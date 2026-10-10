# Risk Desk v2: connecting the front end to the backend

> 给前端同事：把这份文件和 `Dependency_Risk_Desk_v2.html` 一起交给 Claude，说"按 FRONTEND_GUIDE.md 修改这个页面"。
> 布局和交互保持不变：第 1 步选节点（固定 9 个节点 + 检测到的事故），第 2 步手动拖严重程度，第 3 步经理设概率。
> 改的是：数据从后端文件读取，损失从后端的模型计算，并删掉已经过时的文字。

Instructions for Claude. Edit `Dependency_Risk_Desk_v2.html` so that it reads the backend's data and computes every number with the backend's model. Keep the layout, the three steps, the five-layer chain, the decision card, the exit panel, the drawer and the prototype controls.

## 1. Files

From the repo (`git pull`):

| File | Use |
|---|---|
| `sample_data/dashboard.sample.js` | The data as `window.DASHBOARD = {...};`. Load it with a `<script>` tag (works when the page is opened from disk) |
| `sample_data/dashboard.sample.json` | Same data as JSON, if the page is served over HTTP (`fetch`) |
| `web/risk_model.js` | The model: `RiskModel.inject`, `positionLoss`, `oracleFalls`, `decide`, `breakEven`, `slippageAt`, `lif`. Checked equal to the Python backend (`python3 check_js_port.py`) |
| `README.md`, section "Frontend integration" | Field-by-field contract of `dashboard.json` |

Copy `sample_data/dashboard.sample.js` and `web/risk_model.js` next to the HTML file (or adjust the paths), and put the two scripts before the page's own script:

```html
<script src="dashboard.sample.js"></script>
<script src="risk_model.js"></script>
```

## 2. Rules

1. Do not hard-code numbers from the old snapshot. Read everything from `const d = window.DASHBOARD;`.
2. Do not compute losses in page code. Delete the `loss` functions of `FAIL`, `valueDrop` and the local `LIF` / `LIQ_DIST` formulas; call `RiskModel.inject(d, presetKey, node, fail, sev)` instead.
3. Step 1 offers exactly the 9 nodes of `d.ui.nodes` (grouped by `d.ui.layers`), plus the detected incidents (`d.detected`, empty today; keep the prototype sample feed, still labelled as invented).
4. Step 2 stays a manual slider: keep each failure's `label`, `unit`, `min`, `max` and starting value from the page's `FAIL` table (the same keys exist in `d.failure_types.types`). Add two entries for sUSDe, taking `label`, `unit`, `min`, `max`, `default_severity` from `d.failure_types.types.navLoss` and `.discount` ("NAV falls (USDe per sUSDe)", "Trades below its NAV"). USDe and sUSDe are different assets: 1 sUSDe is worth about 1.25 USDe, so "depeg" (falling below $1) applies to USDe only.
5. Step 3 stays the manager's probability. Start it at `d.failure_types.types[fail].probabilities.p_severe` when that is not null, with the note "historical default (C): " + `evidence.source`. When it is null, keep the page's sample value and its "not calibrated" note.
6. Show evidence grades: A = read from chain / API, B = contract rule back-tested, C = analogy from history, D = assumption. Dashed style = D.
7. Keep the field names of `dashboard.json`. If something is missing, ask the backend (do not invent it).

## 3. Replace the constants

| Page constant | Replace with |
|---|---|
| `D` (snapshot) | `d = window.DASHBOARD` |
| `N`, `CURVE`, `MAXX` | `d.position.notional_usd`, `d.exit_curve.map(x => [x.fraction, x.loss])`, `d.max_exit_fraction` |
| `LD` | `d.lending[0]` (`lltv`, `collateral_usd`, `borrow_usd`, `liquidity_usd`, `aggregate_ltv`, `oracle_address`; `market_id` is now the full id) |
| `NODES` | `d.ui.nodes`: same 9 keys (`eth`, `ethena`, `usde`, `susde`, `feeds`, `oracle`, `market`, `pt`, `lending`) with `label`, `kind`, `layer`, `address`, `contract_name`, `members` (ids in `d.dependency_graph.nodes`), `evidence {grade, source}`, `note`, `failures` |
| `LAY` | `d.ui.layers` (`n`, `name`, `nodes`); facts per layer: see section 6 |
| `EDGES` | `d.ui.edges` (`from`, `to`, `type`, `grade`, `evidence`) |
| `FBN` | `d.ui.nodes[k].failures` (sUSDe now has `navLoss` and `discount` instead of `depeg`) |
| `POS` | `d.position_presets`: `spot`, `lev_market_avg`, `lev_largest_borrower`, `lev_closest_to_liquidation` (`label`, `collateral_usd`, `debt_usd`, `lltv`, `ltv`, `evidence`). Fill the header position `<select>` from it |
| `FAIL[k].loss` | delete; `RiskModel.inject` |
| `FAIL[k].prob` | `d.failure_types.types[k].probabilities.p_severe` when not null |
| `stress()` | the `sellable_later` / `avg_cost_later` returned by `inject` (drain keeps its own curve, section 7) |
| `DETECTED` | `d.detected` when it is not empty; otherwise the prototype sample list (keep it labelled as invented) |
| `REPLAYS` | oracle: node `oracle`, failure `oracleLow`, severity 2.77 (`d.failure_types.types.oracleLow.anchors[0]`), and show `d.validation` ("back-test of the liquidation rules on PT-reUSD: 9/9 checks pass"); issuer: node `ethena`, failure `shortfall`, severity 50 (Stream xUSD) or 99.87 (Elixir deUSD) from `anchors` |

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

Rewrite `model()` around it:

```js
const d = window.DASHBOARD;
function model() {
  const P = d.position_presets[S.pos], equity = P.collateral_usd - P.debt_usd;
  const pr = d.failure_types.types[S.fail].probabilities || {};
  const share = pr.partial_severity_share ?? S.ps / 100;   // partial case severity, share of the severe one
  const ratio = pr.partial_to_severe_prob ?? S.pk;          // partial case probability, multiple of the severe one
  const sev = RiskModel.inject(d, S.pos, S.node, S.fail, S.sev);
  const par = RiskModel.inject(d, S.pos, S.node, S.fail, S.sev * share);
  const pS = S.p, pP = Math.min(ratio * pS, 1 - pS), p0 = Math.max(0, 1 - pS - pP);
  const el = pS * sev.L_high + pP * par.L_high;             // expected loss, fraction of equity
  const scale = P.collateral_usd / equity;                  // exit cost per unit of equity
  const curve = d.exit_curve.map(x => [x.fraction, x.loss * scale]);
  const dec = RiskModel.decide(1, el, curve, carry());      // same call shape as today
  const be = RiskModel.breakEven(d.exit_curve.map(x => [x.fraction, x.loss]), sev.L_high, scale, carry());
  return {P, equity, sev, par, pS, pP, p0, el, dec, be};
}
```

- Money: loss in USD = `L x equity`; sale cost in USD = `x x slippage x collateral`.
- The probability zones on the slider: `be.p_start` (start selling), `be.p_exit_sellable` (brief's "exit cost / loss": exiting the sellable part pays), `be.p_sell_to_cap` (sell all that can be sold). Exact values, no grid. They use the severe case alone; with the partial case included the page's existing scan over the slider stays valid.
- Keep `carry()` (implied APY minus the "cash earns" assumption).

## 5. Decision card

- Verdict and bars as today, from `dec`.
- Under the verdict, one line from `sev.note`, and: oracle follows = `sev.oracle_falls`, liquidated = `sev.liquidated`.
- If `sev.L_low !== sev.L_high`: "loss between L_low and L_high depending on the oracle; the decision uses the high end".
- "What would change the answer": keep the probability and severity rows; add "position preset" (try the other presets: the closest-to-liquidation borrower flips most answers).

## 6. Five-layer chain

Layer facts (replace the old texts, numbers from the data):

| Layer | Head | Fact |
|---|---|---|
| 1 | `d.ui.nodes.eth.label` | "Every contract below settles here" |
| 2 | "sUSDe, backed by USDe and Ethena" | "The PT redeems to sUSDe at expiry"; USDe and sUSDe are read on chain (grade A) |
| 3 | `d.ui.nodes.oracle.contract_name` | `d.ui.nodes.oracle.note` (linear discount, 0.75% / 16 h switch, deviation now) |
| 4 | `d.ui.nodes.market.label` | "You can sell `max_exit_fraction x notional` today" |
| 5 | `d.ui.nodes.lending.label` | "`d.borrowers.distribution.n_borrowers` borrowers; Morpho liquidations would exceed the pool from a `d.borrowers.first_drop_seized_exceeds_capacity` oracle drop" |

Effects shown on the red path, from the `inject` result of the severe case:

- origin layer: the failure and severity, e.g. "USDe down 2%".
- layer 3: `oracle_falls === true` -> "Oracle follows (after the 16 h switch)" for `usde` / `ethena`, "Oracle reports the low price" for `oracleLow`; `false` -> "Oracle does not move (linear discount, no market input)".
- layer 4: `sellable_later < sellable_now` -> "Sellable falls from X to Y".
- layer 5: `liquidated` contains true -> "Your position is liquidated"; levered and false -> "Not liquidated".
- your position: `loss_usd`.

Remove these old texts, the backend now contradicts them: "Type unknown", "Upstream feeds are not resolved yet", "Not resolved. Needs the on-chain crawler", "Not verified. Planned: on-chain read from the sUSDe contract", "Starting probabilities are samples, not calibrated from history" (keep it only for failures whose `p_severe` is null).

## 7. Exit panel

- Today: `max_exit_fraction`, cost `slippageAt(max_exit_fraction)`; optional gas per size in `d.exit_curve[i].gas_usd`.
- If this plays out: `sev.sellable_later` and `sev.avg_cost_later` (null -> "No room left"). For `lending:cascade` and for failures where the oracle follows, these come from the real liquidation curve (`d.borrowers.exit_later`), replacing the "pool liquidity leaves" assumption.
- Dashed curve: only for `market:drain` (the page's existing `stressCurve(sev / 100)`).
- The refused row: `d.evidence.max_exit_fraction.source` names the refused sizes.

## 8. Evidence drawer

For a node `k`: `d.ui.nodes[k]` (`kind`, `layer`, `address` with the Etherscan link, `contract_name`, `evidence`, `note`), its `members` looked up in `d.dependency_graph.nodes` (label, contract name, address, grade), and the edges of `d.ui.edges` touching `k` with their `evidence`. For `oracle`, add the oracle tree `d.oracle` (primary, backup, threshold, timelock, deviation now). For `feeds`, the count of Chainlink transmitters is in the note.

## 9. Acceptance tests

After the change, these inputs must give these numbers (from `RiskModel.inject`; check in the browser console with `RiskModel.inject(window.DASHBOARD, preset, node, fail, sev)` and on screen):

| Position preset | Node · failure | Severity | L_low - L_high (of equity) | Loss USD | Oracle falls | Liquidated | Sellable later | Avg cost later |
|---|---|---|---|---|---|---|---|---|
| `spot` | `susde:navLoss` | 10% | 0.1000 - 0.1000 | $1,000,000 | False | [False] | 0.4500 | 0.491% |
| `spot` | `susde:discount` | 3% | 0.0000 - 0.0000 | $0 | False | [False] | 0.4500 | 0.491% |
| `spot` | `pt:depeg` | 10% | 0.0000 - 0.0000 | $0 | False | [False] | 0.4500 | 0.491% |
| `spot` | `usde:depeg` | 10% | 0.1000 - 0.1000 | $1,000,000 | True | [False] | 0.0000 | - |
| `lev_closest_to_liquidation` | `usde:depeg` | 0.5% | 0.0531 - 0.0531 | $50,000 | False | [False] | 0.4500 | 0.491% |
| `lev_closest_to_liquidation` | `usde:depeg` | 2% | 0.4646 - 0.4646 | $437,054 | True | [True] | 0.1418 | 1.232% |
| `lev_closest_to_liquidation` | `susde:navLoss` | 2% | 0.2126 - 0.2126 | $200,000 | False | [False] | 0.4500 | 0.491% |
| `lev_closest_to_liquidation` | `susde:discount` | 2% | 0.0000 - 0.0000 | $0 | False | [False] | 0.4500 | 0.491% |
| `lev_closest_to_liquidation` | `pt:depeg` | 10% | 0.0000 - 0.0000 | $0 | False | [False] | 0.4500 | 0.491% |
| `lev_closest_to_liquidation` | `oracle:oracleLow` | 2.77% | 0.5335 - 0.5335 | $501,897 | True | [True] | 0.1264 | 1.305% |
| `lev_market_avg` | `ethena:shortfall` | 50% | 1.0000 - 1.0000 | $1,179,163 | True | [True] | 0.0000 | - |
| `spot` | `market:drain` | 60% | 0.0000 - 0.0000 | $0 | None | None | 0.1800 | 0.491% |
| `spot` | `lending:cascade` | 1% | 0.0000 - 0.0000 | $0 | None | None | 0.1449 | 1.219% |
| `spot` | `lending:cascade` | 6% | 0.0000 - 0.0000 | $0 | None | None | 0.0000 | - |
| `lev_market_avg` | `eth:halt` | 6h | 0.0000 - 0.0000 | $0 | None | None | 0.4500 | 0.491% |

What the table shows (good demo points): the same 2% fall liquidates the closest borrower if it is USDe against USD (the oracle follows after its 16 h switch) but not if it is sUSDe's NAV (no feed sees it: the loss is real but nobody is liquidated) or a sUSDe market discount (no loss if held to expiry); a 10% PT price fall costs nothing because the oracle ignores the PT market price and the PT redeems at expiry; when other borrowers are liquidated at a 1% oracle drop, only 14.5% of the position can still be sold.

## 10. Do not

- Do not change `dashboard.json` field names or meanings.
- Do not add loss formulas to the page; extend `web/risk_model.js` only together with the backend (and rerun `python3 check_js_port.py`).
- Do not present the prototype's sample detections as real.
- Do not show a number without its source when the drawer is opened.

## 11. Refreshing the data (backend side)

```bash
RPC_URL=https://ethereum-rpc.publicnode.com python3 onchain_positions.py
python3 crawl.py --morpho-market 0x5613b170ded221c588b6e9637b910f49e5508680ceede207f44aa72e5c46cb05 --depth 5 --tag pt_susde_market
python3 export_dashboard.py --market 0x47ad2cd1dd15739a7a035b9d3b7828d916fef77e \
  --curves data/exit_curve_0x47ad2cd1_10m.csv data/exit_curve_0x47ad2cd1_cap.csv \
  --positions data/morpho_positions_0x5613b170.json --js-out sample_data/dashboard.sample.js
python3 check_js_port.py
```
