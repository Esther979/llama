# CLAUDE.md

Backend for the Belem Capital track (EPFL Hackathon, 10–11 Oct 2026): "DeFi Risk Dependency Challenge".
Given a DeFi position (or a vault deposit): discover its dependencies layer by layer, estimate the loss if one of
them fails, and recommend how much to exit now versus stay, with reasons a portfolio manager can act on.
Judging: dependency discovery 30%, defensible impact estimate 30%, stay/exit usefulness 25%, working demo on real
data 15%. The brief's worked example is a Pendle PT position with five layers (settlement chain, yield source and
issuer, oracle, PT market / AMM, lending market), incident highlighted at layer 3 (oracle). The brief stresses:
"the hard part is not noticing the incident, it is working out what it does to your book, and how fast."

A teammate builds the front end (Risk Desk v2, a single HTML page) from our data files. Do not change existing JSON
field names or meanings without updating README.md, the two front-end guides and telling the user.

## How to work in this repo

- The user writes in Chinese: answer in Chinese. Code, comments, commit messages and repo docs stay in English.
- Work step by step. Every data step ends with a `GATE PASS` / `GATE FAIL` line; do not continue past a FAIL.
- Before running anything that measures or fetches, state a prediction of the result; afterwards say whether it held.
- Show changes as file-by-file diffs (or a per-file summary for long ones) before committing; commit / push only when
  the user asks (they usually do). End commit messages with the attribution lines from the system reminder.
- Ground every claim about an API, a contract or a field in docs, source code or a real response. Never guess
  endpoint paths, field names or contract function names: check the Etherscan verified source / ABI (`etherscan.py`),
  the GitHub source, or ask.
- Complete, runnable code, Python 3.9+, standard library where possible (pycryptodome only for keccak).
- Raw API responses go under `data/` (git-ignored). Samples for the front end go under `sample_data/` (committed).
- Any change to a model function must be mirrored in `web/risk_model.js` and pass `python3 check_js_port.py`
  (needs node). Keep the PT view (first view) stable when working on the vault view (second view).
- zsh does not word-split `$VAR`: pass file lists explicitly or as arrays. Long runs (vault pipeline ~10 min) go in
  the background (`run_in_background`), then check the log.

## Product (agreed with the team and the organisers)

Two views in one page:

1. **Position view (PT, main entry)**: PT-sUSDe-26NOV2026, held outright or as collateral on Morpho. Step 1 picks one
   of 9 nodes (`eth`, `ethena`, `usde`, `susde`, `feeds`, `oracle`, `market`, `pt`, `lending`) plus detected incidents;
   step 2 picks the failure and drags the severity (manual), plus the incident duration and "recovers / stays";
   the verdict (STAY / REDUCE / SELL_TO_CAP / EXIT) and the break-even severity follow. Details: five-layer chain with
   evidence, exit panel ("now vs later"), sensitivity ("what would change the answer"), timeline.
2. **Vault view (second view)**: input = **vault address + amount invested** (manager enters it, e.g. 100,000; default
   10,000,000; or % of portfolio x portfolio size). Vaults from the RockawayX dashboard list. Verdict badge STAY /
   EXIT / EXIT_PARTIAL / REVIEW; details: dependency chain, loss if staying vs cost of exiting in money, sentence,
   sensitivity, timeline, liquidity run.

### Decision method (no probability)

The organisers rejected p x L (sudden events cannot be predicted). The decision is made **given the incident**, at a
chosen or observed severity:
- PT view: sell share x minimising `x·(slippage(x) + carry) + (1 − x)·L(severity)`, never beyond the largest Pendle
  quote (`decision_core.decide` with p = 1; `frontend_contract.decide_at`, `RiskModel.decideAt`). Carry and slippage
  per unit of equity (x collateral / equity) for levered positions. Key output: break-even severity
  (`break_even_severity`, `RiskModel.breakEvenSeverity`).
- Vault view: withdraw each tranche whose unit cost is below L(severity): free tranche (idle + liquidity market) at
  the yield given up, forced tranche (VaultV2 `forceDeallocate` from other markets, up to their liquidity) at the
  yield given up + on-chain `forceDeallocatePenalty`; the rest is locked (`vault_pipeline.vault_decide_at`,
  `RiskModel.vaultDecideAt`). L(severity) from `severity_grid` / `duration_grids` computed from every real borrower.
- Probability-based fields (`decision_grid`, `thresholds`, `break_even`, `incidents[].probabilities`,
  `expected_loss`, `tail_loss_95`, `weakest_link`, `vault_decide`) remain in the JSON as legacy; the front end must
  not use them.

### Loss if staying (summary)

`loss_model.py`, per position or per real borrower: threshold `t = 1 − D/(C·LLTV)`; if the lending oracle falls by
the shock and shock > t → liquidated (LIF = min(1.15, 1/(1 − 0.3·(1 − LLTV))) = 1.0262 at LLTV 0.915; seized share
`q = D·LIF/(C·(1 − s))`; q ≥ 1 → equity lost, rest is bad debt); else loss = min(equity, C·s·π) (π = share of the
shock that remains; must-sell uses s). Oracle unknown → both branches, decide with the high one. Vault: bad debt of
every borrower x (vault allocation / market supply) (Morpho takes bad debt pro rata) / vault assets x amount.

## Files

| File | Role |
|---|---|
| `fetch_data.py` | step0 connectivity · step1 Pendle markets · step2 history · step3 real sell quotes · step4 Morpho markets with the PT as collateral |
| `decision_core.py` | `decide` (exit fraction minimising cost, capped at the largest quote), `slippage_at`, `load_curve`, `cvar` |
| `loss_model.py` | Loss given shock / position (Morpho rules from source), `PRESETS` (USDe, PT-reUSD, xUSD, deUSD anchors, with `recovery_source`) |
| `backtest_reusd.py` | Back-test of the Morpho rules on PT-reUSD 25 Aug 2026 (HackMD figures + our Pendle candles): 9/9; grade B depends on it |
| `calibrate_depeg.py` | Stablecoin depeg outcome frequencies (DeFiLlama, ~300 coins, 326 episodes); legacy probabilities + severity anchors |
| `incidents.py` | Legacy three-outcome incidents (p-based), exit costs with gas, exit later after liquidations, lender block |
| `reasoning.py` | Evidence grades A–D, per-scenario reasoning steps, decision texts (legacy weakest link) |
| `etherscan.py` | Etherscan V2 verified source / ABI / contract name (key `ETHERSCAN_API_KEY` in `.env`, git-ignored, never saved) |
| `crawl.py` | ABI-driven dependency crawler: calls every address-returning view, enumerates `f(uint256)` + `fLength`, turns Morpho market ids into nodes; edge kinds data / role / operator / infra |
| `oracle_types.py` | Oracle classification: linear discount, MorphoChainlinkOracleV2 (base side only), MetaOracleDeviationTimelock (threshold + timelock), Chainlink market vs reported-rate feeds, constant; `underlying_assets`; `oracle_falls(cls, layer, shock, hours, token)`; unknown → D |
| `onchain_positions.py` | Morpho borrowers over JSON-RPC (stdlib, batched): `read_market` (any market), liquidation curve 0.5–40%, gas price, borrow rate (IRM `borrowRateView`), oracle tree; 7 gates |
| `export_dashboard.py` | Builds `data/dashboard.json` for the PT view (`--positions`, `--borrower`, `--js-out`) |
| `frontend_contract.py` | PT-view contract: `ui` (9 nodes, layers, edges incl. to the position, injections), `failure_types`, `position_presets`, `time_model`, `inject`, `decide_at`, `break_even_severity`, `sensitivity`, `decide_at_duration`, `timeline_pt`, `timeline_summary` |
| `vault_pipeline.py` | Vault view: RockawayX-format input → routing, per-vault crawl, markets / allocations, borrowers, oracle types, incidents (collateral, underlying, asset issuer, liquidity run) with severity and duration grids, `vault_decide_at`, `vault_sensitivity`, `vault_timeline(_summary)`, `--js-out` |
| `web/risk_model.js` | JS port of every model function above (`RiskModel.*`) for the front end |
| `check_js_port.py` | JS vs Python on thousands of cases (17 gates) |
| `llama_graph.py` | DeFiLlama free endpoints: protocol edges, price and stablecoin replay |
| `FRONTEND_GUIDE.md`, `FRONTEND_VAULT_GUIDE.md` | Step-by-step instructions for the front-end colleague (to give to Claude), with acceptance tables |
| `README.md` | Data contracts of `dashboard.json`, `vaults_report.json`, vault details; run order |
| `sample_data/` | `dashboard.sample.json/.js` (+ levered, borrower), `vaults.sample.js`, `vaults_report.sample.json`, `vault_detail.sample.json`, `rockawayx_vaults.csv` (the 33 RockawayX vaults) |

## Refresh everything

```bash
RPC_URL=https://ethereum-rpc.publicnode.com python3 onchain_positions.py
python3 crawl.py --morpho-market 0x5613b170ded221c588b6e9637b910f49e5508680ceede207f44aa72e5c46cb05 --depth 5 --tag pt_susde_market
python3 export_dashboard.py --market 0x47ad2cd1dd15739a7a035b9d3b7828d916fef77e \
  --curves data/exit_curve_0x47ad2cd1_10m.csv data/exit_curve_0x47ad2cd1_cap.csv \
  --positions data/morpho_positions_0x5613b170.json --js-out sample_data/dashboard.sample.js
cp data/dashboard.json sample_data/dashboard.sample.json   # + levered (--debt 8950000) and borrower (--borrower 0x5c43...) samples
python3 vault_pipeline.py sample_data/rockawayx_vaults.csv --js-out sample_data/vaults.sample.js   # ~10 min
cp data/vaults_report.json sample_data/vaults_report.sample.json
python3 backtest_reusd.py && python3 calibrate_depeg.py && python3 check_js_port.py
```

## Key facts (live data, 10 Oct 2026)

Position under test: PT-sUSDe-26NOV2026 (Ethereum), Pendle market `0x47ad2cd1dd15739a7a035b9d3b7828d916fef77e`,
PT `0xb195b618ea52b77cb2a58846f452f59f8dfa9390`, sUSDe `0x9d39a5de30e57443bff2a8307a4256c8797a3497`,
Morpho market `0x5613b170ded221c588b6e9637b910f49e5508680ceede207f44aa72e5c46cb05` (USDC loan, LLTV 0.915).

- Oracle `0xF8b2…1b08` = MetaOracleDeviationTimelock: primary MorphoChainlinkOracleV2 over a
  PendleSparkLinearDiscountOracle (price = 1 − timeLeft × 6%/yr: no market input, no USDe input); backup adds
  Chainlink USDe/USD; switches only after deviation > 0.75% for 16 h (challenge timelock) + acceptChallenge.
  So a PT market dip liquidates nobody; a USDe depeg liquidates only after 16 h; a sUSDe NAV loss is seen by no feed.
- 1 sUSDe = 1.2524 USDe; SY exchange rate = sUSDe totalAssets/totalSupply; PT index = max(rate, stored) → a sUSDe
  NAV fall is a permanent PT loss, a market discount is recovered at expiry (Pendle source).
- Exit: Pendle accepts at most a $4.5M sale (0.49%), refuses $5M; $1M exits at 0.033%. Gas ~$0.1–0.3 per sale.
- 13 real borrowers; largest collateral $3.93M, closest to liquidation $3.25M at LTV 0.906 (0.99% away). Every real
  borrower can sell alone (all < $4.5M); together, liquidations exceed the pool from a 5.5% oracle drop.
- Borrow APR 3.68% (IRM) < oracle accretion 6%/yr; after expiry the oracle stays at 1 while debt accrues → the
  closest borrower crosses the LLTV in ~6 months without any shock (timeline finding).
- PT expiry 26 Nov 2026 (46 days), Pendle implied APY 5.01%.
- Vaults: 33 RockawayX rows; 12 Ethereum Morpho VaultV2 get full numbers (Belem RWA EURCV included), 4 other Ethereum
  protocols get a dependency graph only, 6 other chains not supported, 11 Solana/Kamino out of scope. Break-even
  severities of the worst incident: Tori 7.9%, YIELD 10.1%, Huma 11.8%, f(x) 13.6%, Confidential RWA 13.8% (PST),
  Belem 20.1% (mGLOeuro), NUVA 21.4%. PST is the main risk of two vaults; PT-reUSD (25 Aug incident) sits in two.

## Requirements discussed (and decisions)

- Organisers: no probability (done: severity-based core); vault address + amount input (done); STAY / EXIT badge,
  dependency chain, loss vs exit cost in money, one sentence (done); "force allocation" = most likely VaultV2
  `forceDeallocate` (used as the forced exit tranche; to confirm); "multiplied by price of PT" + timeline (done as
  incident duration + PT valued at its price; exact meaning to confirm).
- Team: PT view stays the main entry, vault view is the second view; Kamino deferred; fault injection limited to the
  9 nodes; severity slider manual; USDe ≠ sUSDe (done); timeline = incident duration, flat timelines described as
  "duration does not change the answer" (not "always stay").
- Front-end questions answered: cascade range to 40% (done), carry scaled per unit of equity (done), position edges
  in `ui.edges` (done), amount above vault assets is capped (documented).

## Not done (priority order)

1. **PT view position size**: make size an input (default $10M) with an exit curve by USD sale size (quotes cover
   $100k–$4.5M; above = capacity cap; recompute "exit later" per size); real-borrower presets with their real sizes;
   fix the three PT-price issues: PT units from the quoted price (0.99300), unlevered loss at market price (oracle
   price only for liquidation), sale cost at today's value. Optional wallet-address input.
2. **Detection** (`detect.py`): turn the signals we already read into `detected[]` (meta-oracle deviation vs 0.75% and
   challenge state, Chainlink staleness, utilization, debt within 1% of liquidation, PT price jumps) with the observed
   severity; replay PT-reUSD 25 Aug 2026 (our hourly candles) to show it fires at 04:00 UTC.
3. **Volatile collateral** (WBTC / wstETH / cbBTC, ~14% of Belem's vault, not analysed): severity anchors from
   DeFiLlama BTC/ETH drawdowns, oracles are Chainlink market feeds (follow immediately).
4. **Front-end integration check** against both acceptance tables; a 2–3 minute demo script (Belem vault → mGLOeuro →
   chain → "exit above 20%" → PT five layers → 16 h oracle timelock → timeline); one command for refresh + checks.
5. Off-chain dependencies with source URLs (Ethena exchanges / custodians, SG-Forge for EURCV, Huma receivables);
   the LLM only finds relations, numbers come from code.
6. Liquidation feasibility for RWA collateral without DEX liquidity (bad debt if liquidators cannot sell).
7. Admin / upgrade risk from the crawler's role edges (who can change an oracle or a vault, timelock, EOA vs multisig).
8. Vault timeline: PT collateral pull-to-par and borrower interest; swap cost for asset-issuer incidents (REVIEW).
9. Protocol exploit failure type; Stream xUSD / Elixir deUSD replay (Dune); Base Morpho vault; Kamino (deferred).

Open questions for the organisers: is the vault view scored or a bonus; is "force allocation" `forceDeallocate`;
exact meaning of "multiplied by price of PT"; Belem wallet addresses (would make position size grade A).

Assumptions to keep visible: PT-view size $10M is ours; default vault amount 10,000,000 is a placeholder for the
manager's input; capacity is a snapshot (Pendle swap route only); alternative yield per currency USD 4% / EUR 2% /
ETH 3% (D); default severity = median severe depeg loss 84.1% (C), the break-even severity is the informative output.

## API facts learned the hard way

- Pendle base `https://api-v2.pendle.finance/core` (no key so far). `POST /v3/sdk/{chain}/convert` needs `receiver`;
  response `routes[0].data.priceImpact`, `routes[0].outputs[0].amount`, `routes[0].data.gasUsed` (gas units; 508k to
  1.135M by size); `routes[0].data.fee.usd` is the swap fee, not gas. Spec on GitHub is older than the docs (`/v2/markets/all`).
- sUSDe is not in Pendle `/v1/assets/all`; decimals from DeFiLlama `coins.llama.fi/prices/current`.
- Morpho REST `GET /v1/blue/markets?chain_id=&collateral_token=` → `market_id`, `oracle_address`, `lltv_wad`; GraphQL
  `marketById`, `marketPositions(where: {marketUniqueKey_in, chainId_in})`; `MarketState` has `borrowApy` etc.
- RPC `https://ethereum-rpc.publicnode.com`: eth_call and JSON-RPC batches work; eth_getLogs only for the last ~10–50k
  blocks (older: 403 archive). Completeness is proved by sum of borrowShares = totalBorrowShares.
- Etherscan V2 `https://api.etherscan.io/v2/api?module=contract&action=getsourcecode&chainid=1&address=…&apikey=…`
  gives `ContractName`, `ABI`, `SourceCode`, `Proxy`, `Implementation`.
- VaultV2: `adapters(uint256)` + `adaptersLength()`, `liquidityAdapter()`, `liquidityData()` (abi-encoded
  MarketParams → id = keccak), `forceDeallocate(adapter, data, assets, onBehalf)` with `forceDeallocatePenalty(adapter)`,
  `exit()` pays from idle then the liquidity adapter. MorphoMarketV1AdapterV2: `marketIds(uint256)`,
  `marketIdsLength()`, `expectedSupplyAssets(bytes32)`.
- IRM AdaptiveCurveIrm `borrowRateView((address,address,address,address,uint256),(uint128 x6))` selector `8c00bf6b`.
- keccak256 is not in hashlib (`sha3_256` differs); pycryptodome 3.24.0 in `.venv`; selectors are hard-coded and
  re-checked with it.
- DeFiLlama free `stablecoins.llama.fi/stablecoinprices` (daily, by gecko_id, first row date 0; no Stream xUSD).
  Pro-only (avoid): `getTokenProtocols`, `getOracles`, `getHacks`, `yields.*`.
- Kamino (Solana): kVault program `KvauGMspG5k6rtzrqqn7WNn3oZdyKqLKwK2XWQ8FLjd`, klend `KLend2g3cP87fffoy8q1mQqGKjrxjC8boSyAYavgmjD`;
  public Solana RPC reads the accounts; decoding needs the IDLs (not done).
