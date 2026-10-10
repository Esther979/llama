# CLAUDE.md

Backend for the Belem Capital track (EPFL Hackathon, 10–11 Oct 2026): "DeFi Risk Dependency Challenge".
Given one DeFi position: discover its dependencies, estimate the loss if one fails, and recommend
how much to exit now versus stay. Judging: dependency discovery 30%, defensible impact estimate 30%,
stay/exit usefulness 25%, working demo on real data 15%.

A teammate builds the dashboard from `data/dashboard.json` (contract in README.md). Do not change that
JSON's field names or meaning without updating README.md and telling the user.

## How to work in this repo

- Work step by step. Every data step ends with a `GATE PASS` / `GATE FAIL` line; do not continue past a FAIL.
- Before running anything that measures or fetches, state a prediction of the result; afterwards say whether it held.
- Show changes as file-by-file diffs. Never rewrite a whole file when an edit will do.
- Ground every claim about an API, a contract or a field in docs, source code or a real response.
  Never guess endpoint paths, field names or contract function names; check first, or ask.
- Write complete, runnable code, not templates. Python 3.9+, standard library where possible.
- Raw API responses are saved under `data/` (git-ignored). Keep doing that.

## Files

| File | Role |
|---|---|
| `fetch_data.py` | step0 connectivity · step1 Pendle markets · step2 history · step3 real sell quotes · step4 Morpho markets with the PT as collateral |
| `decision_core.py` | Picks exit fraction x minimising `x·slippage(x) + (1−x)·p·L`, capped at the largest size with a real quote |
| `export_dashboard.py` | Builds `data/dashboard.json` (position, exit curve, capacity, lending, thresholds, decision grid over p) |
| `llama_graph.py` | DeFiLlama free endpoints via `defillama-sdk` 0.1.4: protocol-level edges, price and stablecoin replay |
| `sample_data/dashboard.sample.json` | dashboard.json from the 10 Oct run, for UI work without API calls |

## Current position under test

PT-sUSDe-26NOV2026, Ethereum (chain 1)
- Pendle market `0x47ad2cd1dd15739a7a035b9d3b7828d916fef77e`
- PT `0xb195b618ea52b77cb2a58846f452f59f8dfa9390`
- underlying sUSDe `0x9d39a5de30e57443bff2a8307a4256c8797a3497`
- Morpho market (USDC loan, LLTV 0.915), id starts `0x5613b170de`; oracle `0xF8b29e7E9c00CE531434775f7923CC9fbCa01b08` (Morpho API type: Unknown)

## Findings so far (10 Oct 2026, live data)

- Exit is cheap but capped: for an assumed $10M position, selling $4.5M costs 0.49%; Pendle refuses $5M
  (`MarketProportionTooHigh`). $1M exits fully at 0.033%.
- Morpho: collateral $7.93M, borrow $6.99M, aggregate LTV 0.882 vs LLTV 0.915 (≈3.6% PT drop to liquidation);
  withdrawable liquidity $0.76M; Morpho PT collateral exceeds what the Pendle pool can absorb in one sale.
- With the placeholder L = 0.5: p > 4.2% → sell to the 45% cap; p < 0.03% → stay.

## Status

Done
- Live data pipeline for one position (Pendle + Morpho), real exit curve and capacity.
- Decision maths with capacity cap; dashboard export; JS port in README checked equal to Python (201/201 points).

Not done (in priority order)
1. Per-layer loss model to replace the placeholder L = 0.5:
   L2 issuer/depeg (PT redeems to sUSDe, so loss ≈ underlying drop) · L3 oracle (min/TWAP manipulation, see
   PT-reUSD incident) · L5 liquidation for levered holders (Morpho LIF = min(1.15, 1/(1 − 0.3·(1 − LLTV))),
   ≈1.0262 at LLTV 0.915).
2. Merge all dependencies into one edge file: `src, dst, type, weight_usd, evidence`
   (evidence = which API/contract call and block). Today the data sits in separate JSON files.
3. On-chain crawler over RPC: start from the position, read referenced contracts layer by layer, resolve the
   Unknown Morpho oracle. Verify function signatures from the Pendle and Morpho GitHub sources before coding.
   Needs an RPC URL (asked from Belem); historical replay needs an archive node.
4. Off-chain dependencies for L2 (Ethena: exchanges, custodians) via GraphRAG + LLM agent, each edge with a source URL.
   The LLM never produces the loss numbers; numbers come from code.
5. `carry_lost` (yield given up by selling the PT early) is 0; make the alternative yield an input.
6. Replays: Stream xUSD / Elixir deUSD (Nov 2025, L2 issuer failure) and PT-reUSD on Morpho (25 Aug 2026,
   L3 oracle manipulation, analysis at hackmd.io/@kanveuler/BJe_n1ivGe).

Assumptions to keep visible: position size $10M is ours, not Belem's; capacity is a snapshot and counts only
the Pendle swap route (no limit orders, OTC, or holding to maturity); p is set by the manager on the dashboard.

## API facts learned the hard way

- Pendle base `https://api-v2.pendle.finance/core`. Works without a key so far; if 401/403, set `PENDLE_API_KEY`.
- Pendle `POST /v3/sdk/{chain}/convert` requires `receiver` (any valid address works for quotes), despite the
  OpenAPI spec marking it optional. Response: `routes[0].data.priceImpact`, `routes[0].outputs[0].amount`.
- The OpenAPI spec on GitHub is older than the docs (spec: `/v1/markets/all`, `/v2/.../historical-data`;
  docs: `/v2/markets/all`, `/v3/.../historical-data`). The code tries the newer path first.
- sUSDe is not in Pendle `/v1/assets/all`; decimals come from DeFiLlama `coins.llama.fi/prices/current`.
- Morpho: REST `GET /v1/blue/markets?chain_id=&collateral_token=` returns `market_id`, `oracle_address`, `lltv_wad`;
  GraphQL `marketById` gives state and oracle. Oracle details only for ChainlinkOracle / ChainlinkOracleV2 types.
- DeFiLlama Pro-only (avoid): `getTokenProtocols`, `getOracles`, `getHacks`, all `yields.*`.
