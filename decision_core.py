"""
Stay / partial-exit / exit decision for ONE affected pocket.
All quantities are fractions of the pocket's current value.
"""
import csv
import sys
from dataclasses import dataclass
from typing import List, Tuple


@dataclass
class Scenario:
    name: str
    prob: float   # probability it materialises within the horizon (mutually exclusive)
    loss: float   # loss on the pocket if it does, e.g. 0.5 = lose half


def slippage_at(x: float, curve: List[Tuple[float, float]]) -> float:
    """Average slippage when selling fraction x of the pocket.
    curve = [(fraction_sold, avg_slippage), ...] from real quotes (e.g. Pendle Convert API)."""
    pts = sorted(curve)
    if x <= pts[0][0]:
        return pts[0][1]
    for (x0, s0), (x1, s1) in zip(pts, pts[1:]):
        if x <= x1:
            return s0 + (s1 - s0) * (x - x0) / (x1 - x0)
    return pts[-1][1]


def load_curve(*paths: str) -> List[Tuple[float, float]]:
    """Read one or more data/exit_curve_*.csv written by fetch_data.py step3 and merge them.
    All files must come from the same --notional (checked via usd / fraction).
    Uses realized_loss_vs_mark when present, else |price_impact_raw|."""
    merged, notional = {}, None
    for path in paths:
        with open(path) as f:
            for r in csv.DictReader(f):
                frac = float(r["fraction"])
                n = float(r["usd"]) / frac
                if notional is None:
                    notional = n
                elif abs(n - notional) > 1e-6 * notional:
                    sys.exit(f"{path} was run with notional {n:,.0f}, others with {notional:,.0f} - "
                             f"only merge files from the same --notional")
                v = r.get("realized_loss_vs_mark") or r.get("price_impact_raw")
                if v in (None, ""):
                    continue
                merged[frac] = abs(float(v))
    if not merged:
        sys.exit(f"no usable rows in {', '.join(paths)}")
    return sorted(merged.items())


def load_usd_curve(*paths: str) -> List[Tuple[float, float]]:
    """Same files as load_curve, keyed by the USD size of the sale instead of the fraction, so quotes taken
    with different --notional can be merged (the AMM's cost depends on the amount sold, not on who sells).
    Duplicate sizes keep the last file's value."""
    merged = {}
    for path in paths:
        with open(path) as f:
            for r in csv.DictReader(f):
                v = r.get("realized_loss_vs_mark") or r.get("price_impact_raw")
                if v not in (None, ""):
                    merged[float(r["usd"])] = abs(float(v))
    if not merged:
        sys.exit(f"no usable rows in {', '.join(paths)}")
    return sorted(merged.items())


def expected_loss(scens: List[Scenario]) -> float:
    return sum(s.prob * s.loss for s in scens)


def cvar(scens: List[Scenario], alpha: float = 0.95) -> float:
    """Expected loss in the worst (1 - alpha) tail, 'no event' (loss 0) included."""
    dist = [(s.loss, s.prob) for s in scens]
    dist.append((0.0, max(0.0, 1.0 - sum(s.prob for s in scens))))
    dist.sort(reverse=True)
    tail, need, acc = 1.0 - alpha, 1.0 - alpha, 0.0
    for loss, p in dist:
        take = min(p, need)
        acc += take * loss
        need -= take
        if need <= 1e-12:
            break
    return acc / tail


def decide(scens: List[Scenario], curve: List[Tuple[float, float]],
           carry_lost: float = 0.0, steps: int = 100) -> dict:
    """carry_lost: yield given up per unit sold (e.g. remaining fixed PT yield minus what
    the cash earns elsewhere until maturity)."""
    el = expected_loss(scens)
    # Never extrapolate past the largest size that got a real quote: beyond it the AMM
    # refused (e.g. Pendle "MarketProportionTooHigh"), so that part cannot be sold now.
    max_x = max(x for x, _ in curve)
    best_x, best_cost = 0.0, el
    xs = [i / steps for i in range(steps + 1) if i / steps <= max_x + 1e-12]
    if abs(xs[-1] - max_x) > 1e-12:
        xs.append(max_x)                            # the cap itself, when it is not on the grid
    for x in xs:
        cost = (x * (slippage_at(x, curve) + carry_lost) if x > 0 else 0.0) + (1 - x) * el
        if cost < best_cost - 1e-12:
            best_x, best_cost = x, cost
    capped = max_x < 1.0 - 1e-12
    full_exit = None if capped else slippage_at(1.0, curve) + carry_lost
    if best_x == 0:
        verdict = "STAY"
    elif best_x >= 1.0 - 1e-12:
        verdict = "EXIT"
    elif capped and best_x >= max_x - 1e-12:
        verdict = f"EXIT {best_x:.0%} NOW (capacity limit)"
    else:
        verdict = f"PARTIAL EXIT {best_x:.0%}"
    return {
        "verdict": verdict,
        "expected_loss_if_stay": el,
        "cvar95_if_stay": cvar(scens),
        "cost_full_exit": full_exit,
        "max_exit_now": max_x,
        "best_exit_fraction": best_x,
        "stuck_fraction": (1 - best_x) if capped and best_x >= max_x - 1e-12 else 0.0,
        "expected_total_cost_at_best": best_cost,
        # the probability at which full exit and staying break even, per scenario
        "break_even_prob": {} if full_exit is None else
        {s.name: full_exit / s.loss for s in scens if s.loss > 0},
        "loss_contribution": {s.name: s.prob * s.loss for s in scens},
    }


if __name__ == "__main__":
    # Usage: python3 decision_core.py [data/exit_curve_A.csv data/exit_curve_B.csv ...]
    # Several CSVs from the same --notional are merged. Without a CSV it falls back to the
    # brief's illustrative curve (11% to exit everything).
    if len(sys.argv) > 1:
        curve = load_curve(*sys.argv[1:])
        print(f"real exit curve from {', '.join(sys.argv[1:])}: {curve}")
    else:
        curve = [(0.10, 0.015), (0.25, 0.03), (0.50, 0.06), (1.00, 0.11)]
        print("illustrative exit curve (no CSV given)")
    for p in (0.05, 0.15, 0.30):
        scens = [Scenario("issuer insolvency", p, 0.50)]
        r = decide(scens, curve)
        fe = "n/a (capacity)" if r["cost_full_exit"] is None else f"{r['cost_full_exit']:.3f}"
        be = r["break_even_prob"].get("issuer insolvency")
        print(f"p={p:.2f}  {r['verdict']:<18} E[L]={r['expected_loss_if_stay']:.3f}  "
              f"CVaR95={r['cvar95_if_stay']:.3f}  full_exit={fe}  "
              f"best_cost={r['expected_total_cost_at_best']:.4f}  "
              f"break_even_p={'n/a' if be is None else f'{be:.2f}'}"
              + (f"  stuck={r['stuck_fraction']:.0%}" if r["stuck_fraction"] else ""))
