#!/usr/bin/env python3
"""
Collect everything the dashboard needs into ONE file: data/dashboard.json.

  python3 export_dashboard.py --market 0x47ad2cd1dd15739a7a035b9d3b7828d916fef77e \
      --curves data/exit_curve_0x47ad2cd1_10m.csv data/exit_curve_0x47ad2cd1_cap.csv --L 0.5 \
      [--debt 8800000] [--lltv 0.915] [--must-sell] \
      [--oracle-tracks-underlying true|false|unknown] [--oracle-tracks-market true|false|unknown]

--L drives the legacy top-level decision_grid (placeholder). The "scenarios" list uses
loss_model.py: one L per preset, for the position described by --debt / --lltv / ... .

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
from loss_model import PRESETS, Position, position_loss

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


def tri(v):
    v = v.lower()
    if v not in ("true", "false", "unknown"):
        raise argparse.ArgumentTypeError("expected true, false or unknown")
    return {"true": True, "false": False, "unknown": None}[v]


def run_grid(curve, L, pstep):
    """decision_grid rows for p = 0, pstep, ..., 1 and the two thresholds read off them."""
    max_x = max(x for x, _ in curve)
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
    return grid, {"start_selling_p": start_p, "sell_to_cap_p": cap_p}


def build(market, curves, L, pstep, data_dir, debt=0.0, lltv_arg=None, can_hold=True,
          oracle_tracks_underlying=None, oracle_tracks_market=None):
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

    grid, thresholds = run_grid(curve, L, pstep)

    # ---- per-scenario L from loss_model.py ----
    if debt < 0 or debt >= notional:
        sys.exit(f"--debt must be in [0, {notional:,.0f}) (collateral = notional_usd)")
    if lltv_arg is not None:
        lltv, lltv_source = lltv_arg, "--lltv"
    else:
        found = sorted({x["lltv"] for x in lending if isinstance(x["lltv"], float)})
        if len(found) == 1:
            lltv, lltv_source = found[0], f"morpho_markets_{pt[:10]}.json"
        elif len(found) > 1:
            sys.exit(f"several Morpho LLTVs in data/ ({found}); pass --lltv")
        elif debt > 0:
            sys.exit("no Morpho LLTV in data/ (run fetch_data.py step4) and --debt > 0; pass --lltv")
        else:
            lltv, lltv_source = Position.lltv, "loss_model default (unused: no debt)"
    if debt > 0 and debt / notional >= lltv:
        print(f"warning: LTV {debt / notional:.4f} >= LLTV {lltv} - position is already liquidatable",
              file=sys.stderr)
    equity = notional - debt
    scale = notional / equity
    pos = Position("dashboard", notional, debt, lltv, can_hold,
                   oracle_tracks_underlying, oracle_tracks_market)
    # exit cost per unit of equity: slippage x collateral / equity
    eq_curve = [(x, s * scale) for x, s in curve]
    scenarios = []
    for sc in PRESETS:
        r = position_loss(sc, pos)
        exact = abs(r["L_high"] - r["L_low"]) < 1e-12
        sgrid, sthr = run_grid(eq_curve, r["L_high"], pstep)
        thr = [b["liquidation_drop_threshold"] for b in r["branches"]]
        scenarios.append({
            "key": sc.key, "layer": sc.layer, "shock": sc.shock, "permanent": sc.permanent,
            "hours": sc.hours, "source": sc.source, "analogy": sc.analogy,
            "L_low": r["L_low"], "L_high": r["L_high"], "oracle_known": r["oracle_known"],
            "L_used": r["L_high"],
            "L_basis": "exact" if exact else "L_high (oracle behaviour unknown: worst branch)",
            "branches": [{"oracle_falls": b["oracle_falls"], "liquidated": b["liquidated"],
                          "loss_of_equity": b["loss_of_equity"], "loss_usd": b["loss_usd"],
                          "bad_debt_usd": b["bad_debt_usd"]} for b in r["branches"]],
            "liquidated": [b["liquidated"] for b in r["branches"]],
            "liquidation_drop_threshold": thr[0],
            "bad_debt_usd": max(b["bad_debt_usd"] for b in r["branches"]),
            "thresholds": sthr,
            "decision_grid": sgrid,
        })

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
        "thresholds": thresholds,
        "decision_grid": grid,
        "position_inputs": {
            "collateral_usd": notional, "debt_usd": debt, "equity_usd": equity,
            "lltv": lltv, "lltv_source": lltv_source, "can_hold": can_hold,
            "oracle_tracks_underlying": oracle_tracks_underlying,
            "oracle_tracks_market": oracle_tracks_market,
            "exit_cost_scale": scale,
            "note": "scenarios[].decision_grid is per unit of equity: exit cost = slippage x exit_cost_scale "
                    "(collateral / equity), stay cost = p x L_used. The unsold part keeps the full "
                    "position's L; the deleveraging effect of a sale is not modelled.",
        },
        "scenarios": scenarios,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--market", required=True)
    ap.add_argument("--curves", nargs="+", required=True)
    ap.add_argument("--L", type=float, default=0.5)
    ap.add_argument("--pstep", type=float, default=0.005)
    ap.add_argument("--data-dir", default=os.path.join(HERE, "data"))
    ap.add_argument("--out", default=None)
    ap.add_argument("--debt", type=float, default=0.0, help="USD borrowed against the PT (0 = unlevered)")
    ap.add_argument("--lltv", type=float, default=None, help="default: from the Morpho market in data/")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--can-hold", dest="can_hold", action="store_true", default=True)
    g.add_argument("--must-sell", dest="can_hold", action="store_false")
    ap.add_argument("--oracle-tracks-underlying", type=tri, default=None, metavar="true|false|unknown")
    ap.add_argument("--oracle-tracks-market", type=tri, default=None, metavar="true|false|unknown")
    a = ap.parse_args()
    out = build(a.market, a.curves, a.L, a.pstep, a.data_dir, a.debt, a.lltv, a.can_hold,
                a.oracle_tracks_underlying, a.oracle_tracks_market)
    path = a.out or os.path.join(a.data_dir, "dashboard.json")
    with open(path, "w") as f:
        json.dump(out, f, indent=1)
    t = out["thresholds"]
    print(f"saved -> {path}")
    print(f"max exit now {out['max_exit_fraction']:.0%} of ${out['position']['notional_usd']:,.0f}; "
          f"start selling at p>={t['start_selling_p']}, sell to cap at p>={t['sell_to_cap_p']} (L={a.L})")
    pi = out["position_inputs"]
    print(f"position: debt ${pi['debt_usd']:,.0f}, LLTV {pi['lltv']} ({pi['lltv_source']}), "
          f"can_hold={pi['can_hold']}, exit cost x{pi['exit_cost_scale']:.3f}")
    for s in out["scenarios"]:
        t = s["thresholds"]
        L = (f"{s['L_low']:.4f}" if s["L_basis"] == "exact" else f"{s['L_low']:.4f}-{s['L_high']:.4f}")
        print(f"  {s['key']:13s} L={L:15s} liquidated={s['liquidated']}  "
              f"start p>={t['start_selling_p']}  cap p>={t['sell_to_cap_p']}")


if __name__ == "__main__":
    main()
