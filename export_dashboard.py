#!/usr/bin/env python3
"""
Collect everything the dashboard needs into ONE file: data/dashboard.json.

  python3 export_dashboard.py --market 0x47ad2cd1dd15739a7a035b9d3b7828d916fef77e \
      --curves data/exit_curve_0x47ad2cd1_10m.csv data/exit_curve_0x47ad2cd1_cap.csv --L 0.5 \
      [--debt 8800000] [--lltv 0.915] [--must-sell] \
      [--oracle-tracks-underlying true|false|unknown] [--oracle-tracks-market true|false|unknown] \
      [--positions data/morpho_positions_0x5613b170.json [--borrower 0xADDRESS]]

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

import backtest_reusd
import onchain_positions
from decision_core import Scenario, decide, load_curve
from loss_model import PRESETS, Position, position_loss
from reasoning import check_texts, decision_texts, derived, ev, overall_weakest, scenario_reasoning, weakest_link

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


def saved_at(path):
    return dt.datetime.fromtimestamp(os.path.getmtime(path), dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def pt_price_of(csv_path, decimals):
    """USD per PT used by fetch_data.py step3 to size the quotes (Pendle /v1/prices/assets)."""
    import csv
    with open(csv_path) as f:
        r = next(csv.DictReader(f))
    return float(r["usd"]) / (int(r["pt_amount_wei"]) / 10 ** decimals)


def refusals(curves, max_x):
    """Quotes above max_x that Pendle refused, read from the raw files next to the curve CSVs."""
    out = []
    for c in curves:
        raw = c.replace("exit_curve_", "exit_quotes_raw_").replace(".csv", ".json")
        for q in load_json(raw) or []:
            if q.get("fraction", 0) > max_x and q.get("status") not in (200, 201):
                msg = str((q.get("response") or {}).get("_error", ""))
                out.append((q["fraction"], "MarketProportionTooHigh" if "MarketProportionTooHigh" in msg
                            else f"HTTP {q.get('status')}", os.path.basename(raw)))
    return sorted(out)


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
          oracle_tracks_underlying=None, oracle_tracks_market=None, positions=None, borrower=None):
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

    morpho_path = os.path.join(data_dir, f"morpho_markets_{pt[:10]}.json")
    morpho = load_json(morpho_path) or []
    src = {
        "pendle": f"Pendle GET /{mk.get('source', 'v2')}/markets/all, fetched {mk.get('fetched_at')} "
                  f"(data/pendle_markets.json)",
        "quotes": f"Pendle POST /v3/sdk/{m.get('chainId')}/convert sell quotes PT -> underlying, saved "
                  f"{saved_at(curves[0])} ({', '.join(os.path.basename(c) for c in curves)})",
        "morpho": f"Morpho GraphQL marketById, saved {saved_at(morpho_path)} (data/{os.path.basename(morpho_path)})"
                  if morpho else None,
    }
    lending = []
    for mm in morpho:
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
        x = lending[-1]
        x["aggregate_liquidation_drop_threshold"] = (1 - x["aggregate_ltv"] / lltv
                                                     if x["aggregate_ltv"] and isinstance(lltv, float) else None)
    pt_dec = next((int((mm.get("collateralAsset") or {})["decimals"]) for mm in morpho
                   if (mm.get("collateralAsset") or {}).get("decimals") is not None), None)
    pt_price = pt_price_of(curves[0], pt_dec if pt_dec is not None else 18)

    grid, thresholds = run_grid(curve, L, pstep)

    # ---- on-chain borrowers (onchain_positions.py) ----
    onc, bor = None, None
    if positions:
        onc = load_json(positions)
        if not onc:
            sys.exit(f"missing {positions} - run onchain_positions.py")
        if not onc.get("all_gates_pass"):
            sys.exit(f"{positions}: not all gates passed - rerun onchain_positions.py")
        if borrower:
            bor = next((b for b in onc["borrowers"] if b["address"] == borrower.lower()), None)
            if not bor or bor["borrow_usdc"] <= 0:
                sys.exit(f"{borrower} has no debt in {positions}")
    elif borrower:
        sys.exit("--borrower needs --positions")
    same_size = bool(bor) and abs(bor["collateral_usdc"] / notional - 1) < 0.01
    if bor:
        if debt:
            sys.exit("--borrower fills the debt: do not pass --debt as well")
        debt = bor["borrow_usdc"] if same_size else bor["ltv"] * notional
        if lltv_arg is None:
            lltv_arg = onc["lltv"]
        if not same_size:
            print(f"note: borrower collateral ${bor['collateral_usdc']:,.0f} != quoted notional ${notional:,.0f}; "
                  f"using its LTV {bor['ltv']:.4f} on our size. For its real size: fetch_data.py step3 --notional "
                  f"{bor['collateral_usdc']:.0f}", file=sys.stderr)

    # ---- per-scenario L from loss_model.py ----
    if debt < 0 or debt >= notional:
        sys.exit(f"--debt must be in [0, {notional:,.0f}) (collateral = notional_usd)")
    if lltv_arg is not None:
        lltv, lltv_source = lltv_arg, (f"on chain, block {onc['block']}" if bor and lltv_arg == onc["lltv"]
                                       else "--lltv")
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

    # ---- evidence grades (see reasoning.py) ----
    validation = backtest_reusd.run(data_dir)
    mech = ev("B" if validation["all_pass"] else "D",
              "github.com/morpho-org/morpho-blue src/Morpho.sol (health check, LIF = min(1.15, 1/(1 - 0.3(1 - LLTV))), "
              f"no close factor); back-test backtest_reusd.py: {validation['passed']}/{validation['total']} checks pass"
              + ("" if validation["all_pass"] else " - FAILED, so graded D"))
    for x in lending:
        x["evidence"] = {k: ev("A", src["morpho"]) for k in ("lltv", "collateral_usd", "borrow_usd", "liquidity_usd",
                                                             "oracle_address", "oracle_type")}
        x["evidence"]["aggregate_ltv"] = derived("borrow_usd / collateral_usd", borrow_usd="A", collateral_usd="A")
        x["evidence"]["aggregate_liquidation_drop_threshold"] = derived(
            "1 - aggregate_ltv / lltv (Morpho health check)", formula=mech["grade"], aggregate_ltv="A", lltv="A")
    oracle_src = ("unknown: Morpho API oracle type "
                  f"'{lending[0]['oracle_type'] if lending else 'n/a'}', oracle contract not read yet; both branches computed")
    chain = (f"Ethereum eth_call at block {onc['block']} ({os.path.basename(positions)}), borrower "
             f"{bor['address']}") if bor else None
    e_in = {
        "collateral": (ev("A", chain) if same_size else
                       ev("D", "position size assumed by us (= notional_usd of the quotes), not Belem's")),
        "debt": (ev("A", chain) if same_size else
                 derived(f"borrower LTV ({chain}) x our assumed position size", ltv="A", position_size="D") if bor else
                 ev("D", "typed in (--debt), not read from chain" if debt > 0 else "default 0: assumed unlevered")),
        "lltv": (ev("A", src["morpho"]) if lltv_source.startswith("morpho_markets") else
                 ev("A", chain) if lltv_source.startswith("on chain") else
                 ev("D", "typed in (--lltv)" if lltv_source == "--lltv" else lltv_source)),
        "can_hold": ev("D", "assumption (--can-hold / --must-sell)"),
        "pt_price": ev("A", f"Pendle GET /v1/prices/assets at quote time (usd / PT amount in "
                            f"{os.path.basename(curves[0])})"),
    }
    for fl, val in (("oracle_tracks_underlying", oracle_tracks_underlying),
                    ("oracle_tracks_market", oracle_tracks_market)):
        e_in[fl] = ev("D", oracle_src if val is None else f"typed in (--{fl.replace('_', '-')}), not verified on-chain")
    # Each derived number is graded only by what it depends on. LTV = 0 whatever the size, so an
    # unlevered LTV depends on the debt input alone; position size enters only USD amounts and the
    # exit costs per fraction of the position (quotes were taken at this size).
    g_coll, g_debt, g_lltv = e_in["collateral"]["grade"], e_in["debt"]["grade"], e_in["lltv"]["grade"]
    e_in["ltv"] = (ev("A", f"{chain}: borrow / (collateral x oracle price)") if bor else
                   derived("debt / collateral", debt_usd=g_debt) if debt == 0 else
                   derived("debt / collateral", debt_usd=g_debt, collateral_usd=g_coll))
    g_ltv = e_in["ltv"]["grade"]
    e_in["scale"] = derived("collateral / equity = 1 / (1 - ltv)", ltv=g_ltv)
    ev_scen = {}
    for sc in PRESETS:
        r = position_loss(sc, pos)
        g_perm = "C" if sc.recovery_source else "D"
        perm = ev(g_perm, f"observed: {sc.recovery_source}" if sc.recovery_source else
                  "assumption: no recovery" if sc.permanent == 1 else "assumption")
        if debt == 0:                                   # L = shock x permanent (can hold) or shock (must sell)
            L_dep = {"shock": "C", "ltv": g_ltv, "can_hold": e_in["can_hold"]["grade"],
                     **({"permanent": g_perm} if can_hold else {})}
            thr_dep = {"ltv": g_ltv}
        else:
            liq = [b["liquidated"] for b in r["branches"]]
            # liquidated branch: residual PT is worth end_value; healthy branch: end_value or sold_value
            uses_perm = any(liq) or can_hold
            L_dep = {"shock": "C", "ltv": g_ltv, "lltv": g_lltv, "formula": mech["grade"],
                     "oracle": e_in["oracle_tracks_underlying" if sc.layer == 2 else "oracle_tracks_market"]["grade"],
                     **({"can_hold": e_in["can_hold"]["grade"]} if not all(liq) else {}),
                     **({"permanent": g_perm} if uses_perm else {})}
            thr_dep = {"formula": mech["grade"], "ltv": g_ltv, "lltv": g_lltv}
        L_ev = derived("loss_model.position_loss (fraction of equity)", **L_dep)
        ev_scen[sc.key] = {
            "shock": ev("C", sc.source),
            "permanent": perm,
            "hours": ev("C", sc.source) if sc.hours is not None else ev("D", "unknown"),
            "L": L_ev,
            "liquidated": derived("shock vs liquidation threshold",
                                  **{k: v for k, v in L_dep.items() if k not in ("permanent", "can_hold")}),
            "threshold": derived("1 - ltv / LLTV" if debt > 0 else "no debt: no threshold", **thr_dep),
            "bad_debt": derived("loss_model.position_loss (USD)", position_size=g_coll, **L_dep),
            "grid": derived("decision_core.decide with L_used and the exit curve (costs per fraction of a "
                            "position of this size)", exit_curve="A", position_size=g_coll, L_used=L_ev["grade"]),
        }
    borrowers_block = None
    if onc:
        cap_pt = max_x * notional / pt_price
        lc, first = onchain_positions.liquidation_curve(onc["borrowers"], onc["oracle_price"], onc["lltv"], cap_pt)
        e_chain = {"grade": "A", "source": f"Ethereum eth_call at block {onc['block']} ({os.path.basename(positions)})",
                   "block": onc["block"]}
        borrowers_block = {
            "block": onc["block"], "block_timestamp": onc["block_timestamp"], "market_id": onc["market_id"],
            "oracle_price": onc["oracle_price"], "lltv": onc["lltv"], "lif": onc["lif"],
            "total_borrow_usdc": onc["market"]["total_borrow_assets_usdc"],
            "discovery": onc["discovery"], "gates_passed": sum(g["pass"] for g in onc["gates"]),
            "gates_total": len(onc["gates"]),
            "list": onc["borrowers"], "distribution": onc["distribution"],
            "capacity_pt": cap_pt, "liquidation_curve": lc, "first_drop_seized_exceeds_capacity": first,
            "selected": bor["address"] if bor else None,
            "evidence": {"list": e_chain, "distribution": e_chain, "oracle_price": e_chain, "lltv": e_chain,
                         "capacity_pt": derived("largest quoted sale in USD (max_exit_fraction x notional_usd, an "
                                                "absolute amount Pendle accepted) / pt_price_usd", exit_curve="A",
                                                pt_price="A"),
                         "liquidation_curve": derived("onchain_positions.liquidation_curve: borrowers at block "
                                                      f"{onc['block']}, full liquidation, LIF", borrowers="A",
                                                      formula=mech["grade"]),
                         "first_drop_seized_exceeds_capacity": derived(
                             "first oracle drop where PT seized > capacity_pt", borrowers="A",
                             formula=mech["grade"], capacity_pt="A")},
        }
    ctx = {"collateral": notional, "debt": debt, "lltv": lltv, "can_hold": can_hold,
           "oracle_tracks_underlying": oracle_tracks_underlying, "oracle_tracks_market": oracle_tracks_market,
           "name": m.get("name") and f"PT-{m.get('name')} (expiry {str(m.get('expiry'))[:10]})",
           "pt": pt, "pt_price": pt_price, "curve": curve, "max_x": max_x, "scale": scale, "pstep": pstep,
           "lending": lending[0] if lending else None, "src": src, "ev": e_in, "ev_scen": ev_scen,
           "borrowers": borrowers_block, "borrower": bor}
    grid_fn = lambda L_, sc_: run_grid([(x, s * sc_) for x, s in curve], L_, pstep)[1]

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
        S = scenario_reasoning(ctx, sc, r, sthr, mech)
        texts = decision_texts(S, sc, r)
        bad = check_texts(S, texts)
        if bad:
            sys.exit(f"GATE FAIL  decision_text for {sc.key} uses numbers not in its reasoning steps: {bad}")
        es = ev_scen[sc.key]
        g_grid = es["grid"]
        scenarios[-1].update({
            "evidence": {"shock": es["shock"], "permanent": es["permanent"], "hours": es["hours"],
                         "L_low": es["L"], "L_high": es["L"], "L_used": es["L"],
                         "branches": es["bad_debt"], "liquidated": es["liquidated"],
                         "liquidation_drop_threshold": es["threshold"], "bad_debt_usd": es["bad_debt"],
                         "thresholds": g_grid, "decision_grid": g_grid},
            "reasoning": S,
            "decision_text": texts,
            "weakest_link": weakest_link(ctx, sc, r, sthr, grid_fn),
        })
    refused = refusals(curves, max_x)
    g_pos = ev("A", src["pendle"])
    placeholder = ev("D", "placeholder L (--L), not from the loss model")

    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "position": {
            "chain_id": m.get("chainId"), "name": m.get("name"), "market": market.lower(),
            "pt": pt, "underlying": und, "expiry": str(m.get("expiry"))[:10],
            "pool_liquidity_usd": d.get("liquidity"), "implied_apy": d.get("impliedApy"),
            "notional_usd": notional,
            "pt_price_usd": pt_price,
            "evidence": {**{k: g_pos for k in ("chain_id", "name", "market", "pt", "underlying", "expiry",
                                                "pool_liquidity_usd", "implied_apy")},
                         "notional_usd": e_in["collateral"], "pt_price_usd": e_in["pt_price"]},
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
            "ltv": debt / notional,
            "borrower": ({k: bor[k] for k in ("address", "collateral_pt", "collateral_usdc", "borrow_usdc", "ltv",
                                              "distance_to_liquidation")} | {"block": onc["block"],
                                                                             "same_size_as_quotes": same_size}
                         if bor else None),
            "evidence": {"collateral_usd": e_in["collateral"], "debt_usd": e_in["debt"],
                         "equity_usd": derived("collateral - debt", collateral_usd=g_coll, debt_usd=g_debt),
                         "lltv": e_in["lltv"], "can_hold": e_in["can_hold"],
                         "oracle_tracks_underlying": e_in["oracle_tracks_underlying"],
                         "oracle_tracks_market": e_in["oracle_tracks_market"],
                         "exit_cost_scale": e_in["scale"],
                         "ltv": e_in["ltv"]},
            "note": "scenarios[].decision_grid is per unit of equity: exit cost = slippage x exit_cost_scale "
                    "(collateral / equity), stay cost = p x L_used. The unsold part keeps the full "
                    "position's L; the deleveraging effect of a sale is not modelled.",
        },
        "scenarios": scenarios,
        **({"borrowers": borrowers_block} if borrowers_block else {}),
        "weakest_link": overall_weakest(scenarios),
        "validation": validation,
        "evidence": {
            "grades": {"A": "measured now from live API / chain data",
                       "B": "mechanism verified in contract source and back-tested",
                       "C": "analogy from another asset's history", "D": "assumption or unknown"},
            "exit_curve": ev("A", src["quotes"]),
            "max_exit_fraction": ev("A", f"largest quoted fraction; " + (
                "; ".join(f"{f:g} refused ({why}, {fn})" for f, why, fn in refused) if refused
                else "no refused quote above it in the raw files")),
            "lending": ev("A", src["morpho"]) if lending else ev("D", "no Morpho data in data/"),
            "assumptions": placeholder, "thresholds": placeholder, "decision_grid": placeholder,
            "mechanism": mech,
        },
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
    ap.add_argument("--positions", help="data/morpho_positions_<id>.json from onchain_positions.py")
    ap.add_argument("--borrower", help="a borrower in --positions: its LTV (and debt if same size) replace --debt")
    a = ap.parse_args()
    out = build(a.market, a.curves, a.L, a.pstep, a.data_dir, a.debt, a.lltv, a.can_hold,
                a.oracle_tracks_underlying, a.oracle_tracks_market, a.positions, a.borrower)
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
        w = s["weakest_link"]
        print(f"  {s['key']:13s} L={L:15s} liquidated={s['liquidated']}  "
              f"start p>={t['start_selling_p']}  cap p>={t['sell_to_cap_p']}  "
              f"weakest: {w['input']} ({w['grade']}) -> {w['alternative']}")
    if "borrowers" in out:
        b = out["borrowers"]
        print(f"borrowers at block {b['block']}: {b['distribution']['n_borrowers']} with debt, debt-weighted LTV "
              f"{b['distribution']['ltv_debt_weighted']:.4f}; seized PT > Pendle capacity from a "
              f"{b['first_drop_seized_exceeds_capacity']} oracle drop")
    w, v = out["weakest_link"], out["validation"]
    print(f"overall weakest link: {w.get('input')} ({w.get('grade')}) in {w.get('scenarios')}")
    print(f"GATE {'PASS' if v['all_pass'] else 'FAIL'}  back-test {v['passed']}/{v['total']}; "
          f"mechanism graded {out['evidence']['mechanism']['grade']}")
    print("GATE PASS  every decision_text number comes from its reasoning steps")


if __name__ == "__main__":
    main()
