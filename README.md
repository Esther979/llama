# Belem DeFi Risk — stay or exit

EPFL Hackathon 2026, Belem Capital track. Given one DeFi position, find what it depends on, estimate the loss if a dependency fails, and recommend how much to exit now.

Current test position: **PT-sUSDe-26NOV2026** on Ethereum (Pendle market `0x47ad2cd1dd15739a7a035b9d3b7828d916fef77e`), assumed size $10M.

## Files

| File | What it does | Output |
|---|---|---|
| `fetch_data.py` | Pulls live data: Pendle markets, history, real sell quotes (step3), Morpho lending markets that take the PT as collateral (step4). Standard library only. | `data/*.json`, `data/exit_curve_*.csv` |
| `decision_core.py` | Decision maths: picks the exit fraction x that minimises `x·slippage(x) + (1−x)·p·L`, never beyond the largest size that got a real quote. | printed |
| `export_dashboard.py` | Packs everything the dashboard needs into one JSON. | `data/dashboard.json` |
| `llama_graph.py` | DeFiLlama free endpoints: protocol-level dependency edges, price and stablecoin replay data. Needs `pip install defillama-sdk`. | `data/edges_*.csv`, `data/replay_*.json` |
| `sample_data/dashboard.sample.json` | A ready `dashboard.json` built from the 10 Oct 2026 run, so the dashboard can be built without running anything. | — |

## Run order

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install defillama-sdk            # only llama_graph.py needs it

M=0x47ad2cd1dd15739a7a035b9d3b7828d916fef77e
python3 fetch_data.py step0          # all four endpoints must answer 200
python3 fetch_data.py step1 --filter sUSDe
python3 fetch_data.py step2 --chain 1 --market $M
python3 fetch_data.py step3 --chain 1 --market $M --notional 10000000 --tag 10m
python3 fetch_data.py step3 --chain 1 --market $M --notional 10000000 --fractions 0.25,0.3,0.35,0.4,0.45 --tag cap
python3 fetch_data.py step4 --chain 1 --market $M
python3 export_dashboard.py --market $M --curves data/exit_curve_0x47ad2cd1_10m.csv data/exit_curve_0x47ad2cd1_cap.csv --L 0.5
```

Every fetch step ends with a `GATE PASS` / `GATE FAIL` line.

## Dashboard data contract (`dashboard.json`)

All fractions are 0–1 (multiply by 100 for %). All money in USD.

| Field | Meaning |
|---|---|
| `position` | `chain_id`, `name`, `market`, `pt`, `underlying` (sUSDe), `expiry`, `pool_liquidity_usd`, `implied_apy`, `notional_usd` (position size used for quotes) |
| `exit_curve[]` | Real Pendle quotes: `fraction` of the position sold, `usd`, `loss` = cost of selling it as a fraction of value |
| `max_exit_fraction` | Largest fraction that got a quote. Above it Pendle refused (`MarketProportionTooHigh`): that part cannot be sold through the AMM now |
| `lending[]` | Morpho markets holding the PT as collateral: `lltv`, `collateral_usd`, `borrow_usd`, `liquidity_usd` (what lenders can withdraw now), `aggregate_ltv`, `oracle_address`, `oracle_type` |
| `assumptions.L` | Loss if the event happens. **Placeholder (0.5)** until the per-layer loss model exists |
| `thresholds` | `start_selling_p`: smallest grid p where the tool starts selling; `sell_to_cap_p`: smallest grid p where it sells up to `max_exit_fraction` |
| `decision_grid[]` | Pre-computed result for p = 0, 0.005, …, 1: `verdict`, `exit_fraction`, `stuck_fraction`, `expected_cost`, `stay_cost` |

### Two ways to drive the p slider

1. **Lookup** (simplest): round the slider to 0.5% and read the row from `decision_grid`.
2. **Recompute in the browser** (continuous slider, and needed once L becomes adjustable). Port this:

```js
// curve = exit_curve as [[fraction, loss], ...] sorted; L, p in 0..1
function slippageAt(x, curve) {               // linear interpolation, flat before the first point
  if (x <= curve[0][0]) return curve[0][1];
  for (let i = 1; i < curve.length; i++) {
    const [x0, s0] = curve[i - 1], [x1, s1] = curve[i];
    if (x <= x1) return s0 + (s1 - s0) * (x - x0) / (x1 - x0);
  }
  return curve[curve.length - 1][1];
}
function decide(p, L, curve, steps = 100) {
  const el = p * L, maxX = Math.max(...curve.map(c => c[0]));
  let bestX = 0, bestCost = el;
  for (let i = 0; i <= steps; i++) {
    const x = i / steps;
    if (x > maxX + 1e-12) break;              // never sell beyond the largest real quote
    const cost = (x > 0 ? x * slippageAt(x, curve) : 0) + (1 - x) * el;
    if (cost < bestCost - 1e-12) { bestX = x; bestCost = cost; }
  }
  const capped = maxX < 1 - 1e-12;
  return { exitFraction: bestX, expectedCost: bestCost, stayCost: el,
           stuckFraction: capped && bestX >= maxX - 1e-12 ? 1 - bestX : 0 };
}
```

## Suggested dashboard panels

- **p slider** (set by the manager) with three zones: stay / partial exit / sell to capacity, from `thresholds`.
- **Exit panel**: sellable now (`max_exit_fraction × notional_usd`), stuck part, cost of the recommended sale.
- **Exit curve chart**: `exit_curve` (loss vs size) with the capacity cliff marked at `max_exit_fraction`.
- **Lending panel**: distance to liquidation = `1 − aggregate_ltv / lltv`, withdrawable liquidity, oracle (flag `Unknown`).
- A visible label that **L is a placeholder**.

## Known gaps

- L = 0.5 is a placeholder; the per-layer loss model is not written yet.
- $10M position size is an assumption; the real size should come from Belem.
- Yield given up by selling the PT early (`carry_lost`) is set to 0.
- Capacity is a snapshot and counts only the Pendle swap route (no limit orders, OTC, or holding to maturity).
- No on-chain crawler yet (needs an RPC endpoint); the Morpho oracle type is still `Unknown`.
- The dependency graph is not merged into one file yet.
