# Risk Desk v2: connecting the front end to the backend

> For the front-end colleague: give this file together with `Dependency_Risk_Desk_v2.html` to Claude and say "edit this page following FRONTEND_GUIDE.md".
> Keep the layout, but **remove step 3 (probability)**: the organisers consider that the probability p of a sudden incident cannot be predicted, so the core method is now "assume the incident has happened and decide by its severity".
> Step 1 picks a node (the fixed 9 nodes + detected incidents), step 2 drags the severity by hand; the verdict follows from the severity alone, with "above which fall you should exit" (the break-even severity).
> What changes: the data are read from the backend files, losses and verdicts are computed by the backend model, and outdated texts are removed.
> New: the position size is the manager's input (USD, default $10M); a wallet address can also be entered (a wallet read on chain at the same block by `onchain_positions.py --wallet`, or a borrower of this Morpho market, at its real on-chain size; numbers are never typed in by hand). The two real-borrower presets use their real sizes.
> The "Cash earns after selling, % APY" input is annual: convert it with `RiskModel.carryOf(d, S.alt / 100)` into the yield given up until expiry before passing it to the model (4% -> 0.128%); never pass the annual difference.

Instructions for Claude. Edit `Dependency_Risk_Desk_v2.html` so that it reads the backend's data and computes every number with the backend's model. Keep the layout, the five-layer chain, the decision card, the exit panel, the drawer and the prototype controls. Remove step 3 (the probability slider) and everything that uses a probability: the decision is made given the incident, at the severity chosen in step 2.

## 1. Files

From the repo (`git pull`):

| File | Use |
|---|---|
| `sample_data/dashboard.sample.js` | The data as `window.DASHBOARD = {...};`. Load it with a `<script>` tag (works when the page is opened from disk) |
| `sample_data/dashboard.sample.json` | Same data as JSON, if the page is served over HTTP (`fetch`) |
| `web/risk_model.js` | The model: `RiskModel.atSize` (position size and wallet, call first), `carryOf` (annual cash yield -> carry), `decideAt`, `breakEvenSeverity`, `sensitivity`, `decideAtDuration`, `timeline`, `timelineSummary`, `inject`, `walletPresets`, `positionLoss`, `oracleFalls`, `slippageAt`. Checked equal to the Python backend (`python3 check_js_port.py`) |
| `README.md`, section "Frontend integration" | Field-by-field contract of `dashboard.json` |

Copy `sample_data/dashboard.sample.js` and `web/risk_model.js` next to the HTML file (or adjust the paths), and put the two scripts before the page's own script:

```html
<script src="dashboard.sample.js"></script>
<script src="risk_model.js"></script>
```

## 2. Rules

1. Do not hard-code numbers from the old snapshot. Read everything from `d = RiskModel.atSize(window.DASHBOARD, S.size, S.wallet)` (section 3b), recomputed whenever the size or the wallet input changes.
2. Do not compute losses in page code. Delete the `loss` functions of `FAIL`, `valueDrop` and the local `LIF` / `LIQ_DIST` formulas; call `RiskModel.inject(d, presetKey, node, fail, sev)` instead.
3. Step 1 offers exactly the 9 nodes of `d.ui.nodes` (grouped by `d.ui.layers`), plus the detected incidents (`d.detected`, empty today; keep the prototype sample feed, still labelled as invented).
4. Step 2 stays a manual slider: keep each failure's `label`, `unit`, `min`, `max` and starting value from the page's `FAIL` table (the same keys exist in `d.failure_types.types`). Add two entries for sUSDe, taking `label`, `unit`, `min`, `max`, `default_severity` from `d.failure_types.types.navLoss` and `.discount` ("NAV falls (USDe per sUSDe)", "Trades below its NAV"). USDe and sUSDe are different assets: 1 sUSDe is worth about 1.25 USDe, so "depeg" (falling below $1) applies to USDe only.
5. No probability anywhere: delete step 3, `S.p`, `pOf` / `vOf`, the partial-case assumptions (`pk`, `ps`) and the probability zones. The decision assumes the incident has happened; the severity slider is the only "how bad" input. Show on that slider the zones from `RiskModel.breakEvenSeverity` (stay / sell part / sell to the pool limit). The backend still has probability-based fields (`decision_grid`, `thresholds`, `incidents[].probabilities`...) for compatibility: do not use them.
6. Show evidence grades: A = read from chain / API, B = contract rule back-tested, C = analogy from history, D = assumption. Dashed style = D.
7. Keep the field names of `dashboard.json`. If something is missing, ask the backend (do not invent it).

## 3. Replace the constants

| Page constant | Replace with |
|---|---|
| `D` (snapshot) | `d = RiskModel.atSize(window.DASHBOARD, S.size, S.wallet)` (section 3b) |
| `N`, `CURVE`, `MAXX` | `d.position.notional_usd` (= the size input), `d.exit_curve.map(x => [x.fraction, x.loss])`, `d.max_exit_fraction` (all for the size input; 1 up to $4.5M) |
| `LD` | `d.lending[0]` (`lltv`, `collateral_usd`, `borrow_usd`, `liquidity_usd`, `aggregate_ltv`, `oracle_address`; `market_id` is now the full id) |
| `NODES` | `d.ui.nodes`: same 9 keys (`eth`, `ethena`, `usde`, `susde`, `feeds`, `oracle`, `market`, `pt`, `lending`) with `label`, `kind`, `layer`, `address`, `contract_name`, `members` (ids in `d.dependency_graph.nodes`), `evidence {grade, source}`, `note`, `failures` |
| `LAY` | `d.ui.layers` (`n`, `name`, `nodes`); facts per layer: see section 6 |
| `EDGES` | `d.ui.edges` (`from`, `to`, `type`, `grade`, `evidence`), including the two edges to the position: `pt -> position` "holding" (D: the size is assumed) and `lending -> position` "liquidation" (B: Morpho rule, back-tested; `applies_to` = the levered presets). Draw only those, do not add page-made edges |
| `FBN` | `d.ui.nodes[k].failures` (sUSDe now has `navLoss` and `discount` instead of `depeg`) |
| `POS` | `d.position_presets`: `spot`, `lev_market_avg` (follow the size input), `lev_largest_borrower`, `lev_closest_to_liquidation` (real positions: $3.93M and $3.25M), plus `wallet` (PT held in the wallet) and / or `wallet_morpho` (its Morpho position) when a wallet was found (`label`, `collateral_usd` = market value, `collateral_oracle_usd`, `pt_units`, `debt_usd`, `lltv`, `ltv`, `sized`, `evidence`). Fill the header position `<select>` from it; show the size next to each label (real borrowers: "real position") |
| `FAIL[k].loss` | delete; `RiskModel.inject` |
| `FAIL[k].prob` | delete (no probability) |
| `stress()` | the `sellable_later` / `avg_cost_later` returned by `inject` (drain keeps its own curve, section 7) |
| `DETECTED` | `d.detected` when it is not empty; otherwise the prototype sample list (keep it labelled as invented) |
| `REPLAYS` | oracle: node `oracle`, failure `oracleLow`, severity 2.77 (`d.failure_types.types.oracleLow.anchors[0]`), and show `d.validation` ("back-test of the liquidation rules on PT-reUSD: 9/9 checks pass"); issuer: node `ethena`, failure `shortfall`, severity 50 (Stream xUSD) or 99.87 (Elixir deUSD) from `anchors` |

## 3b. Position size and wallet (header inputs)

Add two inputs to the header, next to the position `<select>`:

- "Position size (USD)": a number, default `window.DASHBOARD.size_input.default_usd` (10,000,000), marked as an assumption (D) until the manager types a size. It sets the size of `spot` (PT held outright) and `lev_market_avg` (PT as collateral at the market's average LTV).
- "Wallet (optional)": an address, typed or picked from a list of the addresses in `d.borrowers.wallets` and `d.borrowers.list`. Presets appear at the wallet's real size, read on chain (grade A): `wallet` = PT held in the wallet, `wallet_morpho` = its position in this Morpho market. Messages: `d.wallet_read === false` -> "not read on chain: rerun onchain_positions.py --wallet <address>"; `wallet_read` true and `wallet_found` false -> "holds no PT-sUSDe in the wallet or in this Morpho market at block {d.borrowers.block}". Nothing is typed in by hand: the numbers come only from the chain.

```js
let d = RiskModel.atSize(window.DASHBOARD, S.size, S.wallet || null);   // on load and on every size / wallet change
```

Every other call takes this `d`. What changes with the size: PT units = size / `size_input.pt_price_usd`; Morpho values them at `size_input.oracle_price_usd` (liquidation only); the exit curve: up to `size_input.capacity_usd` ($4.5M) the whole position can be sold (`d.max_exit_fraction` = 1), above it the rest is stuck; "exit later" after liquidations. Show under the inputs: "{pt_units} PT at {pt_price_usd}; sellable now: {max_exit_fraction} ({capacity_usd} pool limit)".

## 4. The model

`RiskModel.inject(d, presetKey, node, fail, sev)` returns, for one outcome:

| Field | Meaning |
|---|---|
| `L_low`, `L_high` | Loss as a fraction of the position's equity (= of the position when unlevered). They differ only when the oracle behaviour is unknown; decide with `L_high`, show the range |
| `loss_usd` | `L_high` x equity |
| `oracle_falls` | Does the lending oracle follow this failure? `true` / `false` / `null` (unknown) |
| `liquidated` | Per oracle branch, is the position liquidated? |
| `sellable_now`, `sellable_later`, `avg_cost_later` | Exit today and after the failure plays out (fractions of the position; `avg_cost_later` null = nothing can be sold) |
| `note` | Why: the propagation rule in one sentence. Show it |

How each node and failure is modelled (`d.ui.injections`):

| Node · failure | Oracle follows? | What it means |
|---|---|---|
| `ethena:shortfall`, `usde:depeg` | after the meta-oracle switch (deviation > 0.75% for 16 h) | USDe / USD is priced only by the backup oracle |
| `susde:navLoss` | no | sUSDe's NAV (USDe per sUSDe) falls: the PT loses the same share for good (Pendle's PT index never decreases), no feed prices the NAV, so nobody is liquidated |
| `susde:discount` | no | sUSDe trades below its NAV while the NAV is unchanged: the PT still redeems at the NAV-based rate, holding to expiry recovers it |
| `pt:depeg` | no | the oracle prices the PT by a linear discount; holding to expiry recovers the PT |
| `feeds:oracleLow`, `oracle:oracleLow` | yes (by definition) | liquidations happen at the low price, then the price recovers |
| `lending:cascade` | (the cause) | severity = oracle drop that liquidates other borrowers; their PT is sold into the pool first |
| `market:drain` | — | severity = pool liquidity removed (assumption, grade D) |
| `eth:halt`, `feeds:stale`, `oracle:stale` | — | no direct loss modelled |

Rewrite `model()` around the two decision functions (no probability):

```js
// d = RiskModel.atSize(window.DASHBOARD, S.size, S.wallet), section 3b
function model() {
  const P = d.position_presets[S.pos], equity = P.collateral_usd - P.debt_usd;
  const f = FAIL[S.fail];                                   // page's own slider range (step 2)
  const r = RiskModel.decideAt(d, S.pos, S.node, S.fail, S.sev, carry());
  const be = RiskModel.breakEvenSeverity(d, S.pos, S.node, S.fail, carry(), f.min, f.max);
  return {P, equity, r, be};
}
```

`RiskModel.decideAt(d, preset, node, fail, sev, carry)` = `inject` plus the decision: it sells the share x of the position that minimises x x (slippage + carry) + (1 - x) x L(sev), never beyond the largest Pendle quote (the same `decide()` as before, with the incident certain). It returns everything `inject` returns, plus:

| Field | Meaning |
|---|---|
| `verdict` | `STAY`, `REDUCE` (sell part), `SELL_TO_CAP` (sell all the pool takes; the rest is stuck), `EXIT` (sell everything) |
| `sell_fraction`, `sell_usd` | How much to sell now |
| `sale_cost_usd` | Slippage + yield given up on what is sold |
| `loss_if_stay_usd` | Loss if you do nothing (L x equity) |
| `loss_kept_usd` | Loss on the part you keep |
| `total_if_act_usd`, `avoided_usd` | Sale cost + loss kept; loss avoided by acting |
| `stuck_fraction` | Share that cannot be sold through the pool now |

`RiskModel.breakEvenSeverity(d, preset, node, fail, carry, lo, hi)` returns `{start, cap}`: the smallest severity (in the failure's unit) at which selling starts, and at which it reaches the pool limit (or a full exit); `null` = not within `[lo, hi]`. Pass the page's slider range as `lo`, `hi`.

- `carry()`: the input "Cash earns after selling, % APY" (`S.alt`, default `d.time_model.implied_apy x 100` = 5.01, i.e. nothing given up) is annual; the model needs the yield given up **until expiry** as a fraction of the value sold. Always convert with `const carry = () => RiskModel.carryOf(d, S.alt / 100);` (= max(0, implied APY - S.alt / 100) x days to expiry / 365: 4% today -> 0.128%, not 1.01%). Never pass the annual difference: it overstates the cost of selling about 8 times (46 days to expiry). `decideAt`, `breakEvenSeverity` and `sensitivity` multiply it by value / equity for levered presets, like the slippage. Parse the input with a decimal comma too ("5,01").
- Severity zones on the step-2 slider: `[lo, be.start)` stay, `[be.start, be.cap)` sell part, `[be.cap, hi]` sell to the pool limit.
- Money: everything is already in USD in the result.

## 5. Decision card

- Badge: `r.verdict` (`STAY` green, `REDUCE` amber "Sell `sell_usd`", `SELL_TO_CAP` red "Sell `sell_usd`, `stuck_fraction` stuck", `EXIT` red).
- Sentence (numbers from `r` and `be` only): "If {node label} {failure label lowercased} by {sev}, doing nothing loses {loss_if_stay_usd}. Selling {sell_usd} now costs {sale_cost_usd} and leaves {loss_kept_usd} at risk on the rest." For `STAY`: "If ..., doing nothing loses {loss_if_stay_usd}; selling would cost more than it saves." Then: "Selling starts to pay once the severity exceeds {be.start}" (or "Selling does not pay at any severity on this slider").
- Bars: "Do nothing" = `loss_if_stay_usd`; "Act" = `sale_cost_usd` + `loss_kept_usd`.
- Under the verdict, one line from `r.note`, and: oracle follows = `r.oracle_falls`, liquidated = `r.liquidated`. If `r.L_low !== r.L_high`: "loss between L_low and L_high depending on the oracle; the decision uses the high end".
- "What would change the answer": `const sv = RiskModel.sensitivity(d, S.pos, S.node, S.fail, S.sev, carry())`. It replaces one assumption at a time by its stated alternative and reruns the decision. Show `sv.candidates` as a table (`alternative`, `grade`, `verdict`, a mark when `flips`), the other position presets (`comparison: true`) in a separate "other positions" group, and highlight `sv.weakest`: the lowest-graded assumption that flips the verdict ("The answer hinges on: {alternative} (grade {grade}) -> {verdict}"); `null` -> "No tested assumption changes the answer". Also show the severity break-even (`be.start`, `be.cap`). The backend's `weakest_link` / `scenarios[].weakest_link` fields are probability-based legacy: do not use them.

## 5b. Timeline: how long the incident lasts

The organisers asked for a timeline ("over how many months, what risk") with the PT valued at its price. Add to step 2, under the severity slider:

- "How long does it last?": a duration slider, log scale from 1 hour to 6 months (`hours`), with tick marks at the meta-oracle switch (`d.oracle.challenge_timelock_s / 3600` = 16 h) and at the PT's expiry (`d.time_model.days_to_expiry x 24` h).
- "After the incident": a toggle "recovers" (default) / "stays" (`recovers` true / false).

Compute with `RiskModel.decideAtDuration(d, S.pos, S.node, S.fail, S.sev, hours, recovers, altApy)` instead of `decideAt` (same result fields, plus `hours`, `days`, `past_expiry`, `carry`, `pt_price_market`, `pt_price_oracle`, `position_value_usd`, `collateral_usd`, `debt_usd`, `ltv`). `altApy` = the "cash earns" assumption as a fraction (`S.alt / 100`; `null` = the PT's implied APY, i.e. no yield given up); these functions convert it themselves (`carryOf` over the incident's duration, at most until expiry). What it models:

| Effect of the duration | How |
|---|---|
| Meta-oracle switch | below 16 h the oracle does not switch, so a USDe depeg liquidates nobody; from 16 h it does (`oracle_falls`) |
| Recovery | `recovers`: the shock disappears after the incident, so a holder who can wait loses nothing, but liquidations that happened during it stay |
| PT valued at its price | position value = PT units x PT price at the end of the incident: market price from the implied APY, oracle price from the linear discount (6% a year), both 1 at expiry (`position_value_usd`, `pt_price_*`). The loss is on the market value; the oracle value (`collateral_usd` in the result) is used only for the liquidation check; a sale now is costed on today's value |
| Debt over time | levered presets: debt grows at the market's borrow APR (`d.time_model.borrow_apr`, read on chain); the oracle price rises with the linear discount; after expiry it stays at 1 while the debt keeps growing (`ltv`) |
| Yield given up | exiting gives up (implied APY - alt) over the incident, at most until expiry (`carry`) |

Describe the timeline with `RiskModel.timelineSummary(d, S.pos, rows)`: `duration_matters` false -> "The duration does not change the answer: {why_flat}" (e.g. an unlevered holder: no debt, so no oracle timer and no interest; the verdict then comes from the severity and the recovers / stays toggle, it is not "always stay"); true -> one line per `changes[]` entry: "From {to_hours} h: {verdict_before} -> {verdict_after} ({reason})".

Timeline chart: `RiskModel.timeline(d, S.pos, S.node, S.fail, S.sev, recovers, altApy)` returns the same object for 1 h, 6 h, 12 h, 16 h, 1 d, 2 d, 3 d, 1 w, 2 w, 30 d, expiry, 60 d, 90 d, 180 d. Plot `loss_if_stay_usd` against the duration (log x axis), colour the background by `verdict`, and mark 16 h and expiry. Assumptions to show (D): pool depth as today, borrow APR constant, implied APY constant.

## 6. Five-layer chain

Layer facts (replace the old texts, numbers from the data):

| Layer | Head | Fact |
|---|---|---|
| 1 | `d.ui.nodes.eth.label` | "Every contract below settles here" |
| 2 | "sUSDe, backed by USDe and Ethena" | "The PT redeems to sUSDe at expiry"; USDe and sUSDe are read on chain (grade A) |
| 3 | `d.ui.nodes.oracle.contract_name` | `d.ui.nodes.oracle.note` (linear discount, 0.75% / 16 h switch, deviation now) |
| 4 | `d.ui.nodes.market.label` | "You can sell `max_exit_fraction x notional` today" |
| 5 | `d.ui.nodes.lending.label` | "`d.borrowers.distribution.n_borrowers` borrowers; Morpho liquidations would exceed the pool from a `d.borrowers.first_drop_seized_exceeds_capacity` oracle drop" |

Effects shown on the red path, from `r` (the `decideAt` result):

- origin layer: the failure and severity, e.g. "USDe down 2%".
- layer 3: `oracle_falls === true` -> "Oracle follows (after the 16 h switch)" for `usde` / `ethena`, "Oracle reports the low price" for `oracleLow`; `false` -> "Oracle does not move (linear discount, no market input)".
- layer 4: `sellable_later < sellable_now` -> "Sellable falls from X to Y".
- layer 5: `liquidated` contains true -> "Your position is liquidated"; levered and false -> "Not liquidated".
- your position: `loss_usd`.

Remove these old texts, the backend now contradicts them: "Type unknown", "Upstream feeds are not resolved yet", "Not resolved. Needs the on-chain crawler", "Not verified. Planned: on-chain read from the sUSDe contract", "Starting probabilities are samples, not calibrated from history" (keep it only for failures whose `p_severe` is null).

## 7. Exit panel

- Today: `max_exit_fraction`, cost `slippageAt(max_exit_fraction)`; optional gas per size in `d.exit_curve[i].gas_usd`.
- If this plays out: `r.sellable_later` and `r.avg_cost_later` (null -> "No room left"). For `lending:cascade` and for failures where the oracle follows, these come from the real liquidation curve (`d.borrowers.exit_later`, oracle drops 0.5% to 40%, so the page's cascade slider range up to 40% is covered), replacing the "pool liquidity leaves" assumption.
- Dashed curve: only for `market:drain` (the page's existing `stressCurve(sev / 100)`).
- The refused row: `d.evidence.max_exit_fraction.source` names the refused sizes.

## 8. Evidence drawer

For a node `k`: `d.ui.nodes[k]` (`kind`, `layer`, `address` with the Etherscan link, `contract_name`, `evidence`, `note`), its `members` looked up in `d.dependency_graph.nodes` (label, contract name, address, grade), and the edges of `d.ui.edges` touching `k` with their `evidence`. For `oracle`, add the oracle tree `d.oracle` (primary, backup, threshold, timelock, deviation now). For `feeds`, the count of Chainlink transmitters is in the note.

## 9. Acceptance tests

`d = RiskModel.atSize(window.DASHBOARD, size)`, then `RiskModel.decideAt(d, preset, node, fail, sev, 0)` (carry 0) and `RiskModel.breakEvenSeverity(d, ..., 0, min, max)` with the failure_types range; check in the console and on screen:

| Size | Preset | Node · failure | Severity | Verdict | Sell | Sale cost | Loss if stay | Loss kept | Oracle falls | Sellable later | Break-even severity (start / cap) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 10M | `spot` | `susde:navLoss` | 10% | SELL_TO_CAP | 45% | $22,089 | $1,000,000 | $550,000 | False | 0.4500 | 0.500% / 2.052% |
| 10M | `spot` | `susde:discount` | 3% | STAY | 0% | $0 | $0 | $0 | False | 0.4500 | - / - |
| 10M | `spot` | `pt:depeg` | 10% | STAY | 0% | $0 | $0 | $0 | False | 0.4500 | - / - |
| 10M | `spot` | `usde:depeg` | 10% | SELL_TO_CAP | 45% | $22,089 | $1,000,000 | $550,000 | True | 0.0000 | 1.000% / 2.052% |
| 10M | `lev_closest_to_liquidation` | `usde:depeg` | 0.5% | REDUCE | 92% | $4,077 | $16,247 | $1,300 | False | 1.0000 | 1.000% / 1.000% |
| 10M | `lev_closest_to_liquidation` | `usde:depeg` | 2% | EXIT | 100% | $5,683 | $143,833 | $0 | True | 0.4362 | 1.000% / 1.000% |
| 10M | `lev_closest_to_liquidation` | `susde:navLoss` | 2% | EXIT | 100% | $5,683 | $64,989 | $0 | False | 1.0000 | 0.500% / 0.657% |
| 10M | `lev_closest_to_liquidation` | `pt:depeg` | 10% | STAY | 0% | $0 | $0 | $0 | False | 1.0000 | - / - |
| 10M | `lev_closest_to_liquidation` | `oracle:oracleLow` | 2.77% | EXIT | 100% | $5,683 | $164,903 | $0 | True | 0.3889 | 1.000% / 1.000% |
| 10M | `lev_largest_borrower` | `usde:depeg` | 2% | EXIT | 100% | $11,804 | $78,675 | $0 | True | 0.3604 | 1.000% / 1.087% |
| 10M | `lev_market_avg` | `ethena:shortfall` | 50% | SELL_TO_CAP | 45% | $22,089 | $1,178,097 | $647,954 | True | 0.0000 | 1.000% / 2.052% |
| 10M | `spot` | `lending:cascade` | 1% | STAY | 0% | $0 | $0 | $0 | None | 0.1449 | - / - |
| 10M | `spot` | `lending:cascade` | 20% | STAY | 0% | $0 | $0 | $0 | None | 0.0000 | - / - |
| 10M | `spot` | `market:drain` | 60% | STAY | 0% | $0 | $0 | $0 | None | 0.1800 | - / - |
| 10M | `lev_market_avg` | `eth:halt` | 6h | STAY | 0% | $0 | $0 | $0 | None | 0.4500 | - / - |
| 1M | `spot` | `usde:depeg` | 10% | EXIT | 100% | $330 | $100,000 | $0 | True | 0.0000 | 1.000% / 1.000% |
| 1M | `spot` | `lending:cascade` | 1% | STAY | 0% | $0 | $0 | $0 | None | 1.0000 | - / - |
| 7M | `spot` | `usde:depeg` | 10% | SELL_TO_CAP | 64% | $22,089 | $700,000 | $250,000 | True | 0.0000 | 1.000% / 2.080% |
| 50M | `spot` | `usde:depeg` | 10% | SELL_TO_CAP | 9% | $22,089 | $5,000,000 | $4,550,000 | True | 0.0000 | 1.000% / 1.910% |

The real-borrower rows do not depend on the size input. With a wallet: `RiskModel.atSize(window.DASHBOARD, 1e7, '0x5c430ff6f374da12218b380d2040299ae5b6d40e').position_presets.wallet_morpho` equals `lev_closest_to_liquidation` (collateral $3,249,472, debt $2,941,927); an address that was not read gives `wallet_read === false`.

What it shows: a 10% sUSDe NAV loss makes an unlevered $10M holder sell up to the pool limit (45%), while a 10% PT market fall needs no action (the PT redeems at expiry and the oracle ignores the market price). The pool takes at most $4.5M, so the size decides the answer: $1M exits in full for $330, $7M can sell 64%, $50M only 9%. The real borrower closest to liquidation ($3.25M) can sell its whole position: at a 0.5% USDe depeg (below the meta-oracle's 0.75% threshold, nobody is liquidated) the levered value loss already makes it sell 92%; at 2% the oracle switches, the position would be liquidated, and exiting now costs $5,683 against $143,833. A cascade at 20% leaves nothing sellable; at 1% a $1M holder can still sell everything.

## 10. Do not

- Do not change `dashboard.json` field names or meanings.
- Do not add loss formulas to the page; extend `web/risk_model.js` only together with the backend (and rerun `python3 check_js_port.py`).
- Do not present the prototype's sample detections as real.
- Do not reintroduce a probability input; the backend's probability-based fields are kept only for compatibility.
- Do not show a number without its source when the drawer is opened.

## 11. Refreshing the data (backend side)

```bash
RPC_URL=https://ethereum-rpc.publicnode.com python3 onchain_positions.py   # [--wallet 0xA 0xB ...]: also read these wallets
python3 crawl.py --morpho-market 0x5613b170ded221c588b6e9637b910f49e5508680ceede207f44aa72e5c46cb05 --depth 5 --tag pt_susde_market
python3 export_dashboard.py --market 0x47ad2cd1dd15739a7a035b9d3b7828d916fef77e \
  --curves data/exit_curve_0x47ad2cd1_10m.csv data/exit_curve_0x47ad2cd1_cap.csv \
  --extra-curves data/exit_curve_0x47ad2cd1_1m.csv \
  --positions data/morpho_positions_0x5613b170.json --js-out sample_data/dashboard.sample.js
python3 check_js_port.py
```
