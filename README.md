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
| `reasoning.py` | Evidence grades (A–D), per-scenario reasoning chain, decision texts and weakest link; used by `export_dashboard.py`. | — |
| `backtest_reusd.py` | Back-tests the Morpho liquidation rules in `loss_model.py` on the 25 Aug 2026 PT-reUSD liquidations (HackMD figures + our Pendle data). Its result is what earns grade B. | printed, and `validation` in `dashboard.json` |
| `calibrate_depeg.py` | Historical outcome frequencies of stablecoin depegs (DeFiLlama daily prices of ~300 USD stablecoins): default probabilities of the depeg incident. 3 gates on known events. | `data/depeg_calibration.json` |
| `incidents.py` | Incidents with three outcomes (resolved / partial / severe), expected and tail loss, exact break-even probabilities, exit now vs later, lender role; used by `export_dashboard.py`. | — |
| `etherscan.py` | Etherscan V2 client (standard library): verified source, ABI, contract name, proxy -> implementation. Key from `ETHERSCAN_API_KEY` or `.env` (git-ignored), never saved. | `data/etherscan/<chain>_<address>.json` |
| `crawl.py` | Generic dependency crawler: from any contracts (or a Morpho market id), calls every view function that returns addresses (ABI from Etherscan), enumerates `f(uint256)` + `fLength()`, turns Morpho market ids into market nodes weighted by allocation. Edge kinds: data (followed), role, operator, infra. | `data/edges_<tag>.csv` (`src, dst, type, kind, weight_usd, evidence`), `data/nodes_<tag>.json` |
| `oracle_types.py` | Oracle type table: decides from verified source and on-chain parameters whether a Morpho oracle follows the collateral's market price and / or its underlying (linear discount, MorphoChainlinkOracleV2, meta-oracle with timelock, Chainlink market / reported-rate feeds, constant feeds; unknown -> both branches, D). | printed / used by `vault_pipeline.py` |
| `vault_pipeline.py` | Vault risk for a list in the RockawayX dashboard format: routes each row (ethereum + morpho = full, other ethereum protocols = dependency graph only, other chains / Solana = not covered, no numbers), and for each Morpho VaultV2: markets and allocations, every borrower, oracle types, incidents per collateral and underlying, vault loss per outcome, exit tranches, break-even and the manager sentence. | `data/vaults/<address>.json`, `data/vaults/edges_<address>.csv`, `data/vaults_report.json` |
| `frontend_contract.py` | Builds the front-end fields of `dashboard.json`: dependency graph by layer, failure types, position presets, detector feed. | used by `export_dashboard.py` |
| `web/risk_model.js` | JS port of the loss model, oracle rule, `decide()` and break-even for the front end. | — |
| `check_js_port.py` | Checks `web/risk_model.js` against Python on 500 random cases (needs node). | printed |
| `onchain_positions.py` | Every borrower of our Morpho market read on chain over JSON-RPC (`RPC_URL`, standard library only): positions, LTVs, liquidation curve vs Pendle capacity; `--wallet 0x…` also reads given wallets at the same block (PT held + Morpho position). 7 gates (+1 per wallet that is also a borrower). | `data/morpho_positions_<id[:10]>.json` |
| `llama_graph.py` | DeFiLlama free endpoints: protocol-level dependency edges, price and stablecoin replay data. Needs `pip install defillama-sdk`. | `data/edges_*.csv`, `data/replay_*.json` |
| `sample_data/dashboard.sample.json` | A ready `dashboard.json` built from the 10 Oct 2026 run, so the dashboard can be built without running anything. | — |
| `sample_data/rockawayx_vaults.csv` | The 33 RockawayX dashboard vaults (input of `vault_pipeline.py`). | — |
| `sample_data/vaults_report.sample.json`, `sample_data/vault_detail.sample.json` | `vaults_report.json` of the run on the 33 vaults, and the detail file of RockawayX Confidential RWA USDC. | — |
| `sample_data/dashboard.levered.sample.json` | Same run with `--debt 8950000` (LTV 89.5%, oracle unknown): shows liquidations, bad debt, L ranges and the oracle as weakest link in `scenarios[]`. | — |
| `sample_data/dashboard.borrower.sample.json` | Same run with `--borrower 0x5c43…` (a real borrower at LTV 90.6%, 0.99% from liquidation): `position_inputs.borrower` filled, LTV graded A. | — |

All three samples are built with `--positions data/morpho_positions_0x5613b170.json` (block 26,161,967), so they include `borrowers`.

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
python3 fetch_data.py step3 --chain 1 --market $M --notional 1000000 --tag 1m     # small sales ($10k..$1M), for exit_curve_usd
python3 fetch_data.py step4 --chain 1 --market $M
python3 backtest_reusd.py           # 9 GATE lines; export_dashboard.py runs it too
python3 calibrate_depeg.py          # 3 GATE lines (USDC 2023 resolved, UST and deUSD severe)
RPC_URL=https://ethereum-rpc.publicnode.com python3 onchain_positions.py   # 7 GATE lines  [--wallet 0xA 0xB ...]
python3 vault_pipeline.py sample_data/rockawayx_vaults.csv   # all 33 RockawayX vaults (or --only 0xVAULT)
python3 export_dashboard.py --market $M --curves data/exit_curve_0x47ad2cd1_10m.csv data/exit_curve_0x47ad2cd1_cap.csv --L 0.5 \
    --extra-curves data/exit_curve_0x47ad2cd1_1m.csv \
    --positions data/morpho_positions_0x5613b170.json [--borrower 0x5c430ff6f374da12218b380d2040299ae5b6d40e]
# levered example: $8.8M USDC borrowed against the $10M PT, oracle behaviour unknown
#   ... --debt 8800000 [--lltv 0.915] [--must-sell] [--oracle-tracks-underlying true|false|unknown] [--oracle-tracks-market true|false|unknown]
```

`--extra-curves`: quotes run with another `--notional` (the `1m` file), merged with `--curves` by USD sale size into `exit_curve_usd`, so any position size has an exit curve (main curves win on duplicate sizes). The export checks that `at_size` at the export size, on the main quotes only, gives back `exit_curve` and `borrowers.exit_later` (`GATE ... position size`).

Position inputs of `export_dashboard.py` (they only affect `position_inputs` and `scenarios`):
`--debt` USD borrowed against the PT (default 0); `--lltv` (default: the LLTV of the Morpho market in `data/`; the script stops if there are several); `--can-hold` (default) / `--must-sell` (forced to sell at the worst point); `--oracle-tracks-underlying`, `--oracle-tracks-market` = `true|false|unknown` (default `unknown`); `--positions` (output of `onchain_positions.py`; adds `borrowers`; refused if its gates did not all pass); `--calibration` (default `data/depeg_calibration.json`); `--lender-supply` (USDC supplied, for the `lender` block, default 1,000,000); `--borrower <address>` (needs `--positions`, replaces `--debt`): the borrower's on-chain LTV and the on-chain LLTV are used (grade A). If the borrower's collateral is within 1% of the quoted notional, its real debt is used (A); otherwise debt = its LTV × our assumed size (D, and the script prints the `fetch_data.py step3 --notional` command for its real size).

`onchain_positions.py` finds borrowers from `SupplyCollateral` / `Borrow` logs. When the RPC refuses old logs (the free publicnode endpoint serves only recent blocks), it takes the addresses from Morpho GraphQL `marketPositions` plus the recent logs it can read. Every amount is then read on chain at one pinned block. The gate "sum of `borrowShares` = market `totalBorrowShares`" proves no borrower is missing. Selectors and topics are keccak256 values computed with pycryptodome and hard-coded (recomputed at start when pycryptodome is installed); they are checked against real logs and API values on every run.

Every fetch step ends with a `GATE PASS` / `GATE FAIL` line.

## Dashboard data contract (`dashboard.json`)

All fractions are 0–1 (multiply by 100 for %). All money in USD.

| Field | Meaning |
|---|---|
| `position` | `chain_id`, `name`, `market`, `pt`, `underlying` (sUSDe), `expiry`, `pool_liquidity_usd`, `implied_apy`, `notional_usd` (position size used for quotes), `pt_price_usd` (USD per PT used to size the quotes), `evidence` |
| `exit_curve[]` | Real Pendle quotes: `fraction` of the position sold, `usd`, `loss` = cost of selling it as a fraction of value (slippage and fees, no gas), `gas_usd` (gas of that sale: Pendle's `gasUsed` × gas price × ETH price at the `--positions` block; `null` without `--positions`) |
| `max_exit_fraction` | Largest fraction that got a quote. Above it Pendle refused (`MarketProportionTooHigh`): that part cannot be sold through the AMM now |
| `exit_curve_usd[]` | Every quote by USD sale size (all `--curves` and `--extra-curves` merged, $10k..$4.5M): `usd`, `loss` (as in `exit_curve`), `gas_usd`. The cost of a sale depends on the amount sold, not on the position, so this gives the exit curve of any position size (`frontend_contract.size_curve` / `RiskModel.sizeCurve`) |
| `size_input` | The PT view's position size (manager's input): `default_usd` (= `notional_usd`, our assumption, D), `pt_price_usd` (Pendle price at quote time: PT units = size / this), `oracle_price_usd` (lending oracle `price()` at the `--positions` block: Morpho values the PT at this, liquidation check only), `capacity_usd` (largest accepted quote: above it the rest is stuck), `smallest_quote_usd`, `note`, `evidence` |
| `lending[]` | Morpho markets holding the PT as collateral: `lltv`, `collateral_usd`, `borrow_usd`, `liquidity_usd` (what lenders can withdraw now), `aggregate_ltv`, `oracle_address`, `oracle_type`, `aggregate_liquidation_drop_threshold` (= `1 − aggregate_ltv / lltv`: oracle fall at which the market as a whole becomes liquidatable), `evidence` |
| `assumptions.L` | Loss used by the top-level `decision_grid`. **Placeholder (0.5)**, kept for compatibility; per-scenario L is in `scenarios[]` |
| `thresholds` | `start_selling_p`: smallest grid p where the tool starts selling; `sell_to_cap_p`: smallest grid p where it sells up to `max_exit_fraction` (`null` = never on the grid) |
| `decision_grid[]` | Pre-computed result for p = 0, 0.005, …, 1 with the placeholder L, unlevered terms: `verdict`, `exit_fraction`, `stuck_fraction`, `expected_cost`, `stay_cost` |
| `position_inputs` | The position the loss model was run for: `collateral_usd` (= `notional_usd`), `debt_usd`, `equity_usd` (= collateral − debt), `lltv`, `lltv_source` (`--lltv`, the Morpho file in `data/`, or the unused default when there is no debt), `can_hold`, `oracle_tracks_underlying`, `oracle_tracks_market` (`true` / `false` / `null` = unknown), `exit_cost_scale` (= collateral / equity, 1 when unlevered), `ltv` (= debt / collateral), `borrower` (`null`, or with `--borrower`: `address`, `collateral_pt`, `collateral_usdc`, `borrow_usdc`, `ltv`, `distance_to_liquidation`, `block`, `same_size_as_quotes`), `note`, `evidence`. `lltv_source` can also be `"on chain, block N"` |
| `scenarios[]` | One entry per preset in `loss_model.PRESETS` (fields below) |
| `borrowers` | Only with `--positions`. `liquidation_curve` and `exit_later` cover oracle drops 0.5%..10% (step 0.5%) and 11%..40% (step 1%). On-chain state of the Morpho market at `block` (`block_timestamp`, `market_id`): `oracle_price` (USDC per PT, from the oracle's `price()`), `lltv`, `lif`, `total_borrow_usdc`, `discovery` (how addresses were found: `mode`, `sources[]`, `logs_cover_from_block`, `candidates`), `gates_passed` / `gates_total` (from `onchain_positions.py`), `list[]` (one per position with collateral or debt, highest LTV first: `address`, `collateral_pt`, `collateral_usdc` (at the oracle price), `borrow_usdc`, `borrow_shares`, `ltv` (= borrow / (collateral × oracle price)), `distance_to_liquidation` (= 1 − ltv / lltv: oracle fall that makes it liquidatable), `healthy` (Morpho's own check, integer maths)), `distribution` (`n_borrowers`, `ltv_min`, `ltv_median`, `ltv_max`, `ltv_debt_weighted`, `distance_buckets[]`: `distance_from`, `distance_to`, `n`, `borrow_usdc`), `capacity_pt` (largest Pendle sale accepted, in PT), `liquidation_curve[]` (for oracle drops 0.005 … 0.10: `oracle_drop`, `n_liquidatable`, `debt_liquidatable_usdc`, `pt_seized` (= borrow × LIF / dropped price, capped at the collateral; full liquidation assumed), `bad_debt_usdc`, `seized_exceeds_capacity`), `first_drop_seized_exceeds_capacity` (`null` = not up to 10%), `selected` (the `--borrower`, or `null`), `evidence` (chain values: grade A with `block`) |
| `exit_costs` | Exit cost of the position including gas, per unit of position value: `first_size` and `cost_first` (smallest quoted sale), `cap` and `cost_avg_cap` (selling everything sellable), `cost_marginal_cap` (cost of the last unit sold at the cap), `gas_usd_first`, `gas_usd_cap`, `gas_included`, `evidence` |
| `incidents[]` | One per incident type (what the detection module reports). Given the incident, three outcomes. Fields below |
| `lender` | Only with `--positions`. The same market seen by a USDC lender. Fields below |
| `weakest_link` | Across scenarios: the lowest-graded input that changes the verdict in the most scenarios. `id`, `step`, `input`, `grade`, `source`, `scenarios` (keys where it is that scenario's weakest link), `total_effect`, `why`. `{"id": null, "note"}` if no tested input changes any verdict |
| `validation` | Back-test from `backtest_reusd.py`: `name`, `event`, `source`, `figures` (the HackMD inputs), `oracle_drop`, `lif`, `checks[]` (`name`, `expected`, `got`, `tolerance`, `pass`), `passed`, `total`, `all_pass` |
| `evidence` | Grades for top-level fields: `grades` (legend), `exit_curve`, `max_exit_fraction` (source names the refused sizes), `lending`, `assumptions` / `thresholds` / `decision_grid` (D: placeholder L), `mechanism` (Morpho rules: B only if `validation.all_pass`) |

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
| `evidence` | Grade per field: `shock`, `permanent`, `hours`, `L_low`, `L_high`, `L_used`, `branches`, `liquidated`, `liquidation_drop_threshold`, `bad_debt_usd`, `thresholds`, `decision_grid` |
| `reasoning[]` | Ordered steps `{step, id, claim, value, unit, evidence, source, basis?}` (below) |
| `decision_text` | `stay`, `partial`, `sell_to_cap`: each `{p_from, p_to, text}` or `null` when the zone does not exist. The zone holds for `p_from ≤ p < p_to` (`p_to` `null` = up to 1). Replace `{p}` in `text` with the slider value. Every other number in a text is a formatted `reasoning[].value` (checked at export; the export stops otherwise) |
| `break_even` | Exact break-even probabilities for this scenario as a single event with loss `L` (= `L_used`), from the exit curve with gas (no p grid): `p_start` (optimizer starts selling), `p_exit_sellable` (= average cost of selling everything sellable / L: brief's "exit cost ÷ loss"), `p_sell_to_cap` (optimizer sells all it can), `exit_cost_sellable` (per unit of equity), `sellable_fraction`, `evidence`. `null` p's when L = 0. Checked against `decide()` on both sides of `p_start` and `p_sell_to_cap` at every export |
| `exit_later` | Only with `--positions`. Exit after the lending oracle has fallen by this scenario's `shock`: liquidators sell `pt_seized` into the pool first. `oracle_drop`, `pt_seized`, `seized_in_position_units`, `sellable_now`, `avg_cost_now`, `sellable_later`, `avg_cost_later` (`null` when nothing is left), `market_impact_of_liquidations` (cost of the next unit after the liquidators' sale), `note`, `condition` |
| `weakest_link` | Lowest-graded input whose stated alternative changes this scenario's thresholds on p; ties on grade → larger change. `step`, `id`, `input`, `grade`, `source`, `alternative`, `thresholds_now`, `thresholds_alt`, `candidates[]` (every input tried: `step`, `id`, `input`, `grade`, `source`, `alternative`, `L_alt`, `thresholds_alt`, `changes_verdict`, `effect` = sum of the two threshold moves, "never" counted as `1 + pstep`), `not_tested[]`. All fields but `candidates`/`not_tested` are `null` if nothing changes the verdict |

`incidents[]` fields:

| Field | Meaning |
|---|---|
| `key`, `layer`, `type`, `description` | `underlying_depeg` (layer 2: sUSDe / USDe below 0.97) or `oracle_dip` (layer 3) |
| `outcomes[]` | `resolved`, `partial`, `severe`: `outcome`, `preset` (loss_model preset, or `null`), `shock`, `L_low`, `L_high`, `L_used` (= `L_high`; `null` = no anchor), `liquidated` (per oracle branch), `probability` (default, the manager can change it), `source`, `evidence.L`. Depeg: resolved = `usde_mild`, partial = `depeg_partial` (median day-30 loss of the calibrated partial episodes, 2.3%), severe = `issuer_total`. Oracle: resolved = no loss, partial = `oracle_dip`, severe = none (probability 0) |
| `probability_evidence` | Depeg: C, from `calibrate_depeg.py` (sample, rules and the range over three samples in `source`). Oracle: D (one event only) |
| `expected_loss`, `expected_loss_usd` | Σ probability × `L_used` (fraction of equity; USD = × equity) |
| `tail_loss_95`, `tail_loss_95_usd`, `var_95` | Mean loss in the worst 5% of outcomes (CVaR 95%), and the loss at the 95% quantile |
| `break_even` | `worst_outcome` (severe, or partial when there is no severe anchor), `L_worst`, `exit_cost_sellable` (per unit of equity), `exit_cost_value` (per unit of value sold), `exit_cost_scale`, `sellable_fraction`, `p_worst_alone` (= exit cost ÷ `L_worst`: brief's formula), `p_worst_given_default_partial` (same with the partial outcome at its default probability; 0 = exiting the sellable part pays even at severe probability 0), `p_partial`, `alternatives[]` (other severe anchors: `preset`, `L`, `p_worst_alone`) |
| `decision_text` | `text`: the manager sentence ("if you think the probability of the severe outcome is above X, exit the sellable part now…"); `numbers`: the formatted values it may contain (checked at export) |
| `exit_later[]` | Only with `--positions`: per outcome with a shock, the same fields as `scenarios[].exit_later` |
| `evidence` | `probabilities`, `expected_loss`, `tail_loss_95`, `break_even` |

`lender` fields: `supply_usdc` (assumed), `total_supply_usdc`, `total_borrow_usdc`, `utilization`, `liquidity_usdc` (= supply − borrow: what can be withdrawn now), `share_of_supply`, `withdrawable_now_usdc`, `withdrawable_fraction`, `locked_fraction`, `block`, `scenarios[]` (`key`, `bad_debt_usdc_per_branch` summed over the real borrowers with loss_model, `L_low`, `L_high` = bad debt / total supply: Morpho takes bad debt from all suppliers pro rata), `incidents[]` (`key`, `outcomes[]`, `expected_loss`, `expected_loss_usdc`, `tail_loss_95`, `tail_loss_95_usdc`, `loss_on_locked_part_usdc`), `decision_text`, `evidence`.

`borrowers.exit_later[]`: the `exit_later` fields for every oracle drop of `liquidation_curve` ("exit now vs later" table), at `notional_usd`; `at_size` recomputes them for the chosen size (`frontend_contract.exit_later_at` / `RiskModel.exitLaterAt`, USD version, adds `seized_usd`).

## Position size (PT view)

The manager enters the position's size (USD value today, default 10,000,000) or a wallet address. `frontend_contract.at_size(d, size_usd, wallet=None)` / `RiskModel.atSize(d, sizeUsd, wallet)` returns the dashboard for that size; every other PT-view function then takes the result as `d`:

- `sized` presets get `collateral_usd` = size, `pt_units` = size / `pt_price_usd` (the quoted PT price, 0.99300), `collateral_oracle_usd` = units x oracle price (0.99239), `debt_usd` = `ltv` x `collateral_oracle_usd`. Real-borrower presets keep their real size.
- `exit_curve`, `max_exit_fraction`, `position.notional_usd` for that size from `exit_curve_usd`: up to $4.5M the whole position can be sold (`max_exit_fraction` = 1); above, `max_exit_fraction` = $4.5M / size and the rest is stuck.
- `borrowers.exit_later` for that size (liquidators' PT sold first, then ours on the same quotes).
- `wallet`: an address read on chain (`wallet_presets` / `RiskModel.walletPresets`). Wallets passed to `onchain_positions.py --wallet` are read at the same block as the borrowers (`borrowers.wallets`): preset `wallet` = PT held in the wallet (`balanceOf`, unlevered) and / or `wallet_morpho` = its position in this Morpho market (same `read_positions` code as the borrowers), both grade A at their real size. Other addresses are looked up in `borrowers.list` (`wallet_morpho` only). `wallet_read` = the address was read on chain; `wallet_found` = it holds PT there. Not read: PT in Pendle LP or other lending markets. A wallet with both parts gets two presets; their combined decision is not modelled (decide each part).
- Legacy fields (`scenarios`, `incidents`, `decision_grid`, `position_inputs`...) stay at the export size.

PT prices in the model: losses and sales use the market value (PT units x Pendle price); the lending oracle's value is used only for the liquidation check (`loss_model.Position.collateral_oracle_usd`: threshold, seized share, bad debt). A sale happens now, so `decide_at` sizes and costs it on today's value even when the incident lasts (`opts.sale_value_usd`); in the timeline the loss is on the value at the end of the incident (units x market price from the implied APY) and the liquidation check on units x oracle price.

## Decision method (no probability)

The organisers asked not to rely on a probability p of the incident (sudden events cannot be predicted). The decision is made **given the incident**, at a severity that is chosen or observed:

- Position (PT view): sell the share x that minimises `x x (slippage(x) + carry) + (1 - x) x L(severity)`, never beyond the largest Pendle quote (`decision_core.decide` with p = 1; `RiskModel.decideAt`). Output: STAY / REDUCE / SELL_TO_CAP / EXIT, sale cost, loss if staying, loss kept, and the **break-even severity** (`RiskModel.breakEvenSeverity`: the smallest severity at which selling starts / reaches the pool limit).
- Vault (second view): withdraw each tranche whose unit cost is below L(severity): free tranche (idle + liquidity market) at the yield given up, forced tranche (`forceDeallocate` from other markets, up to their liquidity) at the yield given up + the on-chain `forceDeallocatePenalty`; the rest is locked (`vault_pipeline.vault_decide_at`, `RiskModel.vaultDecideAt`). L(severity) comes from `severity_grid`, computed from every real borrower. Output: STAY / EXIT / EXIT_PARTIAL / REVIEW and the break-even severities.

Timeline (incident duration, organisers' request): `frontend_contract.decide_at_duration` / `timeline_pt` and `RiskModel.decideAtDuration` / `timeline` (PT view), `vault_pipeline.vault_decide_at(..., hours, recovers)` / `vault_timeline` and `RiskModel.vaultDecideAt` / `vaultTimeline` (vault view). The duration decides whether a meta-oracle switches (16 h), whether the shock recovers after it, the PT's value (units x PT price, pulled to 1 at expiry), the debt (borrow APR) and the yield given up. `dashboard.json` `time_model`: `generated_at`, `expiry`, `days_to_expiry`, `implied_apy`, `oracle_discount_per_year`, `borrow_apr` (AdaptiveCurveIrm.borrowRateView), `evidence`. Vault incidents: `duration_grids[]` (`from_hours`, `recovers`, `grid` like `severity_grid`). `timeline_summary` / `RiskModel.timelineSummary` and `vault_timeline_summary` / `RiskModel.vaultTimelineSummary` say whether the duration changes the verdict (`duration_matters`), list the change points with their reason (`changes[]`: `from_hours`, `to_hours`, `verdict_before`, `verdict_after`, `reason`: meta-oracle switch, PT expiry, liquidation, debt growing after expiry, yield given up) or say why the timeline is flat (`why_flat`, e.g. no debt: no oracle timer, no interest).

Sensitivity (what would change the answer): `frontend_contract.sensitivity` / `RiskModel.sensitivity` (PT view: incident duration vs the oracle's challenge timelock, oracle behaviour, hold vs forced sale, yield given up; other position presets as comparisons) and `vault_pipeline.vault_sensitivity` / `RiskModel.vaultSensitivity` (oracle branch, alternative yield 0% or equal to the vault's, horizon 7 / 90 days; a 10x deposit as comparison). Each replaces one assumption by a stated alternative and reruns the decision; `weakest` = the lowest-graded assumption that flips the verdict (ties: larger change), `null` = robust. Vault detail files store it per incident as `incidents[].sensitivity`.

Probability-based fields (`decision_grid`, `thresholds`, `break_even`, `incidents[].probabilities`, `expected_loss`, `tail_loss_95`, `weakest_link`) are kept for compatibility but are **legacy**: the front end does not use them.

## Frontend integration (Risk Desk v2)

Step-by-step instructions for the front end (to hand to Claude with the page): `FRONTEND_GUIDE.md`. The Risk Desk's 9 nodes, layer rows, edges and fault-injection rules are in `ui` (`nodes`, `layers`, `edges`, `injections`); `RiskModel.inject(d, preset, node, fail, sev)` in `web/risk_model.js` computes one outcome. `export_dashboard.py --js-out file.js` writes the same data as `window.DASHBOARD = {...}` for pages opened from disk (`sample_data/dashboard.sample.js`).

The front end should load `dashboard.json` (or `sample_data/dashboard.sample.json`) instead of a hard-coded snapshot, and compute losses with `web/risk_model.js`: a line-by-line port of the Python loss model, oracle rule, `decide()` and break-even. `python3 check_js_port.py` checks it against Python (500 random cases, all equal); rerun it after any change to either side.

```html
<script src="risk_model.js"></script>   <!-- global RiskModel: positionLoss, oracleFalls, decide, breakEven, slippageAt, lif -->
```

New top-level fields (`position_presets` changed meaning with the position size: see "Position size"):

| Field | Meaning |
|---|---|
| `oracle` | Type tree of the Morpho market's oracle (`underlying_assets` / `underlying_assets_after_switch`: which assets its base feeds price, e.g. `["usde"]`; `oracle_falls(..., token)` uses them so that a sUSDe NAV loss is not seen by a USDe / USD feed) at the `--positions` block (`oracle_types.classify`): `kind`, `tracks_market`, `tracks_underlying` (true / false / null), for a meta-oracle also `primary`, `backup`, `current`, `deviation_threshold`, `challenge_timelock_s`, `healing_timelock_s`, `deviation_now`, `challenged`, `tracks_*_after_switch`; `rule`, `evidence`. `null` without `--positions` |
| `ui` (edges to the position) | `ui.edges` also has `pt -> position` "holding" (D) and `lending -> position` "liquidation" (B, `applies_to` = levered presets) |
| `ui` | The Risk Desk's 9 nodes (`eth`, `ethena`, `usde`, `susde`, `feeds`, `oracle`, `market`, `pt`, `lending`: `label`, `kind`, `layer`, `address`, `contract_name`, `members` = ids in `dependency_graph.nodes`, `evidence`, `note`, `failures`), `layers`, `edges` (`from`, `to`, `type`, `grade`, `evidence`), `injections` (`"node:fail"` -> `type` = loss_model / exit_later / exit_only / not_modelled, `scenario_layer`, `permanent`, `hours`, `oracle` = "rule" (oracleFalls) / true / false, `note`) |
| `dependency_graph` | Crawl of the Morpho market (`crawl.py --tag pt_susde_market`) in the brief's five layers: `block`, `layers[]` (`n`, `name`, `nodes` = ids), `nodes{id: {label, contract_name, address, kind, layer, verified, evidence}}`, `edges[]` (`from`, `to`, `type` = function that returned it, `kind` = data / role / operator / infra, `evidence`), `counts`. Adds the chain, the Pendle market (Pendle API) and the off-chain issuer (grade D, not verified) |
| `failure_types` | `types{key}` with the front end's FAIL keys (`shortfall`, `depeg` (USDe against USD, PT market price), `navLoss` (sUSDe NAV in USDe falls: permanent PT loss, no feed sees it), `discount` (sUSDe below its NAV: recovered at expiry), `oracleLow`, `stale`, `cascade`, `drain`, `halt`): `label`, `layer`, `unit`, `min`, `max`, `default_severity`, `anchors[]` (historical values with source), `model` (`type`: `loss_model`, `exit_later`, `exit_only` or `not_modelled`; `scenario_layer`, `permanent`, `hours`, `oracle` rule), `probabilities` (`outcomes` {resolved, partial, severe}, `p_severe`, `partial_to_severe_prob`, `partial_severity_share`, `evidence`). `by_node{node id: [failure keys]}` |
| `position_presets` | `spot`, `lev_market_avg`, `lev_largest_borrower`, `lev_closest_to_liquidation`: `label`, `collateral_usd` (market value today = PT units x `size_input.pt_price_usd`: what the PT sells for; losses are on it), `collateral_oracle_usd` (PT units x the lending oracle's price: liquidation check only), `pt_units`, `debt_usd`, `lltv`, `can_hold`, `ltv` (debt / `collateral_oracle_usd`, as Morpho computes it), `sized` (true: follows the size input; `spot` and `lev_market_avg` (on-chain total borrow / total collateral, grade A)), `address` (real borrowers), `evidence`, `oracle_rule`. The two real-borrower presets are those borrowers' **real positions** read on chain (grade A; $3.93M and $3.25M), not their LTV at our size |
| `size_usd`, `wallet_read`, `wallet_found` | Only in the result of `at_size` / `RiskModel.atSize`: the size used; whether the wallet address was read on chain, and whether it holds PT there |
| `borrowers.wallets[]` | Only with `onchain_positions.py --wallet`: `address`, `pt_in_wallet` (PT `balanceOf`), `collateral_pt`, `collateral_usdc`, `borrow_usdc`, `borrow_shares`, `ltv`, `healthy` (this Morpho market), `is_contract`, `in_borrower_list`, `oracle_price`, `block` (= `borrowers.block`) |
| `detected` | Detector feed: `[]` until the detector exists. Entry schema in `detector.schema`: `node`, `fail`, `sev`, `signal`, `block`, `evidence` (same shape as the front end's `DETECTED`) |

UI element -> data:

| Risk Desk element | Read / compute |
|---|---|
| Position select | `position_presets` of `RiskModel.atSize(d, size, wallet)` (replaces the hard-coded `POS`; real borrowers at their real size) |
| Snapshot stamp | `generated_at`; on-chain block in `borrowers.block` |
| Step 1 "Which incident / test a failure at" | `dependency_graph.layers[].nodes` grouped by layer; allowed failures per node from `failure_types.by_node` |
| Step 2 failure + severity slider | `failure_types.types[key]`: `label`, `min`, `max`, `unit`, start at `default_severity`, show `anchors` as tick marks |
| Step 3 probability slider | start at `types[key].probabilities.p_severe` (C, with `evidence.source`); `null` = no historical default, keep the sample value and say so |
| Loss of an outcome | `scenario = {layer: model.scenario_layer, shock: sev/100, permanent: model.permanent, hours: model.hours}`; `position = preset + {oracle_tracks_underlying / oracle_tracks_market: RiskModel.oracleFalls(oracle, layer, shock, hours)}` (for `oracleLow` set the flag to `true`); `RiskModel.positionLoss(scenario, position)` -> show `L_low`-`L_high`, decide with `L_high` |
| Partial case | same with `shock x partial_severity_share`, probability `p_severe x partial_to_severe_prob` (replaces the `pk` / `ps` assumptions) |
| Verdict and bars | `el = sum p x L`; `RiskModel.decide(1, el, curve, carry)` as today; for levered presets multiply curve losses by collateral / equity; exact thresholds `RiskModel.breakEven(curve, L_high, scale, carry)` |
| Chain panel | `dependency_graph`: grade A nodes solid, D dashed; edge evidence in the drawer; role / operator / infra edges as counts ("USDe / USD reported by 16 transmitters") |
| Oracle facts | `oracle`: e.g. "PT priced by a linear discount (no market input); switches to a USDe-tracking backup only after a deviation above 0.75% lasting 16 h" |
| Exit panel "If this plays out" | `borrowers.exit_later[]` at the oracle drop nearest the severity (`cascade`, and `depeg` / `oracleLow` when the oracle falls): `sellable_later`, `avg_cost_later` (replaces the 50% pool-drain assumption, which stays only for `drain`) |
| Detector feed | `detected` (empty today) |
| Vault page | `vaults_report.json` and `vaults/<address>.json` (contract below) |

Texts in Risk Desk v2 that the backend now contradicts: "oracle type Unknown", "upstream feeds not resolved", "starting probabilities are samples, not calibrated" (depeg / shortfall defaults are calibrated, C), "USDe / sUSDe not verified" (both read on chain).

## Vault report contract (`vaults_report.json`, `vaults/<address>.json`)

Second view of the front end (the PT position stays the main view): instructions in `FRONTEND_VAULT_GUIDE.md`; data for pages opened from disk in `sample_data/vaults.sample.js` (`window.VAULTS = {report, details}`, written by `vault_pipeline.py --js-out`); `RiskModel.vaultDecide` / `vaultRun` in `web/risk_model.js` recompute the verdict for any amount, probability and alternative yield (checked equal to Python by `check_js_port.py`).

Written by `vault_pipeline.py` from an input in the RockawayX dashboard format (`sample_data/rockawayx_vaults.csv`: `vault_name, vault_address, token_name, chain, protocol, category, tvl_usd, apy`; `62.7m$` / `5.59%` style values are parsed).

Input of the vault view: **vault address + amount invested** (the manager enters the amount; default 10,000,000 in the vault's asset, `--deposit`). The amount only sets the dollar figures and which exit tranche you reach; the vault's loss as a share is the same for every depositor.

`vaults_report.json`: `block`, `input`, `assumptions` (`deposit` = default amount invested (user input), `alt_apy`, `alt_apy_by_currency` {USD, EUR, ETH}, `horizon_days`: D), `coverage_counts`, `vaults[]`:

| Field | Meaning |
|---|---|
| `vault_name`, `vault_address`, `chain`, `protocol`, `tvl_usd`, `apy` | From the input row (`tvl_usd`, `apy` parsed to numbers) |
| `coverage` | `full` (ethereum + morpho: all numbers), `partial` (other ethereum protocol: dependency graph only), `not_supported` (other chain), `out_of_scope` (Solana), `error`. No loss numbers unless `full` |
| `note` | Why the coverage is what it is |
| `total_assets`, `markets` | Full only: vault assets (vault token units) and number of markets it allocates to |
| `worst_incident`, `expected_loss`, `tail_loss_95` | Full only: the incident with the highest expected vault loss, its expected loss and CVaR 95% (fractions of vault assets) |
| `free_fraction`, `locked_fraction` | Full only: share of a `deposit`-sized position that can be withdrawn now without penalty / cannot be withdrawn now |
| `decision_text` | Full only: the manager sentence of the worst incident (numbers checked) |
| `all_gates_pass`, `detail` | Full only: gates of the vault, path of the detail file |
| `verdict`, `loss_if_stay_usd`, `exit_cost_usd`, `severity`, `severity_break_even`, `currency` | Full only: decision for the worst incident at its default severity and a `deposit`-sized position (`STAY`, `EXIT`, `EXIT_PARTIAL`; money in the vault's currency); `severity_break_even` = the token loss above which withdrawing pays |
| `contract`, `dependency_graph`, `direct_dependencies` | Partial only: root contract name, edges file and counts, direct edges (`function: contract`) |

`vaults/<address>.json` (full coverage):

| Field | Meaning |
|---|---|
| `asset`, `asset_symbol`, `total_assets`, `idle`, `liquidity_market` | Vault asset, `totalAssets()`, idle balance, market id decoded from `liquidityData()` |
| `dependency_graph` | `edges_file` (`src, dst, type, kind, weight_usd, evidence`), `nodes`, `edges`, `by_kind` |
| `markets[]` | One per market held by the vault's own adapters: `market_id`, `holder` (adapter), `allocation`, `lltv`, `collateral`, `collateral_symbol`, `collateral_contract`, `collateral_type` (`pt`, `stablecoin`, `yield_wrapper`, `rwa_or_credit`, `volatile`), `oracle` (classification tree from `oracle_types.py`), `supply`, `borrow`, `liquidity`, `share_of_market` (= allocation / market supply: the vault's share of any bad debt), `n_borrowers`, `max_ltv`, `debt_within_1pct_of_liquidation`; `analyzed: false` + `note` below `--min-alloc` |
| `dependency_chain[]` | Six layers from settlement to issuers: `layer`, `name` (Settlement chain, Vault, Protocol, Markets, Collateral and oracles, Underlying and issuers), `items[]` (`label`, `address`, `market_id`, `allocation`, `detail`, `evidence`); off-chain issuers are grade D |
| `default_decision` | `decision` of the worst incident (largest vault loss at its default severity) |
| `incidents[]` | `key` (`type:SYMBOL`), `type` (`depeg`, `issuer_default`, `pt_market_dip`, `asset_issuer` = the vault's own asset fails: every depositor loses its fall and withdrawing does not remove it, `liquidity_run` = other depositors take the free liquidity first (`run`: `rows[]` for 0 / 50 / 100% with `free_usd`, `forced_usd`, `locked_usd`, `expected_loss_on_locked_usd`, `worst_credit_incident`, `worst_expected_loss`, `text`), `volatile_crypto` = not analyzed), `severity_grid[]` (`severity`, `L_low`, `L_high`: vault loss as a fraction of vault assets if the token loses that share, from every real borrower; 19 points 0.5%..100%), `permanent`, `default_severity` (historical anchor), `severity_anchors[]` (`severity`, `label`, `grade`), `decision` (`vault_decide_at` at the default severity and `deposit`: `verdict` STAY / EXIT / EXIT_PARTIAL / REVIEW, `severity`, `L`, `loss_if_stay_usd`, `exit_usd`, `exit_cost_usd`, `loss_kept_usd`, `total_if_act_usd`, `avoided_usd`, `free_usd`, `forced_usd`, `locked_usd`, `carry_cost`, `penalty`, `severity_break_even_free`, `severity_break_even_forced`), `token`, `symbol`, `layer` (2 underlying / issuer, 3 market price), `affected_markets`, `affected_allocation`, `propagation_paths` (vault -> adapter -> market -> collateral -> ... -> token, edge names in brackets), `outcomes[]` (`outcome`, `preset`, `shock`, `hours`, `probability`, `L_low`, `L_high` = vault loss as a fraction of vault assets, `per_market[]`: `oracle_falls`, `market_bad_debt_low/high`, `vault_share_of_market`, `vault_loss_low/high`), `expected_loss`, `tail_loss_95`, `var_95`, `worst_outcome`, `L_worst`, `break_even` (`p_worst` = exit cost / `L_worst`), `decision_text`, `evidence` |
| `exit` | Capacity: `free_usd` (idle + liquidity market), `forced_usd` (other markets' liquidity), `currency` + `currency_source` (DeFiLlama pegType), `alt_apy` (assumed, per currency). Exit for a `deposit`-sized depositor: `free_fraction` (idle + liquidity market), `forced_fraction` (other markets' liquidity via `forceDeallocate`), `locked_fraction`, `force_deallocate_penalty`, `carry_cost` (= max(0, vault APY - `alt_apy`) x horizon / 365: yield given up), `cost_free`, `cost_forced`, `vault_free_fraction` / `vault_forced_fraction` (same if every depositor withdrew), `restricted_gates`, `evidence` |
| `worst_incident`, `decision_text`, `notes`, `gates`, `all_gates_pass` | Summary sentence; gates: allocations + idle = totalAssets (1%), every market's borrower completeness, numbers in texts checked |

How a token failure propagates (vault mode): token -> every collateral whose dependency graph reaches it (PT -> SY -> underlying, wrapper -> asset) -> each Morpho market with that collateral -> the market's oracle decides whether liquidations happen (`oracle_types.oracle_falls`, meta-oracle threshold and timelock included) -> loss_model on every real borrower gives the market's bad debt -> the vault takes `share_of_market` of it -> vault loss per outcome -> expected and tail loss -> exit tranches and break-even.

### Evidence grades

Every `evidence` map is `{field: {grade, source, basis?, block?}}`, one entry per graded field of the object it sits in; values read on chain also carry the `block`.

| Grade | Meaning | Examples |
|---|---|---|
| A | Measured now from live API / chain data | exit quotes, capacity, LLTV, Morpho LTV, PT price |
| B | Mechanism verified in contract source **and** back-tested | Morpho health check, LIF (graded D if `validation.all_pass` is false) |
| C | Analogy from another asset's history | every preset `shock` (USDe for sUSDe; xUSD, deUSD, PT-reUSD for our PT) |
| D | Assumption or unknown | position size, debt, can_hold, oracle behaviour while unknown, assumed recovery (`permanent` of the issuer scenarios) |

A number computed from others takes the **worst** grade of the inputs it actually depends on, listed in `basis`. For example, a position's liquidation threshold is `{formula: B, ltv: D, lltv: A}` → D, while the Morpho market's aggregate threshold is `{formula: B, aggregate_ltv: A, lltv: A}` → B. Dependencies follow `loss_model`'s branches:

- `ltv` is graded by the debt input alone when debt = 0 (LTV is 0 at any size), else by debt and position size.
- L (fraction of equity) depends on `shock`, `ltv`, `can_hold` and, when it matters, `permanent`. When levered it also depends on `lltv`, the Morpho rules (`formula`) and the `oracle` behaviour. `can_hold` is dropped when every branch is liquidated; `permanent` is dropped when the position is sold at the worst point and not liquidated. Position size never enters L.
- `position_size` enters the USD amounts (`bad_debt_usd`, `branches`, `equity_usd`) and each scenario's `thresholds` / `decision_grid`: exit costs are per fraction of a position of this size, quoted at this size.
- `permanent` (recovery) is C when the recovery was observed on the anchor (the source says where), D when assumed (issuer scenarios: no recovery).

### Reasoning steps (`scenarios[].reasoning[]`)

`step` groups entries (several entries can share a number); `id` is stable for lookups. `value` is a number, string, bool, `null`, or `{low, high}` (for `L`). `unit` is `USD`, `USD per PT`, `fraction`, `fraction of equity`, `fraction of value sold`, `probability`, `ratio`, `x` (multiplier) or `null`.

| step | ids | content |
|---|---|---|
| 1 position | `position_size`, `pt`, `borrower` (only with `--borrower`), `debt`, `ltv`, `lltv`, `can_hold` | size, PT and its price, the real borrower used, debt, LTV vs LLTV, can hold or must sell |
| 2 shock | `shock`, `permanent` | fall at the worst point and its anchor; part still there at the end |
| 3 oracle | `oracle`, `oracle_type` | `"unknown, both branches"`, `true`/`false`, or `"not relevant (no debt)"`; the Morpho API oracle type |
| 4 liquidation | `threshold`, `lif` (only if liquidated), `market_threshold` | position threshold vs shock; LIF; the Morpho market's aggregate threshold vs shock |
| 5 loss | `L`, `bad_debt` (levered only) | L low/high of equity; lenders' bad debt |
| 6 exit | `capacity`, `stuck`, `cost_min`, `cost_cap`, `market_liquidations` (only with `--positions`), `exit_cost_scale` (levered only) | sellable share now, part that cannot be sold, cost at the smallest and the largest quoted size, oracle fall from which Morpho liquidations would seize more PT than the pool can absorb |
| 7 decision | `start_selling_p`, `sell_to_cap_p` | thresholds on p (`null` = never on the grid) |

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
- **Incident panel**: pick an incident, show the three outcomes with editable probabilities, `expected_loss` and `tail_loss_95`, and `decision_text`; recompute Σ p × L in the browser when the manager edits a probability.
- **Now vs later**: `borrowers.exit_later` as a chart of sellable fraction and cost against the oracle drop.
- **Reasoning panel** per scenario: `reasoning[]` as a numbered chain with a grade badge (A–D) per step, `decision_text` for the zone the slider is in, and `weakest_link` highlighted ("the verdict hinges on: …").
- A visible label that the top-level **L is a placeholder**, and that a scenario's grid uses `L_high` when `L_basis` is not `"exact"`.

## Known gaps

- Top-level L = 0.5 is a placeholder kept for compatibility; per-scenario L comes from `loss_model.py` presets (shocks are cited anchors, several by analogy).
- Depeg outcome probabilities are frequencies over other stablecoins (C) with our episode rules (0.97, 7 days, 0.5 on day 30); they move with the sample (severe 2.5%–5.4%). The oracle incident has no sample: its 50 / 50 default is a placeholder (D).
- "Exit later" assumes liquidators sell first into the same pool and the pool is not refilled; the PT price fall itself is in L, not in the exit cost.
- Lender: withdrawal gas is not measured; the "locked" part assumes no other lender withdraws first (in a run they do, so it is a best case).
- Vault mode covers ethereum + Morpho VaultV2 only (12 of the 33 RockawayX vaults). Other ethereum protocols get a dependency graph without numbers; other chains and Solana (Kamino) get no numbers. Volatile crypto collateral (WBTC, wstETH, ...) has no calibrated scenario yet and is listed as not analyzed. Issuer-default probabilities borrow the stablecoin depeg frequencies by analogy (C).
- `weakest_link` alternatives are our choices (recovery 0 ↔ 1 or 1 → 0.5, shock ×0.5 / ×1.5, debt 0 ↔ Morpho average LTV, the other oracle branch, can_hold flipped); position size is not tested (needs quotes at another size).
- Back-test tolerances are ours: ±1 bp on the distances to liquidation, ±50 bps for Pendle drop vs oracle drop. The 19 liquidated borrowers are checked as "every LTV in the reported range is liquidated", not borrower by borrower.
- For levered positions the scenario grid treats the unsold part as keeping the full position's L; deleveraging by a partial sale is not modelled.
- $10M position size is an assumption; the real size should come from Belem.
- Yield given up by selling the PT early (`carry_lost`) is set to 0.
- Capacity is a snapshot and counts only the Pendle swap route (no limit orders, OTC, or holding to maturity).
- The on-chain reader covers the Morpho borrowers only. The oracle's own logic is not read yet, so its behaviour stays `unknown` (D), while its current `price()` is read (A).
- Borrower discovery uses Morpho's API for old blocks unless an archive RPC is given; completeness is still proved on chain (`borrowShares` sum). Borrow amounts exclude interest accrued since `market.last_update`.
- The liquidation curve assumes full liquidation of every liquidatable borrower at the dropped oracle price, and compares seized PT with one Pendle sale now (no limit orders, no time to spread sales).
- The dependency graph is not merged into one file yet.
