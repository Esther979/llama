#!/usr/bin/env python3
"""
Back-test of loss_model.py's Morpho rules on the 25 Aug 2026 PT-reUSD liquidations.

  python3 backtest_reusd.py            # prints one GATE PASS / GATE FAIL line per check

Figures (only these) from the HackMD analysis, hackmd.io/@kanveuler/BJe_n1ivGe:
  LLTV 0.915; borrowers' pre-attack LTV 0.8937 to 0.9101; oracle 0.970990973 -> 0.944085974;
  19 borrowers liquidated; debt repaid 36,144,246.114977; oracle-marked bonus 945,796.075867.
Cross-check with our own Pendle data: data/pendle_history_0x13285bcb.json (hourly PT-reUSD ohlcv).
The model is run through loss_model.position_loss / lif, not re-implemented here.
"""
import datetime as dt
import json
import os

from loss_model import PRESETS, Position, Scenario, lif, position_loss

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE = "hackmd.io/@kanveuler/BJe_n1ivGe"
FIGURES = {
    "lltv": 0.915,
    "ltv_min": 0.8937,
    "ltv_max": 0.9101,
    "oracle_before": 0.970990973,
    "oracle_after": 0.944085974,
    "borrowers_liquidated": 19,
    "debt_repaid_usd": 36144246.114977,
    "bonus_usd": 945796.075867,
}
PENDLE_FILE = "pendle_history_0x13285bcb.json"
CANDLE_UTC = dt.datetime(2026, 8, 25, 4, tzinfo=dt.timezone.utc)
CANDLE_OPEN, CANDLE_LOW = 0.9708, 0.9420


def model(ltv, drop, lltv):
    """Run loss_model for one borrower: collateral 1, debt = ltv, oracle falls by `drop`."""
    s = Scenario("reusd_backtest", 3, drop, 0.0, None, SOURCE, False)
    p = Position("borrower", 1.0, ltv, lltv, oracle_tracks_market=True)
    return position_loss(s, p)["branches"][0]


def check(name, expected, got, tol, ok=None):
    ok = abs(got - expected) <= tol if ok is None else ok
    return {"name": name, "expected": expected, "got": got, "tolerance": tol, "pass": bool(ok)}


def run(data_dir=os.path.join(HERE, "data")):
    f = FIGURES
    drop = 1 - f["oracle_after"] / f["oracle_before"]
    hi, lo = model(f["ltv_max"], drop, f["lltv"]), model(f["ltv_min"], drop, f["lltv"])
    checks = [
        check("distance to liquidation at LTV 0.9101 (bps)", 53, hi["liquidation_drop_threshold"] * 1e4, 1),
        check("distance to liquidation at LTV 0.8937 (bps)", 233, lo["liquidation_drop_threshold"] * 1e4, 1),
        check("oracle drop (bps)", 277.09, drop * 1e4, 0.01),
    ]
    # every LTV in the reported range must be liquidated (step 0.0001); the 19 borrowers all sat in it
    grid = [round(f["ltv_min"] + i * 1e-4, 4) for i in range(int(round((f["ltv_max"] - f["ltv_min"]) / 1e-4)) + 1)]
    n_liq = sum(model(x, drop, f["lltv"])["liquidated"] for x in grid)
    checks.append(check(f"model liquidates every LTV in [0.8937, 0.9101] ({len(grid)} points; "
                        f"{f['borrowers_liquidated']} borrowers were liquidated)", len(grid), n_liq, 0))
    checks.append(check("bonus / repaid = LIF - 1", lif(f["lltv"]) - 1, f["bonus_usd"] / f["debt_repaid_usd"], 1e-6))

    # cross-check with our own Pendle data
    path = os.path.join(data_dir, PENDLE_FILE)
    candle = None
    if os.path.exists(path):
        with open(path) as fh:
            rows = json.load(fh)["pt_ohlcv"]["results"].strip().split("\n")
        hdr, ts = rows[0].split(","), int(CANDLE_UTC.timestamp())
        for r in rows[1:]:
            v = r.split(",")
            if int(v[0]) == ts:
                candle = {k: float(x) for k, x in zip(hdr, v) if x != ""}
    if candle is None:
        checks.append(check(f"Pendle candle {CANDLE_UTC:%Y-%m-%d %H:%M} UTC in data/{PENDLE_FILE}", 1, 0, 0))
    else:
        checks.append(check("Pendle hourly open 2026-08-25 04:00 UTC", CANDLE_OPEN, candle["open"], 5e-5))
        checks.append(check("Pendle hourly low 2026-08-25 04:00 UTC", CANDLE_LOW, candle["low"], 5e-5))
        pdrop = 1 - candle["low"] / candle["open"]
        preset = next(s for s in PRESETS if s.key == "oracle_dip")
        checks.append(check("oracle_dip preset shock = Pendle low / open drop", pdrop, preset.shock, 1e-9))
        checks.append(check("Pendle drop and oracle drop agree within 50 bps", 0, (pdrop - drop) * 1e4, 50))
    n_pass = sum(c["pass"] for c in checks)
    return {"name": "backtest_reusd", "event": "PT-reUSD on Morpho, 2026-08-25 (oracle manipulation)",
            "source": SOURCE, "figures": f, "oracle_drop": drop, "lif": lif(f["lltv"]),
            "checks": checks, "passed": n_pass, "total": len(checks), "all_pass": n_pass == len(checks)}


def main():
    r = run()
    print(f"oracle drop {r['oracle_drop']:.6%}, LIF {r['lif']:.6f}\n")
    for c in r["checks"]:
        print(f"GATE {'PASS' if c['pass'] else 'FAIL'}  {c['name']}: got {c['got']:.6g}, "
              f"expected {c['expected']:.6g} +/- {c['tolerance']:g}")
    print(f"\n{r['passed']}/{r['total']} checks pass")


if __name__ == "__main__":
    main()
