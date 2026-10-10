# Second view: vaults

> 给前端同事：这是**第二个视图**（金库），和第一视图（单个 PT 仓位，`FRONTEND_GUIDE.md`）分开。PT 视图仍是主入口，一行都不要改。
> 把这份文件交给 Claude，说"按 FRONTEND_VAULT_GUIDE.md 在页面里加一个金库视图"。

Instructions for Claude. Add a second view, "Vaults", to the Risk Desk page. The existing PT view stays the default view and must not change (same data, same code paths). The two views share only `web/risk_model.js` and the page style.

## 1. Files

| File | Use |
|---|---|
| `sample_data/vaults.sample.js` | `window.VAULTS = {report, details}`: `report` = the 33 RockawayX vaults with their coverage; `details[address]` = full analysis of each Ethereum Morpho vault. Load with `<script>` (works from disk) |
| `web/risk_model.js` | `RiskModel.vaultDecideAt(inc, exit, amount, severity, altApy, horizonDays)` (the decision, no probability), `RiskModel.vaultLossAt(inc.severity_grid, severity)` and `RiskModel.vaultRun(exit, amount, share, lossFraction)`; same file as the PT view. Checked equal to Python (`python3 check_js_port.py`). `vaultDecide` (probability-based) is kept for compatibility only: do not use it |
| `README.md`, section "Vault report contract" | Every field |

```html
<script src="vaults.sample.js"></script>   <!-- after risk_model.js; the PT view keeps dashboard.sample.js -->
```

## 2. Rules

1. A view switch in the header: "Position (PT)" (default) | "Vaults". Switching back restores the PT view exactly as it was.
2. Every number comes from `window.VAULTS` or from `RiskModel.vaultDecide` / `vaultRun`. No formulas in page code.
3. Vaults that are not `coverage: "full"` are listed but greyed, with their `note` (e.g. "Solana (Kamino) is outside the prototype"). Never show loss numbers for them.
4. No probability: every number assumes the incident has happened, at the severity on the slider ("if PST loses 30%..."). Say it next to the numbers. The backend still has probability-based fields (`outcomes[].probability`, `expected_loss`, `tail_loss_95`, `break_even`) for compatibility: do not show them.
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
- Severity: slider "how much does {inc.symbol} lose?" from 0.5% to 100%, starting at `inc.default_severity` (a historical anchor), with tick marks at `inc.severity_anchors` (`severity`, `label`, `grade`: e.g. USDe Feb 2026 1.6%, Stream xUSD 50%, median severe depeg 84%, Elixir deUSD 99.9%). Colour the slider with the break-even severities of the result: below `r.severity_break_even_free` stay, above it withdraw the free part, above `r.severity_break_even_forced` also force out the rest.

**2. Verdict badge** from `const r = RiskModel.vaultDecideAt(inc, v.exit, amount, severity, alt, horizon)`:

| `r.verdict` | Badge |
|---|---|
| `STAY` | green "STAY" |
| `EXIT` | red "EXIT" |
| `EXIT_PARTIAL` | red "EXIT `r.exit_usd`", with "`r.locked_usd` cannot be withdrawn now" |
| `REVIEW` | amber "REVIEW: withdrawing does not help" (asset issuer incidents) |

For `liquidity_run` there is no badge: show the run table (below).

**3. Details** (collapsed by default)
- Dependency chain: `details[a].dependency_chain` (6 layers: settlement chain, vault, protocol, markets, collateral and oracles, underlying and issuers), each item with `label`, `address` (Etherscan link), `detail`, `evidence`. Highlight the items on the selected incident's `propagation_paths` (strings "Vault -> [adapters[0]] MorphoMarketV1AdapterV2 -> [marketIds[0]] Morpho Blue market -> [marketParams.collateralToken] PST").
- Economic impact at this severity: "Loss if you stay: `r.loss_if_stay_usd`" (`r.L` of the deposit), "Cost of exiting now: `r.exit_cost_usd`" (yield given up + force-deallocation penalty), "Loss still kept: `r.loss_kept_usd`" (locked part), "Loss avoided by exiting: `r.avoided_usd`". A small chart of `inc.severity_grid` (severity -> vault loss) with the current severity marked shows how the loss grows.
- Justification sentence (templates in section 4).
- Per market at the historical anchors: `inc.outcomes[].per_market` (`collateral`, `oracle_falls`, `market_bad_debt_high`, `vault_share_of_market`, `vault_loss_high`); show the shock of each row, not its probability.
- Markets: `details[a].markets` (collateral, type, allocation, share of vault and of market, oracle kind and what it follows, borrowers, max LTV, debt within 1% of liquidation).
- Exit: tranches from `details[a].exit` (free now / with penalty / locked for this amount: `r.free_usd`, `r.forced_usd`, `r.locked_usd`), penalty `exit.force_deallocate_penalty`, and "if all depositors withdrew, only `exit.vault_free_fraction` of the vault could leave".
- Assumptions (editable, grade D): alternative yield (`exit.alt_apy`, per currency `VAULTS.report.assumptions.alt_apy_by_currency`), horizon (`exit.horizon_days`). Pass them to `vaultDecide`.
- What would change the answer: `RiskModel.vaultSensitivity(inc, v.exit, amount, severity)` -> `candidates` (`alternative`, `grade`, `verdict`, `flips`; the larger deposit is a `comparison`) and `weakest` (lowest-graded assumption that flips the verdict, or `null` = robust: "No tested assumption changes the answer"). The default result is also stored as `inc.sensitivity`.
- Break-even severity: `r.severity_break_even_free` ("withdrawing pays once {symbol} loses more than this"), `r.severity_break_even_forced` ("forcing out pays once it loses more than this"); `null` = never.

**Morpho liquidity incident** (`type: liquidity_run`): a slider "share of the free liquidity other depositors take first" (0-100%) -> `RiskModel.vaultRun(v.exit, amount, share, L)` with `L` = `r.L` of the worst credit incident (`v.worst_incident`) at its current severity, gives `free_usd`, `forced_usd`, `locked_usd`, `expected_loss_on_locked_usd` (= loss on the locked part at that severity); show `inc.run.text` as the summary and `inc.run.rows` (0%, 50%, 100%, at the default severity) as reference points.

## 4. Sentences (same wording as the backend, `inc.decision_text.text` at the default severity)

```
EXIT / EXIT_PARTIAL: "If {symbol} loses {severity}, staying loses {loss_if_stay_usd} {currency} ({L} of the deposit);
                      exiting {exit_usd} now costs {exit_cost_usd} {currency}[ including the force-deallocation penalty].
                      [{locked_usd} {currency} cannot be withdrawn now.] Exiting pays once {symbol} loses more than
                      {severity_break_even_free}.[ Act early: if all depositors withdrew, only {vault_free_fraction} of
                      the vault could leave without penalty.]"
STAY:                "If {symbol} loses {severity}, staying loses {loss_if_stay_usd} {currency} ({L} of the deposit), less
                      than the cost of exiting ({carry_cost} of the amount withdrawn: yield given up). Exiting pays once
                      {symbol} loses more than {severity_break_even_free}." (or "Exiting does not pay at any severity.")
REVIEW:              "If {symbol} loses {severity}, every depositor loses {loss_if_stay_usd} {currency}. Withdrawing returns
                      {symbol}, so it does not remove this risk; only swapping out of {symbol} does, at a cost not
                      measured here."
```
The penalty clause when `r.exit_usd > r.free_usd` and `r.penalty > 0`; the locked clause when `r.locked_usd > 0`; the "act early" clause when `exit.vault_free_fraction < 0.999`. Money without decimals, in the vault's currency.

## 5. Things to state on screen

- Every number assumes the incident has happened; severity is chosen (or observed), not predicted. The slider's anchors are historical (C).
- Volatile crypto collateral (WBTC, wstETH, cbBTC...) has no calibrated scenario: not analyzed.
- Asset issuer incidents: second-order effects on borrowers (their debt is in the same asset) are not modelled.
- The alternative yield and horizon are assumptions (D).

## 6. Acceptance tests

After the change, these inputs must give these numbers (`RiskModel.vaultDecideAt(inc, v.exit, amount, severity, null, null)` with `v = window.VAULTS.details[address]`, default alternative yield and horizon; money in the vault's currency):

| Vault | Incident | Amount | Severity | Verdict | Loss if stay | Exit | Exit cost | Locked | Break-even severity (free / forced) |
|---|---|---|---|---|---|---|---|---|---|
| Belem RWA EURCV | `issuer_default:mGLOeuro` | 1,000,000 | default 84.14% | EXIT | 616,185 | 1,000,000 | 477 | 0 | 20.09% / 20.09% |
| Belem RWA EURCV | `issuer_default:mGLOeuro` | 1,000,000 | 10.00% | STAY | 0 | 0 | 0 | 0 | 20.09% / 20.09% |
| Belem RWA EURCV | `issuer_default:mGLOeuro` | 100,000 | 30.00% | EXIT | 5,345 | 100,000 | 48 | 0 | 20.09% / 20.09% |
| Belem RWA EURCV | `asset_issuer:EURCV` | 1,000,000 | 5.00% | REVIEW | 50,000 | 0 | 0 | 0 | 0.05% / 0.05% |
| RockawayX Confidential RWA USDC | `issuer_default:PST` | 1,000,000 | 10.00% | STAY | 0 | 0 | 0 | 0 | 13.82% / 16.25% |
| RockawayX Confidential RWA USDC | `issuer_default:PST` | 1,000,000 | 30.00% | EXIT | 123,819 | 1,000,000 | 4,932 | 0 | 13.82% / 16.25% |
| RockawayX Confidential RWA USDC | `pt_market_dip:PT-reUSD-10DEC2026` | 1,000,000 | default 2.97% | STAY | 0 | 0 | 0 | 0 | 15.39% / 23.47% |
| RockawayX YIELD USDC | `issuer_default:PT-reUSD-10DEC2026` | 1,000,000 | 50.00% | EXIT | 182,023 | 1,000,000 | 4,968 | 0 | 10.11% / 11.95% |
| RockawayX NUVA Ecosystem | `issuer_default:nvPRIME` | 1,000,000 | default 84.14% | EXIT_PARTIAL | 587,966 | 380,352 | 2,374 | 619,648 | 21.37% / 26.23% |

Liquidity run, Belem RWA EURCV, amount 1,000,000, mGLOeuro at its default severity (L = 0.6162; `RiskModel.vaultRun(v.exit, 1e6, share, L)`):

| Others take | Free now | With penalty | Locked | Loss on locked part |
|---|---|---|---|---|
| 0% | 361,743 | 638,257 | 0 | 0 |
| 50% | 180,872 | 334,978 | 484,151 | 298,326 |
| 100% | 0 | 0 | 1,000,000 | 616,185 |

## 7. Refreshing the data (backend side)

```bash
RPC_URL=https://ethereum-rpc.publicnode.com python3 vault_pipeline.py sample_data/rockawayx_vaults.csv --js-out sample_data/vaults.sample.js
python3 check_js_port.py
```
