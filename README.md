# Belem DeFi Risk — stay or exit

EPFL Hackathon 2026, Belem Capital track. Given one DeFi position, find what it depends on, estimate the loss if a dependency fails, and recommend how much to exit now.

Current test position: **PT-sUSDe-26NOV2026** on Ethereum (Pendle market `0x47ad2cd1dd15739a7a035b9d3b7828d916fef77e`), assumed size $10M.

## Files

| File | What it does | Output |
|---|---|---|
| `fetch_data.py` | Pulls live data: Pendle markets, history, real sell quotes (step3), Morpho lending markets that take the PT as collateral (step4). Standard library only. | `data/*.json`, `data/exit_curve_*.csv` |
| `decision_core.py` | Decision maths: picks the exit fraction x that minimises `x·slippage(x) + (1−x)·p·L`, never beyond the largest size that got a real quote. | printed |
| `export_dashboard.py` | Packs everything the dashboard needs into one JSON, including one loss L per preset scenario from `loss_model.py`. | `data/dashboard.json` |
| `loss_model.py` | L = shock (cited preset) × transmission (Morpho liquidation rules, position debt / LLTV). Unknown oracle behaviour → both branches, a range. | printed / `--json` |
| `llama_graph.py` | DeFiLlama free endpoints: protocol-level dependency edges, price and stablecoin replay data. Needs `pip install defillama-sdk`. | `data/edges_*.csv`, `data/replay_*.json` |
| `sample_data/dashboard.sample.json` | A ready `dashboard.json` built from the 10 Oct 2026 run, so the dashboard can be built without running anything. | — |
| `sample_data/dashboard.levered.sample.json` | Same run with `--debt 8950000` (LTV 89.5%, oracle unknown): shows liquidations, bad debt and L ranges in `scenarios[]`. | — |

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
# levered example: $8.8M USDC borrowed against the $10M PT, oracle behaviour unknown
#   ... --debt 8800000 [--lltv 0.915] [--must-sell] [--oracle-tracks-underlying true|false|unknown] [--oracle-tracks-market true|false|unknown]
```

Position inputs of `export_dashboard.py` (they only affect `position_inputs` and `scenarios`):
`--debt` USD borrowed against the PT (default 0); `--lltv` (default: the LLTV of the Morpho market in `data/`; the script stops if there are several); `--can-hold` (default) / `--must-sell` (forced to sell at the worst point); `--oracle-tracks-underlying`, `--oracle-tracks-market` = `true|false|unknown` (default `unknown`).

Every fetch step ends with a `GATE PASS` / `GATE FAIL` line.

## Dashboard data contract (`dashboard.json`)

All fractions are 0–1 (multiply by 100 for %). All money in USD.

| Field | Meaning |
|---|---|
| `position` | `chain_id`, `name`, `market`, `pt`, `underlying` (sUSDe), `expiry`, `pool_liquidity_usd`, `implied_apy`, `notional_usd` (position size used for quotes) |
| `exit_curve[]` | Real Pendle quotes: `fraction` of the position sold, `usd`, `loss` = cost of selling it as a fraction of value |
| `max_exit_fraction` | Largest fraction that got a quote. Above it Pendle refused (`MarketProportionTooHigh`): that part cannot be sold through the AMM now |
| `lending[]` | Morpho markets holding the PT as collateral: `lltv`, `collateral_usd`, `borrow_usd`, `liquidity_usd` (what lenders can withdraw now), `aggregate_ltv`, `oracle_address`, `oracle_type` |
| `assumptions.L` | Loss used by the top-level `decision_grid`. **Placeholder (0.5)**, kept for compatibility; per-scenario L is in `scenarios[]` |
| `thresholds` | `start_selling_p`: smallest grid p where the tool starts selling; `sell_to_cap_p`: smallest grid p where it sells up to `max_exit_fraction` (`null` = never on the grid) |
| `decision_grid[]` | Pre-computed result for p = 0, 0.005, …, 1 with the placeholder L, unlevered terms: `verdict`, `exit_fraction`, `stuck_fraction`, `expected_cost`, `stay_cost` |
| `position_inputs` | The position the loss model was run for: `collateral_usd` (= `notional_usd`), `debt_usd`, `equity_usd` (= collateral − debt), `lltv`, `lltv_source` (`--lltv`, the Morpho file in `data/`, or the unused default when there is no debt), `can_hold`, `oracle_tracks_underlying`, `oracle_tracks_market` (`true` / `false` / `null` = unknown), `exit_cost_scale` (= collateral / equity, 1 when unlevered), `note` |
| `scenarios[]` | One entry per preset in `loss_model.PRESETS` (fields below) |

`scenarios[]` fields:

| Field | Meaning |
|---|---|
| `key`, `layer` | Preset name; 2 = underlying / issuer, 3 = oracle / market price of the PT |
| `shock`, `permanent`, `hours` | Fall of the PT value at the worst point; part of it still there at the end; how long the worst point lasted (`null` = unknown) |
| `source`, `analogy` | Where the shock comes from; `true` = observed on another asset, used by analogy |
| `L_low`, `L_high` | Loss as a fraction of **equity** (= of the position when unlevered). Differ only when the oracle behaviour that matters is unknown and the branches disagree |
| `oracle_known` | `false` = both oracle branches were computed |
| `L_used`, `L_basis` | L that drives this scenario's `decision_grid`: always `L_high`. `L_basis` = `"exact"` or `"L_high (oracle behaviour unknown: worst branch)"` |
| `branches[]` | One per oracle branch: `oracle_falls`, `liquidated`, `loss_of_equity`, `loss_usd`, `bad_debt_usd` (lenders' loss) |
| `liquidated[]` | `branches[].liquidated` in the same order (one entry when unlevered or oracle known; `[oracle falls, does not fall]` otherwise) |
| `liquidation_drop_threshold` | Oracle price drop that makes the position liquidatable, `1 − debt / (collateral · lltv)`; `null` when unlevered |
| `bad_debt_usd` | Largest `bad_debt_usd` over the branches |
| `thresholds`, `decision_grid[]` | As the top-level ones, but with `L_used` and **per unit of equity**: exit cost = curve `loss × exit_cost_scale`, stay cost = `p × L_used`. The unsold part is assumed to keep the full position's L (deleveraging by the sale is not modelled) |

### Two ways to drive the p slider

1. **Lookup** (simplest): round the slider to 0.5% and read the row from `decision_grid`.
2. **Recompute in the browser** (continuous slider, and needed once L becomes adjustable). Port this:

```js
// curve = exit_curve as [[fraction, loss], ...] sorted; L, p in 0..1
// For a scenario: L = scenario.L_used and curve = exit_curve.map(c => [c.fraction, c.loss * position_inputs.exit_cost_scale])
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
- **Scenario picker** over `scenarios[]`: show `shock`, `source` (flag `analogy`), L (a range `L_low`–`L_high` when the oracle is unknown), liquidated per branch, `bad_debt_usd`; drive the p slider from that scenario's `decision_grid` / `thresholds`.
- A visible label that the top-level **L is a placeholder**, and that a scenario's grid uses `L_high` when `L_basis` is not `"exact"`.

## Known gaps

- Top-level L = 0.5 is a placeholder kept for compatibility; per-scenario L comes from `loss_model.py` presets (shocks are cited anchors, several by analogy).
- For levered positions the scenario grid treats the unsold part as keeping the full position's L; deleveraging by a partial sale is not modelled.
- $10M position size is an assumption; the real size should come from Belem.
- Yield given up by selling the PT early (`carry_lost`) is set to 0.
- Capacity is a snapshot and counts only the Pendle swap route (no limit orders, OTC, or holding to maturity).
- No on-chain crawler yet (needs an RPC endpoint); the Morpho oracle type is still `Unknown`.
- The dependency graph is not merged into one file yet.
