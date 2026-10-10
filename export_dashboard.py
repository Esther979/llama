#!/usr/bin/env python3
"""
Collect everything the dashboard needs into ONE file: data/dashboard.json.

  python3 export_dashboard.py --market 0x47ad2cd1dd15739a7a035b9d3b7828d916fef77e \
      --curves data/exit_curve_0x47ad2cd1_10m.csv data/exit_curve_0x47ad2cd1_cap.csv --L 0.5

Reads (written earlier by fetch_data.py):
  data/pendle_markets.json            step1
  data/morpho_markets_<pt[:10]>.json  step4  (optional)
  the exit-curve CSVs                 step3
Schema: see README.md, section "Dashboard data contract".
"""
import argparse
import datetime as dt
import json
import os
import sys

from decision_core import Scenario, decide, load_curve

HERE = os.path.dirname(os.path.abspath(__file__))


def addr(x):
    if isinstance(x, str) and "-" in x and x.split("-", 1)[0].isdigit():
        x = x.split("-", 1)[1]
    return x.lower() if isinstance(x, str) else x


def load_json(path):
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def notional_of(csv_path):
    import csv
    with open(csv_path) as f:
        r = next(csv.DictReader(f))
    return float(r["usd"]) / float(r["fraction"])


def build(market, curves, L, pstep, data_dir):
    mk = load_json(os.path.join(data_dir, "pendle_markets.json"))
    if not mk:
        sys.exit(f"missing {data_dir}/pendle_markets.json - run fetch_data.py step1")
    m = next((x for x in mk["markets"] if addr(x.get("address")) == market.lower()), None)
    if not m:
        sys.exit(f"market {market} not in pendle_markets.json")
    pt, und = addr(m.get("pt")), addr(m.get("underlyingAsset"))
    d = m.get("details") or {}

    curve = load_curve(*curves)
    max_x = max(x for x, _ in curve)
    notional = notional_of(curves[0])

    lending = []
    for mm in load_json(os.path.join(data_dir, f"morpho_markets_{pt[:10]}.json")) or []:
        if "error" in mm:
            continue
        s, o = mm.get("state") or {}, mm.get("oracle") or {}
        try:
            lltv = int(mm.get("lltv")) / 1e18
        except (TypeError, ValueError):
            lltv = mm.get("lltv")
        col, bor = s.get("collateralAssetsUsd"), s.get("borrowAssetsUsd")
        lending.append({
            "protocol": "morpho",
            "market_id": mm.get("marketId") or mm.get("uniqueKey"),
            "loan_asset": (mm.get("loanAsset") or {}).get("symbol"),
            "lltv": lltv,
            "collateral_usd": col, "borrow_usd": bor,
            "liquidity_usd": s.get("liquidityAssetsUsd"),
            "aggregate_ltv": (bor / col) if col and bor else None,
            "oracle_address": o.get("address"), "oracle_type": o.get("type"),
        })

    grid, start_p, cap_p = [], None, None
    n = int(round(1 / pstep))
    for i in range(n + 1):
        p = round(i * pstep, 6)
        r = decide([Scenario("event", p, L)], curve)
        x = r["best_exit_fraction"]
        grid.append({"p": p, "verdict": r["verdict"], "exit_fraction": x,
                     "stuck_fraction": r["stuck_fraction"],
                     "expected_cost": r["expected_total_cost_at_best"],
                     "stay_cost": r["expected_loss_if_stay"]})
        if start_p is None and x > 0:
            start_p = p
        if cap_p is None and x >= max_x - 1e-12:
            cap_p = p

    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "position": {
            "chain_id": m.get("chainId"), "name": m.get("name"), "market": market.lower(),
            "pt": pt, "underlying": und, "expiry": str(m.get("expiry"))[:10],
            "pool_liquidity_usd": d.get("liquidity"), "implied_apy": d.get("impliedApy"),
            "notional_usd": notional,
        },
        "exit_curve": [{"fraction": x, "usd": round(x * notional, 2), "loss": s} for x, s in curve],
        "max_exit_fraction": max_x,
        "lending": lending,
        "assumptions": {"L": L, "L_is_placeholder": True,
                        "note": "L = loss if the event happens; placeholder until the per-layer model exists"},
        "thresholds": {"start_selling_p": start_p, "sell_to_cap_p": cap_p},
        "decision_grid": grid,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--market", required=True)
    ap.add_argument("--curves", nargs="+", required=True)
    ap.add_argument("--L", type=float, default=0.5)
    ap.add_argument("--pstep", type=float, default=0.005)
    ap.add_argument("--data-dir", default=os.path.join(HERE, "data"))
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    out = build(a.market, a.curves, a.L, a.pstep, a.data_dir)
    path = a.out or os.path.join(a.data_dir, "dashboard.json")
    with open(path, "w") as f:
        json.dump(out, f, indent=1)
    t = out["thresholds"]
    print(f"saved -> {path}")
    print(f"max exit now {out['max_exit_fraction']:.0%} of ${out['position']['notional_usd']:,.0f}; "
          f"start selling at p>={t['start_selling_p']}, sell to cap at p>={t['sell_to_cap_p']} (L={a.L})")


if __name__ == "__main__":
    main()
