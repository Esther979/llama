"""
Incidents with three outcomes, exact break-even probabilities, exit now vs later, lender role.
Used by export_dashboard.py.

An incident is what the detection module reports (node, type, how bad). Given the incident, three outcomes:
  resolved  false alarm or fixed quickly: loss close to zero
  partial   price damaged (recoverable or limited bad debt)
  severe    permanent loss (theft, total depeg)
Each outcome points to a loss_model preset; its probability is a default the manager can change.

Break-even probabilities (exact, from the exit curve; no p grid):
  p_start          = cost of the first quoted sale / L          optimizer starts selling above it
  p_exit_sellable  = average cost of selling up to the cap / L  brief's "exit cost / loss": above it, exiting the
                                                                sellable part costs less than keeping it
  p_sell_to_cap    = marginal cost at the cap / L               optimizer sells all it can above it
Costs include gas and are per unit of equity (x exit_cost_scale) for levered positions.
"""
from decision_core import Scenario as DScenario, cvar, decide, slippage_at
from loss_model import PRESETS, Position, Scenario, position_loss
from reasoning import NUM, derived, ev, fmt

PRESET = {s.key: s for s in PRESETS}
OUTCOMES = ("resolved", "partial", "severe")


def depeg_partial(cal):
    """Preset for the 'partial' depeg outcome: median day-30 loss of the calibrated partial episodes."""
    return Scenario("depeg_partial", 2, cal["median_loss_at_horizon"]["partial"], 1.0, None,
                    f"median day-30 loss of the {cal['counts']['partial']} 'partial' stablecoin depeg episodes "
                    f"({cal['source']}, {cal['data_from']}..{cal['data_to']}); level assumed to persist", True)


def incident_types(cal):
    p_dep = cal["probabilities"] if cal else None
    dep_src = (f"{cal['n_episodes']} stablecoin depeg episodes (close < {cal['rules']['start_below']} after a "
               f"functioning month, >= 2 days; {cal['coins']} USD stablecoins, {cal['data_from']}..{cal['data_to']}, "
               f"DeFiLlama): resolved = back >= {cal['rules']['functioning_median']} within "
               f"{cal['rules']['resolved_within_days']} days, severe = below {cal['rules']['severe_below_at_horizon']} "
               f"on day {cal['rules']['horizon_days']}; range over 3 samples "
               + ", ".join(f"{o} {cal['range'][o][0]:.1%}-{cal['range'][o][1]:.1%}" for o in OUTCOMES)
               + " (calibrate_depeg.py)") if cal else None
    return [
        {"key": "underlying_depeg", "layer": 2, "type": "depeg",
         "description": "the underlying (sUSDe / USDe) trades below 0.97",
         "outcomes": {"resolved": "usde_mild", "partial": "depeg_partial", "severe": "issuer_total"},
         "severe_alternatives": ["issuer_half"],
         "probabilities": p_dep or {"resolved": 0.0, "partial": 0.0, "severe": 0.0},
         "probability_evidence": ev("C", dep_src) if p_dep else
         ev("D", "no calibration file: run calibrate_depeg.py")},
        {"key": "oracle_dip", "layer": 3, "type": "oracle",
         "description": "the PT market price / lending oracle drops sharply",
         "outcomes": {"resolved": None, "partial": "oracle_dip", "severe": None},
         "severe_alternatives": [],
         "probabilities": {"resolved": 0.5, "partial": 0.5, "severe": 0.0},
         "probability_evidence": ev("D", "no historical sample in our data (one event: PT-reUSD 25 Aug 2026, "
                                         "recovered within 5h); placeholder 50 / 50, set by the manager. No severe "
                                         "anchor, so severe = 0")},
    ]


# ------------------------------------------------------------------ exit costs (with gas)
def _interp(x, pts):
    return slippage_at(x, pts) if pts else 0.0


def cum_cost(x, curve, gas_pts, notional):
    """Cost of selling fraction x of the position, in units of position value: x * slippage + gas / notional."""
    return x * slippage_at(x, curve) + _interp(x, gas_pts) / notional if x > 0 else 0.0


def exit_costs(curve, gas_pts, notional):
    pts = sorted(curve)
    x1, cap = pts[0][0], pts[-1][0]
    xp, sp = pts[-2] if len(pts) > 1 else (0.0, 0.0)
    s_cap = pts[-1][1]
    g = sorted(gas_pts) if gas_pts else []
    g_cap = _interp(cap, g)
    g_prev = _interp(xp, g) if len(pts) > 1 else 0.0
    slope = (s_cap - sp) / (cap - xp) if cap > xp else 0.0
    return {"first_size": x1, "cost_first": cum_cost(x1, pts, g, notional) / x1,
            "cap": cap, "cost_avg_cap": cum_cost(cap, pts, g, notional) / cap,
            # left derivative of x * s(x) + gas(x) / N at the cap (s and gas linear on the last segment)
            "cost_marginal_cap": s_cap + cap * slope + ((g_cap - g_prev) / (cap - xp) / notional if cap > xp else 0),
            "gas_usd_first": _interp(x1, g), "gas_usd_cap": g_cap}


def break_even(costs, scale, L):
    f = lambda c: (c * scale / L) if L and L > 0 else None
    return {"p_start": f(costs["cost_first"]), "p_exit_sellable": f(costs["cost_avg_cap"]),
            "p_sell_to_cap": f(costs["cost_marginal_cap"]), "L": L,
            "exit_cost_sellable": costs["cost_avg_cap"] * scale, "sellable_fraction": costs["cap"]}


def check_break_even(be, curve, scale, notional_gas_free=True):
    """decide() on either side of p_start and p_sell_to_cap (curve without gas). Returns failed checks."""
    bad = []
    eq = [(x, s * scale) for x, s in curve]
    cap = max(x for x, _ in curve)
    L = be["L"]
    if not L:
        return bad
    c = exit_costs(curve, None, 1.0)
    p0, pc = c["cost_first"] * scale / L, c["cost_marginal_cap"] * scale / L
    x = lambda p: decide([DScenario("e", min(p, 1.0), L)], eq)["best_exit_fraction"]
    if p0 < 1:
        if x(p0 * 0.999) != 0:
            bad.append(f"sells below p_start {p0:.6g}")
        if x(p0 * 1.001) == 0:
            bad.append(f"does not sell above p_start {p0:.6g}")
    if pc * 1.03 < 1 and x(pc * 1.03) < cap - 1e-9:
        bad.append(f"not at cap above p_sell_to_cap {pc:.6g}")
    if x(pc * 0.97) >= cap - 1e-9:
        bad.append(f"already at cap below p_sell_to_cap {pc:.6g}")
    return bad


# ------------------------------------------------------------------ exit now vs later
def exit_later(curve, gas_pts, notional, pt_price, seized_pt, oracle_drop):
    """Liquidators sell seized_pt into the pool first. Our sale then starts where they stopped on the same curve
    (pool not refilled): sellable = cap - seized, cost = (cum(cap) - cum(seized)) / sellable."""
    pts = sorted(curve)
    cap = pts[-1][0]
    y = seized_pt / (notional / pt_price)
    now = cum_cost(cap, pts, gas_pts, notional) / cap
    out = {"oracle_drop": oracle_drop, "pt_seized": seized_pt, "seized_in_position_units": y,
           "sellable_now": cap, "avg_cost_now": now}
    if y >= cap:
        out.update(sellable_later=0.0, avg_cost_later=None, market_impact_of_liquidations=None,
                   note="liquidations alone use up the pool's quoted capacity")
        return out
    z = cap - y
    later = (y + z) * slippage_at(y + z, pts) - (y * slippage_at(y, pts) if y > 0 else 0.0)
    later = (later + _interp(z, sorted(gas_pts or [])) / notional) / z
    h = min(0.005, cap - y)
    impact = ((y + h) * slippage_at(y + h, pts) - (y * slippage_at(y, pts) if y > 0 else 0.0)) / h
    out.update(sellable_later=z, avg_cost_later=later, market_impact_of_liquidations=impact if y > 0 else 0.0,
               note=None)
    return out


# ------------------------------------------------------------------ incidents
def tail(dist, alpha=0.95):
    """dist = [(prob, loss)]: CVaR (mean of the worst 1 - alpha) and VaR (loss at that quantile)."""
    scens = [DScenario(f"o{i}", p, L) for i, (p, L) in enumerate(dist) if p > 0]
    acc, var = 0.0, 0.0
    for p, L in sorted(dist, key=lambda t: -t[1]):
        acc += p
        if acc >= 1 - alpha - 1e-12:
            var = L
            break
    return cvar(scens, alpha), var


def evaluate(inc, pos, presets, loss_ev, costs, scale, equity):
    """Expected and tail loss of one incident for the position, break-even on the severe probability."""
    rows, dist = [], []
    for o in OUTCOMES:
        key = inc["outcomes"][o]
        p = inc["probabilities"][o]
        if key is None:
            L_lo = L_hi = 0.0 if o == "resolved" else None
            e = ev("D", "by definition: no loss reaches the position" if o == "resolved"
                   else "no historical anchor for this outcome")
            rows.append({"outcome": o, "preset": None, "shock": None, "L_low": L_lo, "L_high": L_hi,
                         "L_used": L_hi, "liquidated": None, "probability": p, "evidence": {"L": e}})
            if L_hi is not None:
                dist.append((p, L_hi))
            continue
        sc = presets[key]
        r = position_loss(sc, pos)
        rows.append({"outcome": o, "preset": key, "shock": sc.shock, "L_low": r["L_low"], "L_high": r["L_high"],
                     "L_used": r["L_high"], "liquidated": [b["liquidated"] for b in r["branches"]],
                     "probability": p, "source": sc.source, "evidence": {"L": loss_ev(sc, r)}})
        dist.append((p, r["L_high"]))
    exp = sum(p * L for p, L in dist)
    cv, var = tail(dist)
    by = {x["outcome"]: x for x in rows}
    sev = by["severe"] if by["severe"]["L_used"] is not None and by["severe"]["probability"] is not None \
        and inc["outcomes"]["severe"] else by["partial"]
    worst = sev["outcome"]
    c = costs["cost_avg_cap"] * scale
    L_res = by["resolved"]["L_used"] or 0.0
    L_sev = sev["L_used"]
    p_part = by["partial"]["probability"] if worst == "severe" else 0.0
    L_part = by["partial"]["L_used"] or 0.0
    be = {"worst_outcome": worst, "L_worst": L_sev, "exit_cost_sellable": c, "exit_cost_value": costs["cost_avg_cap"],
          "exit_cost_scale": scale, "sellable_fraction": costs["cap"],
          "p_worst_alone": c / L_sev if L_sev else None,
          "p_worst_given_default_partial": (max(0.0, (c - L_res - p_part * (L_part - L_res)) / (L_sev - L_res))
                                            if L_sev and L_sev > L_res else None),
          "p_partial": p_part, "alternatives": []}
    for k in inc["severe_alternatives"]:
        L_alt = position_loss(presets[k], pos)["L_high"]
        be["alternatives"].append({"preset": k, "L": L_alt, "p_worst_alone": c / L_alt if L_alt else None})
    return {"key": inc["key"], "layer": inc["layer"], "type": inc["type"], "description": inc["description"],
            "outcomes": rows, "probability_evidence": inc["probability_evidence"],
            "expected_loss": exp, "expected_loss_usd": exp * equity,
            "tail_loss_95": cv, "tail_loss_95_usd": cv * equity, "var_95": var,
            "break_even": be}


def sentence(inc_out, severe_name):
    """Manager sentence; numbers only from the incident's own values (checked)."""
    be = inc_out["break_even"]
    vals = {"p": (be["p_worst_alone"],), "L": (be["L_worst"],), "c": (be["exit_cost_value"],),
            "x": (be["sellable_fraction"],), "rest": (1 - be["sellable_fraction"],)}
    f = lambda k: fmt(vals[k][0], "fraction")
    if be["p_worst_alone"] is None:
        return {"text": f"Given this incident, the {be['worst_outcome']} outcome costs this position nothing "
                        f"({severe_name}), so staying is free whatever its probability.", "numbers": []}
    txt = (f"Given this incident, if you think the probability of the {be['worst_outcome']} outcome "
           f"({severe_name}: loss {f('L')} of equity) is above {f('p')}, exit the sellable {f('x')} now "
           f"(cost {f('c')} of value sold, gas included"
           + (f", x{fmt(be['exit_cost_scale'], 'x')[:-1]} per unit of equity" if be["exit_cost_scale"] > 1 + 1e-9 else "")
           + f"); the other {f('rest')} cannot be sold through the pool now.")
    nums = [f(k) for k in vals] + [fmt(be["exit_cost_scale"], "x")[:-1]]
    pg = be["p_worst_given_default_partial"]
    if be["worst_outcome"] == "severe" and pg is not None and be.get("p_partial"):
        pp = fmt(be["p_partial"], "fraction")
        txt += (f" With the partial outcome at its default {pp}, exiting the sellable part already pays at any "
                f"severe probability." if pg == 0 else
                f" With the partial outcome at its default {pp}, the severe threshold falls to {fmt(pg, 'fraction')}.")
        nums += [pp, fmt(pg, "fraction")]
    for a in be["alternatives"]:
        if a["p_worst_alone"] is not None and abs(a["L"] - be["L_worst"]) > 1e-9:
            extra = (f" If the {be['worst_outcome']} loss is only {fmt(a['L'], 'fraction')} ({a['preset']}), "
                     f"the threshold is {fmt(a['p_worst_alone'], 'fraction')}.")
            txt += extra
            nums += [fmt(a["L"], "fraction"), fmt(a["p_worst_alone"], "fraction")]
    bad = [n for n in NUM.findall(txt) if n not in nums]
    return {"text": txt, "numbers": nums, "unchecked": bad}


# ------------------------------------------------------------------ lender role
def lender(onc, supply, presets, keys, oracle_flags, mech_grade, incidents=None):
    """A lender of the Morpho market: bad debt (from the real borrowers) is taken pro rata from all suppliers
    (Morpho.sol liquidate: totalSupplyAssets -= badDebtAssets). Withdrawals cost no slippage but only the idle
    liquidity (supply - borrow) can leave now."""
    mk = onc["market"]
    tsupply, tborrow = mk["total_supply_assets_usdc"], mk["total_borrow_assets_usdc"]
    liq = tsupply - tborrow
    if supply > tsupply:
        raise ValueError(f"lender supply {supply:,.0f} > market total supply {tsupply:,.0f}")
    out = {"supply_usdc": supply, "total_supply_usdc": tsupply, "total_borrow_usdc": tborrow,
           "utilization": tborrow / tsupply if tsupply else None, "liquidity_usdc": liq,
           "share_of_supply": supply / tsupply, "withdrawable_now_usdc": min(supply, liq),
           "withdrawable_fraction": min(supply, liq) / supply, "locked_fraction": 1 - min(supply, liq) / supply,
           "block": onc["block"], "scenarios": [], "incidents": []}

    def L_of(sc):
        per_branch = None
        for b in onc["borrowers"]:
            if b["borrow_usdc"] <= 0:
                continue
            p = Position(b["address"], b["collateral_usdc"], b["borrow_usdc"], onc["lltv"], True,
                         oracle_flags.get("oracle_tracks_underlying"), oracle_flags.get("oracle_tracks_market"))
            r = position_loss(sc, p)
            bd = [br["bad_debt_usd"] for br in r["branches"]]
            per_branch = bd if per_branch is None else [x + y for x, y in zip(per_branch, bd)]
        per_branch = per_branch or [0.0]
        return [x / tsupply for x in per_branch], per_branch

    for k in keys:
        Ls, bd = L_of(presets[k])
        out["scenarios"].append({"key": k, "bad_debt_usdc_per_branch": bd, "L_low": min(Ls), "L_high": max(Ls)})
    for inc in incidents or []:
        dist, rows = [], []
        for o in OUTCOMES:
            k, p = inc["outcomes"][o], inc["probabilities"][o]
            if k is None:
                L = 0.0 if o == "resolved" else None
            else:
                L = max(L_of(presets[k])[0])
            rows.append({"outcome": o, "preset": k, "probability": p, "L_used": L})
            if L is not None:
                dist.append((p, L))
        cv, var = tail(dist)
        exp = sum(p * L for p, L in dist)
        out["incidents"].append({"key": inc["key"], "outcomes": rows, "expected_loss": exp,
                                 "expected_loss_usdc": exp * supply, "tail_loss_95": cv,
                                 "tail_loss_95_usdc": cv * supply,
                                 "loss_on_locked_part_usdc": exp * supply * out["locked_fraction"]})
    w = out["withdrawable_fraction"]
    out["decision_text"] = (f"Withdrawing costs no slippage, so any expected loss is worth avoiding: withdraw the "
                            f"{fmt(w, 'fraction')} that can leave now ({fmt(out['withdrawable_now_usdc'], 'USD')}); "
                            f"the other {fmt(1 - w, 'fraction')} is locked until borrowers repay or are liquidated, "
                            f"and other lenders withdrawing first shrink what is left.")
    ech = {"grade": "A", "source": f"Ethereum eth_call at block {onc['block']}", "block": onc["block"]}
    out["evidence"] = {
        "supply_usdc": ev("D", "lender size assumed (--lender-supply)"),
        "total_supply_usdc": ech, "total_borrow_usdc": ech, "utilization": ech, "liquidity_usdc": ech,
        "withdrawable_fraction": derived("min(supply, liquidity) / supply", liquidity_usdc="A", supply_usdc="D"),
        "scenarios": derived("sum of loss_model bad debt over the real borrowers / total supply", borrowers="A",
                             formula=mech_grade, shock="C", oracle="D", permanent="D"),
        "incidents": derived("sum over outcomes of probability x lender L", probabilities="C", L="D"),
    }
    return out
