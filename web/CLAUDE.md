# web/CLAUDE.md — front end (Risk Desk demo)

Front end for the Belem Capital track: one static page with two views. The position view (PT, the default) takes
a single position and an incident set by hand (node, failure, severity) and returns a stay / exit recommendation
with its reasoning. The vault view takes a vault address and an amount invested and does the same for a vault
deposit. A switch at the top right of the header changes view.
The backend rules are in the root `CLAUDE.md`. This file covers `web/` only.

Reply to the user in the language they write in. Code, comments, commit messages and repo docs stay in English.

Always ask for permission before commit and push.

## Files (target layout)

| File                                 | Holds                                              | Never holds                                       |
| ------------------------------------ | -------------------------------------------------- | ------------------------------------------------- |
| `demo.html`                          | Markup and element ids                             | Inline styles, numbers, sentences built in script |
| `demo.css`                           | Design tokens in `:root`, then component styles    | Anything read from data                           |
| `demo.copy.js`                       | User-facing strings, as one `COPY` object          | Logic                                             |
| `demo.js`                            | State, calls to `RiskModel`, rendering, events     | Colours, sizes, literal sentences                 |
| `vault.js`                           | The vault view: state, calls to `RiskModel.vault*` | Anything of the PT view                           |
| `risk_model.js`                      | Backend's model, both views. Read-only here        | —                                                 |
| `../sample_data/dashboard.sample.js` | PT view data (`window.DASHBOARD`). Read-only here  | —                                                 |
| `../sample_data/vaults.sample.js`    | Vault view data (`window.VAULTS`). Read-only here  | —                                                 |

No framework and no build step. The page must open from disk by double-click.

The page loads the backend's two files in place:

```html
<script src="../sample_data/dashboard.sample.js"></script>
<script src="risk_model.js"></script>
```

The vault view adds `<script src="../sample_data/vaults.sample.js"></script>` after `risk_model.js` (590 KB; the
guide's snippet shows it without the folder, use this path).

Do not copy or move the backend's files. The backend regenerates them, and a copy goes stale on the next push.
If the page is ever served over HTTP, serve from the repo root, not from `web/`, or the data path breaks.

## Separation rules

- State is expressed as classes or data attributes (`data-verdict="stay"`, `.hot`, `.origin`, `.hyp`). CSS decides
  how each state looks.
- Script may set inline values only for computed geometry: bar widths, SVG coordinates, chart points.
- Every colour comes from a token. Light and dark values are defined together. Colour means verdict state only
  (stay / reduce / exit); dashed means assumption (grade D).
- A visual change should produce a diff in `demo.css` only. If it needs more files than that, say so before
  making it.
- Wording moves to `demo.copy.js` step by step, not in one rewrite: a sentence that is new or being changed goes
  into the `COPY` object; the other sentences of a render function move when that function is next edited. Do not
  rewrite a render function only to move its strings.

## Source of truth

- `../FRONTEND_GUIDE.md` and its acceptance table decide behaviour. Re-read it after every `git pull`; it changes.
- No loss or cost formulas in the page: every number comes from `RiskModel.*`. No snapshot numbers: read
  `window.DASHBOARD`.
- No probability anywhere. The backend's probability fields are legacy; do not use them.
- Failure labels come from `failure_types.types`. Slider ranges and starting values come from the page's `FAIL`
  table for the seven failures it lists and from `failure_types.types` for any other key, such as `navLoss` and
  `discount`. A page range may be narrower than the data's, never wider (guide section 0b). A key the page does not
  know must appear as one more option, not break the page.
- Edges, including the two to the position, come from `ui.edges`. Do not add page-made edges.
- If the data lacks something, ask the user to raise it with the backend. Do not invent it.
- Never edit the Python files, `sample_data/`, `risk_model.js` or the guides from a front-end task.

## UX decisions to keep

- First screen shows only: the verdict, one comparison (do nothing vs act), and the incident path.
  Everything else opens on demand (folds, evidence drawer).
- Inputs run in thinking order, left to right: where, what and how bad. Sliders update live; no Run button.
- How long the incident lasts is set on a time rail directly above the five-layer chain, playable and draggable
  (user decision, 11 Oct; to-do 7): the control sits on the thing it drives. Step 2 only repeats the value as a
  read-only line. One duration control on the page, never two.
- One mode: any dependency can be failed by hand. Preview was removed on 10 Oct.
- No detector and no invented incidents (team decision). An incident is set by hand (node, failure, severity), or
  loaded from a past event through "Load a past incident pattern…" at the top right: the real events in
  `d.past_incidents`, grade C. No page text may describe a detector or an invented incident (gate 2b).
- Two page views, switched at the top right of the header: Position (PT), the default, and Vaults. In both views
  the header's first row holds only the title and the switch, and the view's own inputs take the second row, so the
  switch does not move when the view changes.
- Header of the PT view, left to right (to-dos 8 and 10, done): title; the position select; "Wallet (optional)";
  "Position size (USD)";
  "Cash earns after selling, % APY"; "Load a past incident pattern…"; the view switch at the far right.
  - The position select and the size input answer different questions and must not look like two size controls.
    The select says how the PT is held (labels from `position_presets[*].label`: "PT held outright", "PT as
    collateral, LTV of the Morpho market average", the two real borrowers); never put an amount in its options.
    The size input says how large the position is.
  - The size input sets the size of `spot` and `lev_market_avg` only (guide section 3b). The two real-borrower
    presets have a fixed on-chain size: the field then shows that size, read-only, grade A, never 10,000,000.
  - The input replaces the header's static "position size $10.00M" text; do not show both.
  - Size and "cash earns" are the manager's only two assumptions; there is no separate "Assumptions you can
    change" section.
- These header inputs belong to the PT view. In the Vaults view the same place shows the vault's own inputs:
  vault address, amount invested, and the vault's alternative yield (`exit.alt_apy`, default per currency from
  `VAULTS.report.assumptions.alt_apy_by_currency`). The horizon field is gone (to-do 9): the vault view's duration
  rail sets how long the incident lasts, and the yield given up is counted over it. The PT select, size,
  "cash earns" and past-incident dropdown are hidden there. Each view keeps its own values when switching.
- The page never opens on an empty decision card: the PT-reUSD oracle drop is preselected on the real borrower
  closest to liquidation (done in `b47402c`), so the first screen shows a liquidation and an exit, not a STAY. A past
  event is a pattern applied to this position, not something that happened to it: the banner and the card label must
  say so ("Pattern from …"), and the PT-reUSD event must never read as an incident on PT-sUSDe. The opening preset
  is likewise someone else's position (a real borrower of this market), not the manager's: say so on the card.
  Because it is a real-borrower preset, the size field is read-only on the first screen (to-do 8): show next to it
  that choosing "PT held outright" or the market-average preset makes the size editable.
- In both views, the dependency chain has two displays: Layers (default) and Graph. Same incident and numbers in
  both. In this file "view" means a page view (Position / Vaults); Layers and Graph are "displays".
- Plain words. One number per sentence. PT view: amounts in USD, shares as % of the position. Vault view: amounts
  in the vault's currency, written after the number. Both views write money the same short way (3.0k, 456k,
  3.00M; PT with "$"); an input field keeps the full number the manager typed.
- Every number in the drawer shows its source and its evidence grade (A to D).
- Works at phone width; the graph may scroll sideways inside its own container.

## Second view: Vaults (`../FRONTEND_VAULT_GUIDE.md`)

First cut done (`a7be800`, `7df75da`). The guide and its acceptance table (9 decision rows and a 3-row
liquidity-run table) decide behaviour.

- **Switch.** A two-option control at the top right of the header, where the Prototype / Preview switch used to
  be: "Position (PT)" (default) | "Vaults". Reuse the existing `.mode` segmented style. Switching shows one
  `<main>` and hides the other; switching back restores the PT view exactly as it was (same selection, slider
  positions, open folds, drawer closed).
- **Isolation.** The guide says not to change a single line of the PT view. Keep that at the level of behaviour:
  the vault view lives in its own `<main id="view-vault">` and its own `vault.js`, shares only `risk_model.js`
  and `demo.css`, and never reads `window.DASHBOARD` or the PT view's state. Adding the switch to the header and
  one `hidden` toggle is the only edit to PT markup. `check_demo.mjs` must print the same PT results before and
  after.
- **Inputs.** In the header (see "UX decisions to keep"). Vault address (text field plus a dropdown from
  `VAULTS.report.vaults`, matched case-insensitively; default Belem RWA EURCV) and amount invested (default 10,000,000, in the vault's asset). Then scenario
  (`details[a].incidents`, default `worst_incident`) and severity.
- **Units differ from the PT view.** Vault severities are fractions (0.8414), not percent; money is in the
  vault's currency (EURCV for Belem), not always USD, even though result fields end in `_usd`.
- **Coverage.** 33 vaults: 12 `full`, 4 `partial`, 6 `not_supported`, 11 `out_of_scope`. Only `full` ones get
  numbers; the others are listed greyed with their `note`. Incidents with `analyzed: false` are listed greyed, never
  with a loss. Go by the flag, not by a list of names: today it covers volatile crypto collateral (WBTC, wstETH,
  cbBTC, weETH) and the WETH vault's asset issuer.
- **Model.** `RiskModel.vaultDecideAt(inc, v.exit, amount, severity, altApy, null, false, hours, recovers)` (the
  duration path, guide 3 "Timeline"; at the default 30 days and "stays" it equals the static call) for the verdict (STAY /
  EXIT / EXIT_PARTIAL / REVIEW), `vaultLossAt`, `vaultRun` (liquidity run: no badge, a table), `vaultSensitivity`,
  `vaultTimeline`, `vaultTimelineSummary`. No probability: do not show `outcomes[].probability`, `expected_loss`,
  `tail_loss_95` or `break_even`.
- **Same UX rules as the PT view.** First screen: badge, the sentence (guide section 4), loss if staying versus
  cost of exiting. Dependency chain (6 layers), markets, exit tranches, sensitivity and timeline open on demand.
- **Use `vaultDecideAt` everywhere.** `vaultDecide` is the old probability-based function. The vault guide named
  it in two places; the backend fixed that in `556828c` (merged).
- **The amount default exceeds the Belem vault.** 10,000,000 is above its total assets (about 4.7M EURCV); the
  guide has a message for that case. Show the message, leave the typed number in the field, and pass
  `Math.min(amount, total_assets)` to the model, as the guide says. Label the amount "your input".

## Current state (`frontend` after to-do 8)

What is on the branch:

- `web/demo.html` (markup), `web/demo.css` (both former `<style>` blocks, in order) and `web/demo.js` (the former
  inline script), moved line for line: rebuilding the old single file from the three gives it byte for byte.
  The page loads `../sample_data/dashboard.sample.js` and `risk_model.js` in place, as shown above.
- Vault view (`web/vault.js`, `COPY.vault`): the header switch; vault address (text or list), amount invested (your
  input; above the vault's assets: message, model gets the capped amount), alternative yield; incidents grouped (not
  analysed ones greyed); severity on a log slider with historical anchors and the break-even zones; badge from
  `vaultDecideAt` on the duration path, the backend's sentence (amounts in short form), stay vs exit bars. To-do 9
  added: a duration rail over the chain (native log range 1 h to 180 days, default `exit.horizon_days`, reference
  marks at `duration_grids` switch points, none today), the recovers / stays toggle where the incident has grids for
  both (default stays), `vaultTimelineSummary` lines under it and the `vaultTimeline` chart in a fold; folds under the
  card: exit tranche by tranche (free / with penalty / locked for this amount, loss if stay / cost / kept / avoided,
  the whole vault's free and forced fractions), "What would change the answer" (`vaultSensitivity`), the vault loss
  by severity (`severity_grid` on the slider's scale, the current severity marked, each market at the anchors'
  shocks, no probability); the markets table in a fold under the chain (affected markets highlighted); the liquidity
  run's share slider (only its result redraws, so a drag keeps its element) with `run.text` for the whole vault;
  layer-6 off-chain relations in the Layers display (issuer, summary, relations by kind with source links and the
  quote's check state, as in the PT drawer). Not done: the "share of my portfolio" amount entry.
- The vault's links and incident path come from the backend: `dependency_edges` (drawn exactly, dashed when grade D,
  evidence as the label's tooltip) and `inc.chain_items` (marked in both displays; an edge is hot when both ends
  are). The page-built edges and the path matching on labels are gone.
- `RiskModel.vaultSensitivity(inc, ex, amount, sev)` takes no alternative yield, duration or recovers: it is computed
  at the vault's defaults. Off them, the fold says so under the table. To raise with the backend: give it the same
  inputs as `vaultDecideAt`.
- `web/demo.copy.js` holds the `COPY` object: so far the step-1 hint, the past-event wording, "not your position"
  and the off-chain row. The other user-facing strings are still in `demo.js` and move step by step (see
  "Separation rules").
- No detector and no invented incidents: the prototype bar, the two examples and the page-built `REPLAYS` are gone.
  "Load a past incident pattern…" lists `d.past_incidents` (4 events). Selecting one sets node, failure, severity,
  the duration and the recovers toggle (`S.past`; `p.opts` is no longer used, guide 5b); moving the dependency,
  failure or severity drops it (what-if), changing the position keeps it. Its text is in `#pastBanner` ("Pattern from …,
  applied to this position. It did not happen to PT-sUSDe."); `#banner` is only the load error. The origin layer
  and node carry a "Past pattern" tag, the card label "Pattern from …".
- First screen: `pt_reusd_aug_2026` on `lev_closest_to_liquidation` (EXIT, doing nothing loses $165k, selling
  costs $5.7k). With a real-borrower preset the card says it is "a real borrower of this market, read on chain, not
  your position". The size field then shows that borrower's on-chain size, read-only (to-do 8).
- Wallet (to-do 10, guide 3b): "Wallet (optional)" after the position select, a text field with a list
  (`<datalist>`) of `d.borrowers.wallets` (read by `onchain_positions.py --wallet`; none in today's sample) and the
  13 borrowers of this market. `d = RiskModel.atSize(window.DASHBOARD, S.size, S.wallet)`: a read wallet adds
  `wallet` (PT held) and / or `wallet_morpho` (its Morpho position) to the position select, the page selects one,
  the size field shows its on-chain size read-only, and the card says "read on chain at block …" (not "not your
  position"). Messages under the inputs: not an address; not read on chain, with the `--wallet` command to rerun;
  read but no PT-sUSDe at the block; read, with its presets (A). Clearing the field removes the presets (back to
  `spot` if one was selected). Nothing is typed in by hand. Events and flashes are keyed by the wallet too.
- Position size (to-do 8, guide 3b): "Position size (USD)" and "Cash earns after selling, % APY" sit in the header
  after the position select; the "Assumptions you can change" fold and the "share of the book" field are gone, and
  so is the stamp's static "position size $10.00M". `d` is `RiskModel.atSize(window.DASHBOARD, S.size)` (`resize()`,
  on load and on every size change; `PRE` follows it); every model call takes this `d`. The size sets `spot` and
  `lev_market_avg`; for a real borrower the field shows its on-chain size, read-only, "read on chain" (A), with a hint
  to pick a sized preset; switching back shows the typed size again. Default `size_input.default_usd`, "assumed"
  (D, source in the title) until typed, then "your input". The field keeps the text as typed ("7,000,000", "5M",
  "250k" are read); anything else restores the last size. Under the inputs: "{pt_units} PT at {pt_price_usd};
  sellable now: {share} ({capacity_usd} pool limit)" for the selected preset. The exit table's refused rows stay
  shares of the quotes' notional (`N0`, the backend file's `position.notional_usd`); the market drawer's "Largest
  sale quoted" is `size_input.capacity_usd`. Events and the timeline are cached by size too.
- "What would change the answer" is `RiskModel.sensitivity` (`778bf71`), called with the same inputs as `decideAt`,
  a past event's `opts` included: the weakest assumption that flips the verdict (or "No tested assumption changes
  the answer"), this position's own assumptions, the other positions as their own group (they never count as the
  weakest), then the severity break-even and the rule. Shown with or without a loss.
- Decision card from `RiskModel.decisionText` (`52df261`, guide section 5): its title, headline, reasons,
  break-even, hinge and rule, with a past event's `opts`. The badge, bars, stuck line and oracle-range note are built
  from the decision's numbers (wording in `COPY.card`). The amounts in the backend's sentences are written in full
  ("$164,903"), the bars in short form ("$165k"): the texts are the backend's, numbers checked there.
- Incident path from `RiskModel.propagation` (`52df261`, guide section 6): layer states and texts (`data-state` on
  each row; layers 1 and 2 included), the "Your position" row, the Graph's lit nodes and edges (steps in state
  origin / hit, `pathOf`), and the "How it spreads" fold below the chain (steps with grades, null = "your input",
  ending with the answer). The page-built `story` / `effects` / `flow` / `nodeFx` are gone. The path follows the
  duration (to-do 7, below). In the Graph display an edge lights only when its source is already on the path: the
  position step lists both its edges (holding, liquidation) even when nobody is liquidated (a USDe depeg under 16 h),
  and lighting both lit the liquidation arrow at 6 h (found by gate 2f's 6 h row).
- Time rail (to-do 7, guide 5b and 6): one panel directly above the chain, in both displays: "The incident has
  lasted {duration}", Play / Pause, the recovers toggle (only where `recoveryToggle(...).show`; otherwise its
  `reason` in small print), the log rail 1 h to 180 days (thumb `role="slider"`, pointer capture, a click on the
  track jumps there, arrows 1%, PageUp / PageDown 10%, Home / End), grey marks at the oracle switch and expiry (and
  an accent mark at a past event's own duration), one red mark per `propagationEvents` event, and the event list
  (click: thumb to `hours * 1.0005`; passed events marked). Step 2 only repeats the duration as a read-only line
  ("Lasts 6 h, recovers: drag the time rail on the chain below"). One mechanism: the card is
  `decideAtDuration(d, S.pos, S.node, S.fail, S.sev, S.hours, S.recovers, S.alt / 100)`; `breakEvenSeverity`,
  `sensitivity`, `decisionText` and `propagation` get its inputs (`durInputs`) and `r.carry`. Events and the
  timeline are cached by position, node, failure, severity, recovers and cash APY, never computed on drag; a drag
  renders once per animation frame. A layer whose state changes flashes about 1 s (outline with reduced motion),
  only while the incident stays the same. Play sweeps in about 9 s, pauses 1.4 s just past each event, stops at
  180 days; any other input stops it. `S.hours` / `S.recovers` belong to the PT view (kept across a Vaults switch).
  Default duration `DEF_H` = 6 h (the guide names none; the explainer opens at 6 h): a manual incident keeps the
  rail where it is; a past event sets `p.hours` and `p.recovers`, or 6 h and stays when `hours` is null (Stream
  xUSD, Elixir deUSD). Moving the rail or the toggle keeps a past event selected; moving dependency, failure or
  severity drops it (what-if), as before.
- Timeline chart (to-do 7, second part): a fold under the rail ("Loss if staying, by how long the incident lasts"),
  on the rail's axis: `RiskModel.timeline` points, background by answer between the events' exact durations, grey
  marks at 16 h and expiry, the rail's duration as a line, `timelineSummary` lines above it, the held-constant
  assumptions (D) below. A picture, not a control.
- Off-chain dependencies (guide section 8): the `ethena` and `susde` drawers have an "Off-chain (issuer documents)"
  row from `d.offchain.USDe` (31 relations) and `d.offchain.sUSDe` (4): issuer, summary and count per kind,
  relations grouped by kind on demand, each with a source link, grade D and the quote ("re-checked" when
  `evidence.quote_found` is true; the one USDe quote with `quote_found: null` (Ceffu's page blocks the checker, HTTP 403) is "not re-checked", which is not the same as not found). The `usde` drawer shows the summary and a link to
  Ethena's relations. Off-chain ids are no longer in "Contracts behind it"; the Ethena card reads its count from the
  data.
- Still against the separation rules: three SVG legend swatches in `demo.js` (`renderExit`) carry inline colour
  styles that are not geometry.
- Step 3 and every probability input are gone: the verdict comes from `RiskModel.decideAt`, the step-2 zones and
  "selling starts at / pool limit from" from `breakEvenSeverity`. Wide % sliders use a log scale shared with the
  zone bar.
- Edges come from `ui.edges` only (data id `position` drawn as the page's `pos`).
- Carry is `r.carry` from `decideAtDuration` (yield given up over the incident only, at most until expiry; the
  model converts `S.alt / 100` itself); the "cash earns" field is a text field (`inputmode="decimal"`) that accepts
  "4,5" as well as "4.5". Before to-do 7 it was `RiskModel.carryOf(d, S.alt / 100)` until expiry.
  Keep that field: it is the manager's assumption (grade D, e.g. 4% for USD). `carry` is the yield given up until
  expiry as a fraction of the value sold (today (5.01% - 4%) x 46.3 / 365 = 0.128%), never an annual rate, and 0
  when cash earns more than the PT. Pass it unscaled to `decideAt`, `breakEvenSeverity` and `sensitivity`: the
  model scales it by value / equity for levered positions. The guide's acceptance tables use carry 0.
- The exit panel, chart, sale table, tooltip and layer-4 fact use the selected preset's own curve,
  `RiskModel.sizeCurve(d, P.collateral_usd)`; "Today" is the model's `sellable_now`. The two real borrowers can
  sell 100% today, so their chart has no "Pendle refuses" band.
- `main` was merged at `556828c` (in `5cda215`); the `9fd615e` merge before it brought `d.offchain` (off-chain
  dependencies of USDe and sUSDe), `RiskModel.decisionText` and `RiskModel.sizeCurve`. The backend pushes often, so
  run
  `git log HEAD..origin/main --oneline` before starting and merge first.
- `main` was merged again at `48e5ab9` (in `74993e8`: `d.past_incidents`, the optional `opts` argument) and at
  `f1a44c5` (in `642e57b`: guide 3c, the first-screen rule, docs only).

Check status (after to-do 10): `node web/check_demo.mjs` passes, 40 gates, nothing skipped (gate 8 also covers the
wallet: list, a borrower's address read at its on-chain size (guide 9's 3,249,472 / 2,941,927) and selected, the card
equal to the model, unread / invalid / cleared; the "read, no PT" message is not covered: the sample has no read
wallet; 6f against
`dependency_edges` / `chain_items`; new 6g: 82 incident x duration cases for the vault details, 4 off-chain items,
the run slider) (one NOTE: guide 3c's
oracle / liquidated columns are not compared for the two events without a stated duration); `python3
check_js_port.py` 30/30. What each gate covers is in its comment in `check_demo.mjs`; the history is in `git log`.
Not checked: dragging the rail with a real mouse by eye (only CDP mouse events), layout by eye in dark mode beyond the
screenshots taken.

Lessons worth keeping:

- A second tab in front throttles the first one's timers and animation frames: Play (gate 7) then never ends. A
  gate on a fresh page runs after the rail gates and closes its tab; every page step fails after 90 s instead of
  hanging.
- A phone check needs device emulation (`check_demo.mjs` does it); a plain `--window-size=390` screenshot crops
  the page and proves nothing.
- Before to-do 7 the page's numbers came from `decideAt` with a past event's `opts`; now from `decideAtDuration`,
  so the guide's tables (computed with `decideAt`) match the screen within 0.1%, the model exactly.

Gaps, most visible first: none from the guides' lists; see the small leftovers under the to-do.

Answered by the backend (guide section 0b, merged):

- Slider ranges: `min` / `max` in `failure_types.types` are the range the model covers. The page may narrow a
  range (depeg 1–60 is fine) but must not widen it. Cascade is now 1–40 in the data. The starting value is the
  page's choice. Pass the page's slider range to `breakEvenSeverity`.
- Exit curve per position: `RiskModel.sizeCurve(d, P.collateral_usd)`. `decideAt` and `inject` already use it.
  `d.exit_curve` and `d.max_exit_fraction` belong to the size input's position only and must not be used for the
  real-borrower or wallet presets. Applied in `098d44c`.
- New on `main`: `RiskModel.decisionText(...)` returns the headline, reasons, break-even and the assumption the
  answer hinges on, in the backend's wording (guide section 0, priority 4).
- Past events (`48e5ab9`, guide 3c, section 0 step 5): `d.past_incidents` replaces the page-built list; `decideAt`,
  `breakEvenSeverity`, `sensitivity` and `decisionText` take an optional last argument `opts` (the event's duration
  and recovery). Existing calls are unchanged. Merged in `74993e8`; the 8 acceptance rows of guide 3c were
  reproduced with the model on that data (size 10M, carry 0).
- Recovers toggle (`281b27d`, guide 5b, merged in `b8fb353`): `RiskModel.recoveryToggle(d, node, fail)` returns
  `{show, reason}`; the toggle exists only for failures with an off-chain cause (to-do 7).

This file loads when a file in `web/` is opened; otherwise read it at the start of the session.

## To-do, in order

Done: `main` merged (repeat after every backend push, then `python3 check_js_port.py`); page moved to
`web/demo.html`; position edges from the data; probability removed, verdict from `decideAt`, zones from
`breakEvenSeverity`; split into `demo.html`, `demo.css`, `demo.js`; `check_demo.mjs` written; `main` merged at
`9fd615e` (`a4d9f9e`); carry from `RiskModel.carryOf`, decimal comma accepted (`8baf37b`); exit panel from each
position's own curve, with gate 4b in `check_demo.mjs` (`8291329`, `098d44c`); `main` merged at `556828c`
(`5cda215`); no detector wording and off-chain row in the evidence drawer, with gates 2b / 2c (`a726d90`,
`7aa2500`); `main` merged at `48e5ab9` (`74993e8`) and `f1a44c5` (`642e57b`); off-chain quotes "not re-checked"
when `quote_found` is null (`0c71c3f`); past incidents replace the invented examples, first screen on PT-reUSD
with the closest borrower, gates 1b / 2b / 2d / 2e (`b47402c`); vault view first cut with the header switch and
gates 6a-6e (`a7be800`); vault Graph display, gate 6f (`7df75da`); "What would change the answer" from
`RiskModel.sensitivity`, gate 3b (`778bf71`); decision card from `decisionText` and incident path from
`propagation`, gates 2f / 2g (`52df261`); time rail with events, recovers toggle, Play and flash, the timeline
chart in a fold, gates 7 / 7b (to-do 7: `e8ef479`, `5e436b9`); position size and cash yield in the header through
`atSize`, gate 8, all guide 9 sizes (to-do 8: `d215b5c`); vault view rest: links and path from the backend, details
folds, duration rail and timeline, run slider, layer-6 off-chain relations, gates 6f / 6g (to-do 9: `29af9c6`); the
PT wallet input through `atSize(..., wallet)`, gate 8 (to-do 10).

Item numbers are kept from earlier versions so references stay valid: 1, 2, the old 3 (detector wording), 3b,
the new 3 (past incidents), 4 (vault view, first cut), 5 (sensitivity), 6 (decisionText), 6b (propagation) and 7
(time rail, timeline chart), 8 (position size), 9 (vault view rest) and 10 (wallet) are done.

No numbered item left (6 to 10 done). Small leftovers: the vault "share of my portfolio" amount entry; the three
inline swatch styles.

To raise with the backend: `propagation`'s `position` step lists the `lending -> position` (liquidation) edge even
when the position is not liquidated; the page filters it (see "Current state"), the data could drop it.

7. Done (kept for reference). PT view time rail (duration), recovers / stays toggle and the timeline chart (`decideAtDuration`, `timeline`,
   `timelineSummary`; guide section 5b). Decided by the backend: from this step on there is one mechanism, the
   duration controls.
   - The card uses `decideAtDuration(d, S.pos, S.node, S.fail, S.sev, S.hours, S.recovers, S.alt / 100)`, not
     `decideAt`. `decideAtDuration` and `timeline` take `altApy = S.alt / 100` (an annual rate, not `carry`) and
     compute the carry themselves over the incident's duration, capped at expiry; `null` means cash earns the same
     as the PT.
   - A past event only presets the controls: node, failure, severity, the duration slider (`p.hours`) and the
     recovers toggle (`p.recovers`); events with `hours: null` (Stream xUSD, Elixir deUSD) leave the duration at its
     default and recovers off. `p.opts` is no longer passed.
   - `breakEvenSeverity`, `sensitivity`, `decisionText` and `propagation` have no duration version. Pass them the
     inputs `decideAtDuration` used, and its carry, so that all five agree:
     ```js
     const r = RiskModel.decideAtDuration(
       d,
       S.pos,
       S.node,
       S.fail,
       S.sev,
       S.hours,
       S.recovers,
       S.alt / 100,
     );
     const o = {
       hours: S.hours,
       collateral_usd: r.position_value_usd,
       collateral_oracle_usd: r.collateral_usd,
       debt_usd: r.debt_usd,
       sale_value_usd: d.position_presets[S.pos].collateral_usd,
     };
     if (S.recovers) o.permanent = 0;
     // breakEvenSeverity(d, S.pos, S.node, S.fail, r.carry, lo, hi, 400, o); sensitivity(..., r.carry, o);
     // decisionText(d, S.pos, S.node, S.fail, S.sev, r.carry, o); propagation(d, S.pos, S.node, S.fail, S.sev, r.carry, o)
     ```
     The carry here is `r.carry` (yield given up over the incident only), not `carryOf` until expiry. Numbers move
     slightly (first screen $164,900 instead of $164,903); merge `main` and re-read the acceptance rows first.
   - **Time rail: the duration control is a playable, draggable rail on the five-layer chain** (backend's
     suggestion, approved by the user on 11 Oct, with the three choices below). Reference: the backend's explainer page, section "五层传导：事故怎么一层层传到头寸"
     (a standalone `index.html` shared with the user, not in this repo; ask for it). Copy its behaviour, listed
     below, not its looks or texts: it has its own fonts and colour tokens, Chinese wording and page-made labels
     and notes. Here the style comes from `demo.css` tokens and every string from `COPY`.
     - Where: one panel directly above the chain, so the control sits on the thing it drives: "The incident has
       lasted {duration}", a Play / Pause button, the recovers toggle ("the shock is gone after the incident"; see the next
       point), the rail, the event list. Step 2 keeps the order "what, how bad, how long" with a read-only line ("lasts
       6 h, recovers: drag the time rail below") instead of a second slider. Guide 5b puts the slider in step 2;
       the user chose the explainer's placement. There is one duration control on the page, never two.
     - Recovers toggle: shown only when `RiskModel.recoveryToggle(d, S.node, S.fail).show` is true (backend
       `281b27d`, guide 5b): today `usde:depeg`, `ethena:shortfall` and `susde:navLoss`, the failures with an
       off-chain cause, where recovery is the manager's assumption (grade D). For every other failure hide the
       toggle and show the returned `reason` in small print in its place (`pt:depeg`: "Recovers by contract: the PT
       redeems at expiry, whatever its market price before."). The reason text comes from the model, not from
       `COPY`. Keep passing `S.recovers` unchanged everywhere: where the toggle is hidden it changes nothing. A past
       event still sets `S.recovers` from `p.recovers`; the first-screen event (`oracle:oracleLow`) therefore shows
       the reason, not the toggle.
     - Scale: log, 1 h to 180 days (4,320 h): `hours = 1 * exp(ln(4320) * u)`, `u` in 0..1. Axis labels at 1 h,
       6 h, 1 d, 7 d, 30 d, 90 d, 180 d; durations under 48 h read in hours, longer ones in days.
     - Marks: grey reference marks with a label at the oracle switch (`d.oracle.challenge_timelock_s / 3600`, 16 h)
       and at expiry (`d.time_model.days_to_expiry * 24`); one red mark per entry of `ev.events`.
     - Dragging: a track with a thumb (`role="slider"`, `aria-valuemin` / `max` / `now`, `aria-valuetext` = the
       formatted duration); pointer events with pointer capture and `touch-action: none`; a click on the track
       jumps there; keys: arrows 1% of the rail, PageUp / PageDown 10%. A native `<input type="range">` is fine if
       the marks can be laid over it. Position is the only inline style (computed geometry).
     - On every drag step recompute `decideAtDuration`, then with the same `r.carry` and `o`: the card, the zones,
       `propagation` (layers, "How it spreads", Graph display) and the decision text. If a frame gets slow, limit
       updates to one per animation frame and refresh the fold contents (sensitivity, exit panel) on release.
     - Events: `RiskModel.propagationEvents(d, S.pos, S.node, S.fail, S.sev, S.recovers, S.alt / 100)` (on `main`
       since `97d9450`). It runs the model about 300 times (about 50 ms here): cache it by position, node, failure,
       severity, cash APY and recovers, and never call it on drag. List the events under the rail: the duration,
       then per changed step "layer {n}: {from} -> {to}: {text}", and the verdict change with both badges. Events
       already passed are marked. A click on an event moves the thumb just past it (`hours * 1.0005`). With no
       events: "Between 1 hour and 180 days the path does not change with the duration" (never "always stay").
     - Flash: when a render changes a layer's state, that layer flashes (about 1 s, twice); with
       `prefers-reduced-motion` an outline instead of the animation.
     - Play: sweeps the rail in about 9 s, pauses about 1.4 s just past each event, stops at the end; pressing it
       at the end restarts from 1 h; any drag, key, event click or other input stops it; the label toggles
       Play / Pause. Play is part of this step, not optional: it is how the demo shows the incident spreading.
     - State: `S.hours` and `S.recovers` belong to the PT view and survive a switch to Vaults and back. A past
       event sets them (the first screen opens at 1 h, the left end); the default for a manual incident is the
       guide's (ask the backend if it names none; the explainer opens at 6 h).
   - The demo's main point (guide section 6): the same 3% USDe depeg on the closest borrower stops at layer 4 for
     6 h and reaches layers 3 and 5 after the oracle's 16 h switch, verdict STAY -> EXIT. Checked on the branch's
     data: one event at 16 h, STAY -> EXIT. The explainer's `risk_model.js` and data are byte-identical to the
     branch's at `50d2c16`, so its numbers are the page's numbers.
   - Do the rail and its events first, then the timeline chart (`timeline`, `timelineSummary`, guide 5b) as a
     second commit: the chart shares the rail's log axis and sits in a fold, it is not a second control.
   - `check_demo.mjs`: the card, the zones, the sensitivity table, the decision text and the path use the same
     loss for every preset and past event; the rail shows one red mark per `ev.events` entry and the two grey
     reference marks; keyboard arrows move the thumb; a click on an event moves the thumb past it and changes the
     layer states it names; Play reaches the end and stops; no second duration control exists; the recovers
     toggle is present exactly for the failures where `recoveryToggle(...).show` is true and the reason text is
     shown for the others; the two examples of
     guide section 6 (16 h; 4,190.4 h for `susde:discount` 0.5%).
8. Done (kept for reference). Position size input in the header through `RiskModel.atSize` (default `size_input.default_usd`, marked D until
   typed). It replaces "share of the book", which is then removed: the manager types US dollars directly
   ("Position size (USD)"). In the same change, move "Cash earns after selling, % APY" into the header next to it
   (same field, same state `S.alt`, same decimal-comma parsing, grade D mark) and remove the "Assumptions you can
   change" section, which is then empty. With a real-borrower preset the size field shows the on-chain size and is
   read-only (details in "UX decisions to keep"). Under the inputs show the guide's line: "{pt_units} PT at
   {pt_price_usd}; sellable now: {max_exit_fraction} ({capacity_usd} pool limit)". Update the selectors in
   `check_demo.mjs` in the same commit. Then the 1M / 7M / 50M acceptance rows must pass instead of being skipped.
9. Done. Vault view, rest: markets, exit tranches, sensitivity, liquidity-run slider and table, off-chain relations of
   layer 6, timeline.
10. Done. PT wallet input (guide section 3b: an address read on chain, never typed-in collateral or debt).

Alongside, when the code is touched anyway: the three inline swatch styles; strings into `COPY`.

Update the state, gaps and to-do when an item is done or the backend answers.

## How to work

- One concern per change: a fix, the split, a guide update and a visual tweak are separate commits.
- Do not run a formatter over existing files. The three files as split in `9d63d93` are the baseline.
- Show a per-file summary of the diff before committing. Commit and push only when the user asks. Push after each
  verified commit, once the user approves; do not let work sit on one machine.
- Branch: `frontend`. Merge `main` in before starting (not rebase: the branch is pushed), since the backend moves
  fast.

## How to verify

Checking against the data files is not enough; the drawer crash was missed that way. `node web/check_demo.mjs`
opens the page in the installed Chrome (DevTools protocol, no packages, no server; `CHROME=` to override), drives
its own controls and prints one `GATE PASS` / `GATE FAIL` line per check, exit 1 on any failure, console error or a
step hanging over 90 s. It reads the acceptance tables from `../FRONTEND_GUIDE.md` and `../FRONTEND_VAULT_GUIDE.md`
at run time. It covers: load without errors, every node's drawer in both displays, every preset x failure, the
guides' tables on screen, card / zones / path / sensitivity / exit panel against the model, the time rail, the
header inputs, the vault view, phone width and dark mode.

When to run what:

1. While working: `node web/check_demo.mjs --quick` (about 15 s: the big sweeps sampled, Play not swept). Run it
   once when a step is done, not after every edit.
2. Before each commit: `node web/check_demo.mjs` once (about 35 s). After merging `main`, also
   `python3 check_js_port.py` (30 gates).
3. Only for a refactor or a new gate: run the old page too (`git archive HEAD web` into the scratchpad with a
   `sample_data` symlink, then `node web/check_demo.mjs <old>/web/demo.html`) to show the gate catches the old
   behaviour.
4. Screenshots only for a visible change: desktop, 390px (device emulation) and dark mode of the part that changed;
   not for logic-only changes.
5. A new feature gets its gate in the same commit; keep each gate's description in its comment, not here.

It does not judge layout by eye, and its cross-checks are pairs (e.g. exit panel against card): a full pass is not
proof the page is consistent. State plainly what was checked and what was not, in the reply and in one line of
"Check status" above (replace it, do not append a history).
