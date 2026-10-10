#!/usr/bin/env python3
"""
Per-layer loss model:  L = shock (scenario, an assumption with a cited anchor)
                          x transmission (mechanical: contract rules + position data).

  python3 loss_model.py                 # table: preset scenarios x example positions
  python3 loss_model.py --json out.json # same, machine-readable

Morpho Blue rules used here (checked in github.com/morpho-org/morpho-blue, src/Morpho.sol, Sep 2026):
  healthy  <=>  collateral * oraclePrice * LLTV >= debt
  LIF = min(1.15, 1 / (1 - 0.3 * (1 - LLTV)))          (LIQUIDATION_CURSOR 0.3, MAX 1.15)
  seized collateral = repaid debt * LIF / oraclePrice   (no close factor: a full liquidation is allowed)
  collateral exhausted with debt left -> the rest is bad debt for lenders
"""
import argparse
import json
from dataclasses import asdict, dataclass, field
from typing import Optional

LIQUIDATION_CURSOR = 0.3
MAX_LIF = 1.15


def lif(lltv: float) -> float:
    return min(MAX_LIF, 1 / (1 - LIQUIDATION_CURSOR * (1 - lltv)))


@dataclass
class Scenario:
    key: str
    layer: int              # 2 = underlying/issuer, 3 = oracle/market price of the PT
    shock: float            # fall of the PT's value at the worst point, 0..1
    permanent: float        # part of the shock still there at maturity / end of horizon, 0..1
    hours: Optional[float]  # how long the worst point lasted, if known
    source: str
    analogy: bool           # True = observed on another asset, used by analogy


@dataclass
class Position:
    key: str
    collateral_usd: float           # PT value now
    debt_usd: float = 0.0           # borrowed against the PT on Morpho (0 = unlevered)
    lltv: float = 0.915
    can_hold: bool = True           # can wait for recovery / maturity; False = must sell at the worst point
    oracle_tracks_underlying: Optional[bool] = None   # does the lending oracle fall when the underlying falls?
    oracle_tracks_market: Optional[bool] = None       # does it fall when the Pendle market price is pushed down?


# Anchors measured in this repo's data or cited sources (see README / CLAUDE.md).
PRESETS = [
    Scenario("usde_mild", 2, 1 - 0.9838145098294505, 0.0, 24,
             "USDe daily low 0.98381 on 2026-02-01 (DeFiLlama ethena-usde), back near 1.00 after", False),
    Scenario("oracle_dip", 3, 1 - 0.9420 / 0.9708, 0.0, 1,
             "PT-reUSD hourly low 0.9420 vs 0.9708 on 2026-08-25 04:00 UTC (Pendle ohlcv, market 0x13285bcb); "
             "back to -0.4% within 5h", True),
    Scenario("issuer_half", 2, 0.50, 1.0, None,
             "Stream xUSD fell to about $0.50 in Nov 2025 (Decrypt, citing PeckShield); no recovery assumed", True),
    Scenario("issuer_total", 2, 1 - 0.001255291116845859, 1.0, None,
             "Elixir deUSD 0.00126 by 2025-11-20 (DeFiLlama elixir-deusd); no recovery assumed", True),
]


def _one_branch(s: Scenario, p: Position, oracle_falls: bool) -> dict:
    C, D = p.collateral_usd, p.debt_usd
    equity = C - D
    oracle_drop = s.shock if oracle_falls else 0.0
    end_value = 1 - s.shock * s.permanent           # PT value at the end, relative to now
    sold_value = 1 - s.shock                         # value if forced to sell at the worst point
    out = {"oracle_falls": oracle_falls, "liquidated": False, "bad_debt_usd": 0.0,
           "liquidation_drop_threshold": None}

    if D <= 0:                                       # unlevered
        v = end_value if p.can_hold else sold_value
        loss = C * (1 - v)
        out.update(loss_usd=loss, loss_of_equity=loss / C if C else 0.0)
        return out

    threshold = 1 - D / (C * p.lltv)                 # oracle drop that makes the position unhealthy
    out["liquidation_drop_threshold"] = threshold
    if oracle_drop > threshold:
        f = lif(p.lltv)
        seized_units = D * f / (C * (1 - oracle_drop))   # share of PT units taken by the liquidator
        out["liquidated"] = True
        out["lif"] = f
        if seized_units >= 1:                        # collateral exhausted: borrower loses all equity
            repaid = C * (1 - oracle_drop) / f
            out["bad_debt_usd"] = D - repaid
            loss = equity
        else:
            loss = equity - C * (1 - seized_units) * end_value
    else:
        v = end_value if p.can_hold else sold_value
        loss = min(equity, C * (1 - v))              # limited liability: cannot lose more than equity
        if C * v < D:                                # collateral now worth less than debt, not liquidated
            out["bad_debt_usd"] = D - C * v
    out.update(loss_usd=loss, loss_of_equity=loss / equity if equity else 0.0)
    return out


def position_loss(s: Scenario, p: Position) -> dict:
    """Loss of the position's equity in scenario s. If the oracle behaviour that matters is unknown
    (None), both branches are computed and returned as a range instead of guessing."""
    flag = p.oracle_tracks_underlying if s.layer == 2 else p.oracle_tracks_market
    if p.debt_usd <= 0:
        branches = [_one_branch(s, p, False)]        # oracle irrelevant without debt
    elif flag is None:
        branches = [_one_branch(s, p, True), _one_branch(s, p, False)]
    else:
        branches = [_one_branch(s, p, flag)]
    losses = [b["loss_of_equity"] for b in branches]
    return {"scenario": s.key, "position": p.key, "L_low": min(losses), "L_high": max(losses),
            "oracle_known": flag is not None or p.debt_usd <= 0, "branches": branches,
            "shock": s.shock, "source": s.source, "analogy": s.analogy}


EXAMPLE_POSITIONS = [
    Position("A unlevered, can hold", 10e6),
    Position("A' unlevered, must sell", 10e6, can_hold=False),
    Position("B levered LTV 88%", 10e6, 8.80e6),
    Position("C levered LTV 89.5%", 10e6, 8.95e6),
]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", help="write all results to this file")
    a = ap.parse_args()
    rows = [position_loss(s, p) for s in PRESETS for p in EXAMPLE_POSITIONS]
    print(f"LIF at LLTV 0.915 = {lif(0.915):.6f}\n")
    print(f"{'scenario':13s} {'shock':>7s}  {'position':26s} {'L (of equity)':>16s}  liquidated?")
    for r in rows:
        L = (f"{r['L_low']:.1%}" if abs(r["L_high"] - r["L_low"]) < 1e-12
             else f"{r['L_low']:.1%}-{r['L_high']:.1%}")
        liq = "/".join("yes" if b["liquidated"] else "no" for b in r["branches"])
        note = "" if r["oracle_known"] else "  (oracle unknown: tracks / does not track)"
        print(f"{r['scenario']:13s} {r['shock']:7.2%}  {r['position']:26s} {L:>16s}  {liq}{note}")
    if a.json:
        with open(a.json, "w") as f:
            json.dump({"lif_at_0915": lif(0.915), "presets": [asdict(s) for s in PRESETS], "results": rows}, f, indent=1)
        print(f"\nsaved -> {a.json}")


if __name__ == "__main__":
    main()
