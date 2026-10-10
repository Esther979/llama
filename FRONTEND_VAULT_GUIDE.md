# Second view: vaults

> 给前端同事：这是**第二个视图**（金库），和第一视图（单个 PT 仓位，`FRONTEND_GUIDE.md`）分开。PT 视图仍是主入口，一行都不要改。
> 把这份文件交给 Claude，说"按 FRONTEND_VAULT_GUIDE.md 在页面里加一个金库视图"。

Instructions for Claude. Add a second view, "Vaults", to the Risk Desk page. The existing PT view stays the default view and must not change (same data, same code paths). The two views share only `web/risk_model.js` and the page style.

## 1. Files

| File | Use |
|---|---|
| `sample_data/vaults.sample.js` | `window.VAULTS = {report, details}`: `report` = the 33 RockawayX vaults with their coverage; `details[address]` = full analysis of each Ethereum Morpho vault. Load with `<script>` (works from disk) |
| `web/risk_model.js` | Adds `RiskModel.vaultDecide(inc, exit, amount, pWorst, altApy, horizonDays)` and `RiskModel.vaultRun(exit, amount, share, worstExpectedLoss)`; same file as the PT view, existing functions unchanged. Checked equal to Python (`python3 check_js_port.py`) |
| `README.md`, section "Vault report contract" | Every field |

```html
<script src="vaults.sample.js"></script>   <!-- after risk_model.js; the PT view keeps dashboard.sample.js -->
```

## 2. Rules

1. A view switch in the header: "Position (PT)" (default) | "Vaults". Switching back restores the PT view exactly as it was.
2. Every number comes from `window.VAULTS` or from `RiskModel.vaultDecide` / `vaultRun`. No formulas in page code.
3. Vaults that are not `coverage: "full"` are listed but greyed, with their `note` (e.g. "Solana (Kamino) is outside the prototype"). Never show loss numbers for them.
4. Every loss is "given the incident": the probabilities are the outcomes after the incident has started (e.g. after the asset trades below 0.97). Say it next to the numbers.
5. Show evidence grades (A chain / API, B rule back-tested, C history by analogy, D assumption).

## 3. User path

**1. Input**
- Vault: dropdown from `VAULTS.report.vaults` (name, chain, protocol, TVL); `full` ones selectable. Default: "Belem RWA EURCV" (`0xd6d4b804014ef27836dbe9f8f6bf6c71251548ec`).
- Amount: number input, in the vault's asset (`details[a].asset_symbol`, currency `details[a].exit.currency`); default 1,000,000.
- Scenario: dropdown of `details[a].incidents` with `analyzed !== false`, grouped:
  - Credit incidents (a collateral or underlying fails): `type` = `issuer_default`, `depeg`, `pt_market_dip`
  - "Vault asset issuer fails": `type` = `asset_issuer` (e.g. EURCV, USDC)
  - "Morpho liquidity incident": `type` = `liquidity_run`
  - Not analyzed (`analyzed: false`, e.g. volatile crypto collateral): listed greyed with `note`
  - Default selection: `details[a].worst_incident`.
- Probability of the worst outcome: slider, starts at the incident's default (`outcomes.find(o => o.outcome === inc.worst_outcome).probability`), labelled with `inc.evidence.probabilities.source`.

**2. Verdict badge** from `const r = RiskModel.vaultDecide(inc, v.exit, amount, p, alt, horizon)`:

| `r.verdict` | Badge |
|---|---|
| `STAY` | green "STAY" |
| `EXIT` | red "EXIT" |
| `EXIT_PARTIAL` | red "EXIT `r.exit_usd`", with "`r.locked_usd` cannot be withdrawn now" |
| `REVIEW` | amber "REVIEW: withdrawing does not help" (asset issuer incidents) |

For `liquidity_run` there is no badge: show the run table (below).

**3. Details** (collapsed by default)
- Dependency chain: `details[a].dependency_chain` (6 layers: settlement chain, vault, protocol, markets, collateral and oracles, underlying and issuers), each item with `label`, `address` (Etherscan link), `detail`, `evidence`. Highlight the items on the selected incident's `propagation_paths` (strings "Vault -> [adapters[0]] MorphoMarketV1AdapterV2 -> [marketIds[0]] Morpho Blue market -> [marketParams.collateralToken] PST").
- Economic impact: "Expected loss if you stay: `r.stay_loss_usd`" and "Cost of exiting now: `r.exit_cost_usd`" (yield given up + force-deallocation penalty), plus the tail: `inc.tail_loss_95 x amount` ("worst 5% of outcomes").
- Justification sentence (templates in section 4).
- Outcomes table: `inc.outcomes` (`outcome`, `probability`, `shock`, `L_high` x amount), per market: `per_market` (`collateral`, `oracle_falls`, `market_bad_debt_high`, `vault_share_of_market`, `vault_loss_high`).
- Markets: `details[a].markets` (collateral, type, allocation, share of vault and of market, oracle kind and what it follows, borrowers, max LTV, debt within 1% of liquidation).
- Exit: tranches from `details[a].exit` (free now / with penalty / locked for this amount: `r.free_usd`, `r.forced_usd`, `r.locked_usd`), penalty `exit.force_deallocate_penalty`, and "if all depositors withdrew, only `exit.vault_free_fraction` of the vault could leave".
- Assumptions (editable, grade D): alternative yield (`exit.alt_apy`, per currency `VAULTS.report.assumptions.alt_apy_by_currency`), horizon (`exit.horizon_days`). Pass them to `vaultDecide`.
- Break-even: `r.p_break_even` ("exiting pays above this probability of the worst outcome"), `r.p_break_even_worst_alone` (brief's "exit cost / loss").

**Morpho liquidity incident** (`type: liquidity_run`): a slider "share of the free liquidity other depositors take first" (0-100%) -> `RiskModel.vaultRun(v.exit, amount, share, inc.run.worst_expected_loss)` gives `free_usd`, `forced_usd`, `locked_usd`, `expected_loss_on_locked_usd`; show `inc.run.text` as the summary and `inc.run.rows` (0%, 50%, 100%) as reference points.

## 4. Sentences (same wording as the backend)

```
EXIT / EXIT_PARTIAL:  "Exiting {exit_usd} now costs {exit_cost_usd} (yield given up[ and the force-deallocation penalty]),
                       while staying has an expected loss of {stay_loss_usd}[; {locked_usd} cannot be withdrawn now]."
STAY:                 "Staying has an expected loss of {stay_loss_usd}, below the cost of exiting ({carry_cost as %} of the
                       amount withdrawn: yield given up)."
REVIEW:               "Withdrawing returns {symbol}, so it does not remove this risk (expected loss {expected_loss as %} of
                       the deposit). Only swapping out of {symbol} does, at a cost not measured here."
```
Add "[ and the force-deallocation penalty]" when `r.forced_usd > 0` and the forced tranche is taken (`r.exit_usd > r.free_usd`); add the locked clause when `r.locked_usd > 0`. Money in the vault's currency (EUR for EURCV).

## 5. Things to state on screen

- Probabilities are given the incident (C for depegs, from 326 historical stablecoin depegs; issuer defaults use the same frequencies by analogy, C; oracle dips have no sample, D).
- Volatile crypto collateral (WBTC, wstETH, cbBTC...) has no calibrated scenario: not analyzed.
- Asset issuer incidents: second-order effects on borrowers (their debt is in the same asset) are not modelled.
- The alternative yield and horizon are assumptions (D).

## 6. Acceptance tests

After the change, these inputs must give these numbers (`RiskModel.vaultDecide(inc, v.exit, amount, p, alt, null)` with `v = window.VAULTS.details[address]`; check in the console and on screen; money in the vault's currency):

| Vault | Incident | Amount | p (worst) | alt APY | Verdict | Stay loss | Exit amount | Exit cost | Locked | p break-even |
|---|---|---|---|---|---|---|---|---|---|---|
| Belem RWA EURCV | `issuer_default:mGLOeuro` | 1,000,000 | default 0.0460 | default 2.00% | EXIT | 35,874 | 1,000,000 | 477 | 0 | 0.0611% |
| Belem RWA EURCV | `issuer_default:mGLOeuro` | 100,000 | 0.0005 | default 2.00% | STAY | 39 | 0 | 0 | 0 | 0.0611% |
| Belem RWA EURCV | `issuer_default:mGLOeuro` | 1,000,000 | default 0.0460 | 3.00% | EXIT | 35,874 | 1,000,000 | 0 | 0 | 0.0000% |
| Belem RWA EURCV | `asset_issuer:EURCV` | 1,000,000 | default 0.0460 | default 2.00% | REVIEW | 52,003 | 0 | 0 | 0 | 0.0422% |
| RockawayX Confidential RWA USDC | `issuer_default:PST` | 1,000,000 | default 0.0460 | default 4.00% | EXIT | 34,412 | 1,000,000 | 4,932 | 0 | 0.6594% |
| RockawayX Confidential RWA USDC | `issuer_default:PST` | 1,000,000 | 0.0050 | default 4.00% | STAY | 3,739 | 0 | 0 | 0 | 0.6594% |
| RockawayX Confidential RWA USDC | `issuer_default:AUTO` | 1,000,000 | default 0.0460 | default 4.00% | STAY | 937 | 0 | 0 | 0 | 24.2179% |
| RockawayX NUVA Ecosystem | `issuer_default:nvPRIME` | 1,000,000 | default 0.0460 | default 4.00% | EXIT_PARTIAL | 34,638 | 380,352 | 2,374 | 619,648 | 0.3800% |

Liquidity run, Belem RWA EURCV, amount 1,000,000 (`RiskModel.vaultRun(v.exit, 1e6, share, inc.run.worst_expected_loss)`):

| Others take | Free now | With penalty | Locked | Expected loss on locked |
|---|---|---|---|---|
| 0% | 361,743 | 638,257 | 0 | 0 |
| 50% | 180,872 | 334,977 | 484,151 | 17,369 |
| 100% | 0 | 0 | 1,000,000 | 35,874 |

## 7. Refreshing the data (backend side)

```bash
RPC_URL=https://ethereum-rpc.publicnode.com python3 vault_pipeline.py sample_data/rockawayx_vaults.csv --js-out sample_data/vaults.sample.js
python3 check_js_port.py
```
