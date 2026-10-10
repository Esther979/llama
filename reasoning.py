"""
Evidence grades, per-scenario reasoning chain, decision texts and weakest link for dashboard.json.
Used by export_dashboard.py.

Grades, best to worst:
  A  measured now from live API / chain data
  B  mechanism verified in contract source and back-tested (backtest_reusd.py)
  C  analogy from another asset's history
  D  assumption or unknown
A derived number gets the worst grade of what it is computed from; "basis" lists those grades.
"""
import re

from decision_core import slippage_at
from loss_model import Position, Scenario as LossScenario, position_loss

GRADES = "ABCD"
LAYER_RISK = {2: "underlying / issuer", 3: "oracle / market price"}


def worst(*grades):
    return max(grades, key=GRADES.index)


def ev(grade, source):
    return {"grade": grade, "source": source}


def derived(source, **basis):
    """Evidence of a number computed from others: grade = worst grade in basis."""
    return {"grade": worst(*basis.values()), "source": source, "basis": basis}


# ---- number formatting: decision texts may only contain numbers formatted by fmt() from step values
def fmt(v, unit):
    if unit == "USD":
        return f"${v:,.0f}"
    if unit == "probability":
        return f"{v:g}"
    if unit == "x":
        return f"{v:.2f}x"
    if unit == "ratio":
        return f"{v:.4f}"
    if unit and unit.startswith("fraction"):
        return f"{v * 100:.2f}%" if abs(v) >= 0.01 or v == 0 else f"{v * 100:.3g}%"
    return str(v)


def step(n, sid, claim, value, unit, evidence):
    return {"step": n, "id": sid, "claim": claim, "value": value, "unit": unit,
            "evidence": evidence["grade"], "source": evidence["source"],
            **({"basis": evidence["basis"]} if "basis" in evidence else {})}


def scenario_reasoning(ctx, sc, r, thr, mech):
    """Ordered reasoning steps for one scenario. ctx: position context built in export_dashboard;
    sc: loss_model.Scenario; r: position_loss result; thr: this scenario's thresholds; mech: mechanism evidence."""
    C, D, lltv = ctx["collateral"], ctx["debt"], ctx["lltv"]
    levered = D > 0
    g_mech = mech["grade"]
    flag_name = "oracle_tracks_underlying" if sc.layer == 2 else "oracle_tracks_market"
    flag = ctx[flag_name]
    S = []
    # 1 position
    S.append(step(1, "position_size", f"Position: {fmt(C, 'USD')} of {ctx['name']}", C, "USD", ctx["ev"]["collateral"]))
    S.append(step(1, "pt", f"PT {ctx['pt']} at {ctx['pt_price']:.4f} USD per PT", ctx["pt_price"], "USD per PT",
                  ctx["ev"]["pt_price"]))
    bor = ctx.get("borrower")
    if bor:
        S.append(step(1, "borrower", f"Real Morpho borrower {bor['address']} at block {ctx['borrowers']['block']}: "
                      f"its LTV is used for this position", bor["address"], None, ctx["ev"]["ltv"]))
    S.append(step(1, "debt", f"Debt against the PT: {fmt(D, 'USD')}", D, "USD", ctx["ev"]["debt"]))
    S.append(step(1, "ltv", f"Position LTV {fmt(D / C, 'fraction')} (debt / collateral)", D / C, "fraction",
                  ctx["ev"]["ltv"]))
    S.append(step(1, "lltv", f"Morpho LLTV {fmt(lltv, 'fraction')}", lltv, "fraction", ctx["ev"]["lltv"]))
    S.append(step(1, "can_hold", "Can hold to recovery / maturity" if ctx["can_hold"]
                  else "Must sell at the worst point", ctx["can_hold"], None, ctx["ev"]["can_hold"]))
    # 2 shock
    S.append(step(2, "shock", f"Shock: PT value falls {fmt(sc.shock, 'fraction')} at the worst point "
                  f"({LAYER_RISK[sc.layer]} risk)", sc.shock, "fraction", ctx["ev_scen"][sc.key]["shock"]))
    S.append(step(2, "permanent", f"{fmt(sc.permanent, 'fraction')} of the shock is still there at the end",
                  sc.permanent, "fraction", ctx["ev_scen"][sc.key]["permanent"]))
    # 3 oracle
    if not levered:
        S.append(step(3, "oracle", "Oracle behaviour not relevant: no debt, so no liquidation",
                      "not relevant (no debt)", None, ctx["ev"]["debt"]))
    else:
        v = "unknown, both branches" if flag is None else flag
        claim = ("Unknown whether the lending oracle falls with the shock: both branches computed" if flag is None
                 else f"Lending oracle {'falls' if flag else 'does not fall'} with the shock")
        S.append(step(3, "oracle", claim, v, None, ctx["ev"][flag_name]))
    if ctx["lending"]:
        m = ctx["lending"]
        S.append(step(3, "oracle_type", f"Morpho API oracle type: {m['oracle_type']} ({m['oracle_address']})",
                      m["oracle_type"], None, ev("A", ctx["src"]["morpho"])))
    # 4 liquidation threshold vs shock
    if levered:
        t = r["branches"][0]["liquidation_drop_threshold"]
        above = sc.shock > t
        S.append(step(4, "threshold",
                      f"Liquidation if the oracle falls more than {fmt(t, 'fraction')} (1 - LTV / LLTV); "
                      f"shock {fmt(sc.shock, 'fraction')} is {'above' if above else 'below'} it, so "
                      + ("liquidated if the oracle falls" if above else "no liquidation in either branch"),
                      t, "fraction", ctx["ev_scen"][sc.key]["threshold"]))
        if any(b["liquidated"] for b in r["branches"]):
            f = next(b["lif"] for b in r["branches"] if b["liquidated"])
            S.append(step(4, "lif", f"Liquidator seizes collateral worth the repaid debt x LIF {fmt(f, 'ratio')}",
                          f, "ratio", mech))
    else:
        S.append(step(4, "threshold", "No debt: no liquidation threshold", None, "fraction",
                      ctx["ev_scen"][sc.key]["threshold"]))
    if ctx["lending"] and ctx["lending"].get("aggregate_liquidation_drop_threshold") is not None:
        at = ctx["lending"]["aggregate_liquidation_drop_threshold"]
        S.append(step(4, "market_threshold",
                      f"Morpho market as a whole (aggregate LTV {fmt(ctx['lending']['aggregate_ltv'], 'fraction')}) "
                      f"is liquidatable after a {fmt(at, 'fraction')} oracle fall; shock is "
                      f"{'above' if sc.shock > at else 'below'} it", at, "fraction",
                      derived("1 - aggregate_ltv / LLTV", formula=g_mech, aggregate_ltv="A", lltv="A")))
    # 5 L
    L_ev = ctx["ev_scen"][sc.key]["L"]
    if abs(r["L_high"] - r["L_low"]) < 1e-12:
        claim = f"Loss if it happens: {fmt(r['L_high'], 'fraction')} of equity"
    else:
        lo_b = min(r["branches"], key=lambda b: b["loss_of_equity"])
        lo_d, hi_d = ("falls", "does not fall") if lo_b["oracle_falls"] else ("does not fall", "falls")
        claim = (f"Loss if it happens: {fmt(r['L_low'], 'fraction')} if the oracle {lo_d}, "
                 f"{fmt(r['L_high'], 'fraction')} of equity if it {hi_d}; decision uses the high end")
    S.append(step(5, "L", claim, {"low": r["L_low"], "high": r["L_high"]}, "fraction of equity", L_ev))
    if levered:
        bd = max(b["bad_debt_usd"] for b in r["branches"])
        S.append(step(5, "bad_debt", f"Bad debt left to lenders (worst branch): {fmt(bd, 'USD')}", bd, "USD",
                      ctx["ev_scen"][sc.key]["bad_debt"]))
    # 6 exit capacity and cost
    curve, max_x = ctx["curve"], ctx["max_x"]
    qev = ev("A", ctx["src"]["quotes"])
    S.append(step(6, "capacity", f"Pendle can absorb {fmt(max_x, 'fraction')} of the position "
                  f"({fmt(max_x * C, 'USD')}) in one sale now", max_x, "fraction", qev))
    S.append(step(6, "stuck", f"{fmt(1 - max_x, 'fraction')} cannot be sold through the pool now", 1 - max_x,
                  "fraction", qev))
    S.append(step(6, "cost_min", f"Cost of the smallest quoted sale: {fmt(curve[0][1], 'fraction of value sold')}",
                  curve[0][1], "fraction of value sold", qev))
    c_cap = slippage_at(max_x, curve)
    S.append(step(6, "cost_cap", f"Cost of selling up to the limit: {fmt(c_cap, 'fraction of value sold')}",
                  c_cap, "fraction of value sold", qev))
    bb = ctx.get("borrowers")
    if bb:
        fd = bb["first_drop_seized_exceeds_capacity"]
        S.append(step(6, "market_liquidations",
                      (f"Morpho liquidations would seize more PT than the pool can absorb from a {fmt(fd, 'fraction')} "
                       f"oracle fall ({bb['distribution']['n_borrowers']} borrowers read on chain)") if fd is not None
                      else "Morpho liquidations stay below the pool's capacity for oracle falls up to 10%",
                      fd, "fraction", bb["evidence"]["first_drop_seized_exceeds_capacity"]))
    if levered:
        S.append(step(6, "exit_cost_scale", f"Per unit of equity, exit cost is x{ctx['scale']:.2f} "
                      "(collateral / equity)", ctx["scale"], "x", ctx["ev"]["scale"]))
    # 7 thresholds on p
    g_ev = ctx["ev_scen"][sc.key]["grid"]
    sp, cp = thr["start_selling_p"], thr["sell_to_cap_p"]
    S.append(step(7, "start_selling_p", f"Start selling at p >= {fmt(sp, 'probability')}" if sp is not None
                  else "Never sells on the p grid", sp, "probability", g_ev))
    S.append(step(7, "sell_to_cap_p", f"Sell to the limit at p >= {fmt(cp, 'probability')}" if cp is not None
                  else "Never sells to the limit on the p grid", cp, "probability", g_ev))
    return S


def decision_texts(S, sc, r):
    """Sentence templates for the three p zones. Numbers come only from the steps via fmt()."""
    by = {s["id"]: s for s in S}

    def t(sid, part=None):
        s = by[sid]
        v = s["value"][part] if part else s["value"]
        return fmt(v, s["unit"])

    sp, cp = by["start_selling_p"]["value"], by["sell_to_cap_p"]["value"]
    levered = by["debt"]["value"] > 0
    per_eq = f", x{t('exit_cost_scale')[:-1]} per unit of equity" if levered else ""
    risk = LAYER_RISK[sc.layer]
    L_word = (f"L = {t('L', 'high')} of equity" if r["L_high"] - r["L_low"] < 1e-12
              else f"L = {t('L', 'high')} of equity, the high end of {t('L', 'low')} to {t('L', 'high')}")
    out = {}
    if sp is None:
        why = (f"the {t('shock')} drop is not permanent ({t('permanent')} remains) and the position can hold"
               if r["L_high"] == 0 else "the exit cost exceeds the expected loss at every p")
        out["stay"] = {"p_from": 0, "p_to": None,
                       "text": f"At p={{p}}, stay: in this scenario {L_word}, because {why}; selling never pays."}
        out["partial"] = out["sell_to_cap"] = None
        return out
    out["stay"] = {"p_from": 0, "p_to": sp,
                   "text": f"At p={{p}}, the expected loss of staying ({L_word}) is too small to pay for selling "
                           f"even the smallest quoted size (cost {t('cost_min')} of value sold{per_eq}); stay. "
                           f"Selling starts at p >= {t('start_selling_p')}."}
    if cp is None or cp > sp:
        tail = (f" From p >= {t('sell_to_cap_p')} sell up to the limit." if cp is not None
                else " It never pays to sell all the way to the limit.")
        out["partial"] = {"p_from": sp, "p_to": cp,
                          "text": f"At p={{p}}, sell part of the position: the expected loss on the sold part "
                                  f"({L_word}) exceeds its exit cost, which rises with size up to "
                                  f"{t('cost_cap')} of value sold at the {t('capacity')} capacity limit{per_eq}. "
                                  f"The fraction to sell at this p is in decision_grid.{tail}"}
    else:
        out["partial"] = None
    if cp is not None:
        liq = ""
        if levered and any(b["liquidated"] for b in r["branches"]):
            liq = (f" If the oracle falls, the unsold part is liquidated (shock {t('shock')} is above the "
                   f"{t('threshold')} threshold).")
        out["sell_to_cap"] = {"p_from": cp, "p_to": None,
                              "text": f"At p={{p}}, the expected loss of staying exceeds the marginal exit cost up to "
                                      f"the {t('capacity')} capacity limit (cost {t('cost_cap')} of value sold"
                                      f"{per_eq}); the remaining {t('stuck')} stays exposed to {risk} risk.{liq}"}
    else:
        out["sell_to_cap"] = None
    return out


NUM = re.compile(r"\$?\d[\d,]*(?:\.\d+)?[%x]?")


def check_texts(S, texts):
    """Every number in the decision texts must be a formatted step value. Returns the offending tokens."""
    allowed = set()
    for s in S:
        vals = s["value"].values() if isinstance(s["value"], dict) else [s["value"]]
        for v in vals:
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                allowed.add(fmt(v, s["unit"]))
                if s["unit"] == "x":
                    allowed.add(fmt(v, s["unit"])[:-1])
    bad = []
    for z in texts.values():
        if z:
            bad += [n for n in NUM.findall(z["text"].replace("{p}", "")) if n not in allowed]
    return bad


def weakest_link(ctx, sc, r, thr, grid_fn):
    """Lowest-graded input whose stated alternative changes this scenario's thresholds on p.
    Ties on grade: the larger change wins ("never" counts as p = 1 + pstep); then the order tried.
    grid_fn(L, scale) -> thresholds."""
    C, D = ctx["collateral"], ctx["debt"]
    never = 1 + ctx["pstep"]
    base = dict(collateral_usd=C, debt_usd=D, lltv=ctx["lltv"], can_hold=ctx["can_hold"],
                oracle_tracks_underlying=ctx["oracle_tracks_underlying"],
                oracle_tracks_market=ctx["oracle_tracks_market"])
    flag_name = "oracle_tracks_underlying" if sc.layer == 2 else "oracle_tracks_market"

    def thresholds(s=sc, L_pick="high", **over):
        kw = {**base, **over}
        rr = position_loss(s, Position("alt", **kw))
        L = rr["L_high"] if L_pick == "high" else rr["L_low"]
        return grid_fn(L, kw["collateral_usd"] / (kw["collateral_usd"] - kw["debt_usd"])), L

    def scen(**over):
        d = {k: getattr(sc, k) for k in ("key", "layer", "shock", "permanent", "hours", "source", "analogy")}
        return LossScenario(**{**d, **over})

    cands = []   # (step, id, input, grade, source, alternative, fn)
    if D > 0:
        if ctx[flag_name] is None:
            cands.append((3, "oracle", flag_name, ctx["ev"][flag_name], "oracle does not fall (L_low branch)",
                          lambda: thresholds(L_pick="low")))
        else:
            cands.append((3, "oracle", flag_name, ctx["ev"][flag_name], f"{flag_name} = {not ctx[flag_name]}",
                          lambda: thresholds(**{flag_name: not ctx[flag_name]})))
    alt_perm = 1.0 if sc.permanent < 1 else 0.5
    ev_s = ctx["ev_scen"][sc.key]
    cands.append((2, "permanent", "recovery (permanent part of the shock)", ev_s["permanent"],
                  f"permanent = {alt_perm:g}", lambda: thresholds(s=scen(permanent=alt_perm))))
    cands.append((1, "can_hold", "can_hold", ctx["ev"]["can_hold"], f"can_hold = {not ctx['can_hold']}",
                  lambda: thresholds(can_hold=not ctx["can_hold"])))
    for k in (0.5, 1.5):
        cands.append((2, "shock", "shock size", ev_s["shock"], f"shock x {k:g} = {min(1.0, sc.shock * k):.4f}",
                      lambda k=k: thresholds(s=scen(shock=min(1.0, sc.shock * k)))))
    # the debt alternative changes the LTV: graded by the LTV, explained by the debt's source when grades agree
    e_debt = ctx["ev"]["debt"] if ctx["ev"]["debt"]["grade"] == ctx["ev"]["ltv"]["grade"] else ctx["ev"]["ltv"]
    if D > 0:
        cands.append((1, "debt", "debt_usd", e_debt, "unlevered (debt = 0)",
                      lambda: thresholds(debt_usd=0.0)))
    elif ctx["lending"] and ctx["lending"].get("aggregate_ltv"):
        a = ctx["lending"]["aggregate_ltv"]
        cands.append((1, "debt", "debt_usd", e_debt,
                      f"levered like the Morpho market average (LTV {a:.4f})",
                      lambda: thresholds(debt_usd=a * C)))

    def eff(t1, t2):
        f = lambda v: never if v is None else v
        return sum(abs(f(t1[k]) - f(t2[k])) for k in ("start_selling_p", "sell_to_cap_p"))

    rows = []
    for n, sid, inp, e, alt, fn in cands:
        t_alt, L_alt = fn()
        rows.append({"step": n, "id": sid, "input": inp, "grade": e["grade"], "source": e["source"],
                     "alternative": alt, "L_alt": L_alt, "thresholds_alt": t_alt,
                     "changes_verdict": t_alt != thr, "effect": eff(thr, t_alt)})
    hits = [x for x in rows if x["changes_verdict"]]
    pick = None
    if hits:
        g = worst(*[x["grade"] for x in hits])
        pick = max((x for x in hits if x["grade"] == g), key=lambda x: x["effect"])   # max keeps the first on ties
    return {"step": pick["step"] if pick else None, "id": pick["id"] if pick else None,
            "input": pick["input"] if pick else None, "grade": pick["grade"] if pick else None,
            "source": pick["source"] if pick else None, "alternative": pick["alternative"] if pick else None,
            "thresholds_now": thr, "thresholds_alt": pick["thresholds_alt"] if pick else None,
            "candidates": rows,
            "not_tested": ["position size (needs exit quotes at another size)",
                           "exit curve and LLTV (grade A, measured)"]}


def overall_weakest(scenarios):
    """Across scenarios: lowest grade, then chosen in the most scenarios, then largest total change."""
    picks = [(s["key"], s["weakest_link"]) for s in scenarios if s["weakest_link"]["id"]]
    if not picks:
        return {"id": None, "note": "no tested input changes any scenario's verdict"}
    g = worst(*[w["grade"] for _, w in picks])
    agg = {}
    for key, w in picks:
        if w["grade"] != g:
            continue
        e = next(c["effect"] for c in w["candidates"] if c["id"] == w["id"] and c["alternative"] == w["alternative"])
        a = agg.setdefault(w["id"], {"id": w["id"], "step": w["step"], "input": w["input"], "grade": g,
                                     "source": w["source"], "scenarios": [], "total_effect": 0.0})
        a["scenarios"].append(key)
        a["total_effect"] += e
    best = max(agg.values(), key=lambda a: (len(a["scenarios"]), a["total_effect"]))
    best["why"] = (f"Grade {g} ({best['input']}): changing it to its stated alternative changes the p thresholds "
                   f"in {len(best['scenarios'])} of {len(scenarios)} scenarios; see scenarios[].weakest_link")
    return best
