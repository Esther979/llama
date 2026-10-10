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
| `vault.js` (not created yet)         | The vault view: state, calls to `RiskModel.vault*` | Anything of the PT view                           |
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
- One mode: any dependency can be failed by hand. Preview was removed on 10 Oct.
- No detector and no invented incidents (team decision). An incident is set by hand (node, failure, severity), or
  loaded from a past event through "Load a past incident pattern…" at the top right: the real events in
  `d.past_incidents`, grade C. No page text may describe a detector or an invented incident (gate 2b).
- Two page views, switched at the top right of the header: Position (PT), the default, and Vaults.
- Header of the PT view, left to right, once to-do 7 is done: title; the position select; "Position size (USD)";
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
  `VAULTS.report.assumptions.alt_apy_by_currency`) with the horizon (`exit.horizon_days`). The PT select, size,
  "cash earns" and past-incident dropdown are hidden there. Each view keeps its own values when switching.
- The page never opens on an empty decision card: the PT-reUSD oracle drop is preselected on the real borrower
  closest to liquidation (done in `b47402c`), so the first screen shows a liquidation and an exit, not a STAY. A past
  event is a pattern applied to this position, not something that happened to it: the banner and the card label must
  say so ("Pattern from …"), and the PT-reUSD event must never read as an incident on PT-sUSDe. The opening preset
  is likewise someone else's position (a real borrower of this market), not the manager's: say so on the card.
  Because it is a real-borrower preset, the size field is read-only on the first screen (to-do 7): show next to it
  that choosing "PT held outright" or the market-average preset makes the size editable.
- In the PT view, the dependency chain has two displays: Layers (default) and Graph. Same incident and numbers in
  both. In this file "view" means a page view (Position / Vaults); Layers and Graph are "displays".
- Plain words. One number per sentence. PT view: amounts in USD, shares as % of the position. Vault view: amounts
  in the vault's currency.
- Every number in the drawer shows its source and its evidence grade (A to D).
- Works at phone width; the graph may scroll sideways inside its own container.

## Second view: Vaults (`../FRONTEND_VAULT_GUIDE.md`)

Not started. The guide and its acceptance table (9 decision rows and a 3-row liquidity-run table) decide behaviour.

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
- **Model.** `RiskModel.vaultDecideAt(inc, v.exit, amount, severity, altApy, horizonDays)` for the verdict (STAY /
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

## Current state (`frontend` at `b47402c`)

What is on the branch:

- `web/demo.html` (markup), `web/demo.css` (both former `<style>` blocks, in order) and `web/demo.js` (the former
  inline script), moved line for line: rebuilding the old single file from the three gives it byte for byte.
  The page loads `../sample_data/dashboard.sample.js` and `risk_model.js` in place, as shown above.
- `web/demo.copy.js` holds the `COPY` object: so far the step-1 hint, the past-event wording, "not your position"
  and the off-chain row. The other user-facing strings are still in `demo.js` and move step by step (see
  "Separation rules").
- No detector and no invented incidents: the prototype bar, the two examples and the page-built `REPLAYS` are gone.
  "Load a past incident pattern…" lists `d.past_incidents` (4 events). Selecting one sets node, failure and
  severity and passes its `opts` to `decideAt` and `breakEvenSeverity` (`S.past`); moving the dependency, failure
  or severity drops it (what-if), changing the position keeps it. Its text is in `#pastBanner` ("Pattern from …,
  applied to this position. It did not happen to PT-sUSDe."); `#banner` is only the load error. The origin layer
  and node carry a "Past pattern" tag, the card label "Pattern from …".
- First screen: `pt_reusd_aug_2026` on `lev_closest_to_liquidation` (EXIT, doing nothing loses $165k, selling
  costs $5.7k). With a real-borrower preset the card says it is "a real borrower of this market, read on chain, not
  your position". The header still shows "position size $10.00M" (gap 2).
- `sensitivity` and `decisionText` are not called yet, so `opts` reaches only `decideAt` and `breakEvenSeverity`;
  pass it when to-do 5 and 6 add them.
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
- Carry comes from `RiskModel.carryOf(d, S.alt / 100)`; the "cash earns" field is a text field
  (`inputmode="decimal"`) that accepts "4,5" as well as "4.5".
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

Checked at `b47402c`: `node web/check_demo.mjs` passes: no console errors, load-error banner hidden, 1b (first
screen: PT-reUSD on the closest borrower, EXIT, event banner, "Pattern from", "not your position"), 18/18 drawers,
2b (no detector or invented-incident wording, no prototype bar), 2c (off-chain links ethena 31/31, susde 4/4, usde
links to Ethena, quote wording by `quote_found` true 34 / null 1 / false 0, on-chain members only), 2d (4 past
events listed, each sets its incident and passes its opts; opts change the USDe result; moving the severity makes
a what-if), 2e (guide 3c rows 8/8, model and screen), 48 preset x failure combinations, 15/15 of the guide's 10M
acceptance rows, 4b 192/192, no horizontal scroll at 390px, dark background in dark mode. On the page before
`b47402c`, gates 1b, 2b, 2d and 2e fail (8 failures); gate 2c's quote wording failed before `0c71c3f`. Screenshots
checked: the first screen on desktop and at a real 390px viewport (device emulation; a plain `--window-size=390`
screenshot crops the page and is not a valid phone check). `python3 check_js_port.py` passes all 22 gates at the
`48e5ab9` merge (`f1a44c5` changed docs only).
Earlier: screenshots of the ethena drawer collapsed and expanded, the usde drawer and the graph view.
Gate 4b failed on the page before its fix (114/192, every failure with a real-borrower preset). Screenshots checked: the closest
borrower at a 2% and a 0.5% USDe depeg, and the $10M position. Not checked: the guide's 1M / 7M / 50M rows (no size
input yet; reported as SKIPPED), layout by eye in dark mode (first screen and the expanded off-chain row
included). Earlier: the carry change was
compared old vs new on 564 cases: no verdict changed, 9 REDUCE sizes moved by 1-3 points.

Gaps, most visible first:

1. "What would change the answer" is built by the page, not by `sensitivity`. Its numbers come from `decideAt`, and
   it has no "cash earns 1% less" row, so it cannot carry that bug; what is missing is the content: the duration,
   must-sell and carry alternatives and the weakest assumption.
2. No `atSize`: no position size or wallet input. The page is `web/demo.html` and shows the size as a fixed,
   assumed $10M; the header's "position size $10.00M" stays even when a real-borrower preset is selected.

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
with the closest borrower, gates 1b / 2b / 2d / 2e (`b47402c`).

Item numbers are kept from earlier versions so references stay valid: 1, 2, the old 3 (detector wording), 3b and
the new 3 (past incidents) are done.

4. Vault view, first cut: header switch, address and amount inputs in the header (they replace the PT view's two
   header inputs while this view is shown), scenario and severity, verdict badge, the
   sentence, loss if staying versus cost of exiting, and the dependency chain. Add the vault acceptance rows and a
   "PT view unchanged after switching back" gate to `check_demo.mjs`. The planned demo order opens on this view
   (Belem vault, mGLOeuro, "exit above 20%", then the PT five layers, the 16 h oracle timelock, the timeline), so
   it comes before the PT view's remaining refinements. That order is a plan only: no demo script is written yet.
5. "What would change the answer" from `RiskModel.sensitivity` (candidates table, other positions in their own
   group, `weakest`); with a past event selected, pass its `opts`.
6. Decision sentence and reasons from `RiskModel.decisionText` (guide section 5); with a past event selected, pass
   its `opts` (the reasons then say when the shock is over). It also removes page-built sentences, so fewer strings
   are left to move into `COPY`.
7. Position size input in the header through `RiskModel.atSize` (default `size_input.default_usd`, marked D until
   typed). It replaces "share of the book", which is then removed: the manager types US dollars directly
   ("Position size (USD)"). In the same change, move "Cash earns after selling, % APY" into the header next to it
   (same field, same state `S.alt`, same decimal-comma parsing, grade D mark) and remove the "Assumptions you can
   change" section, which is then empty. With a real-borrower preset the size field shows the on-chain size and is
   read-only (details in "UX decisions to keep"). Under the inputs show the guide's line: "{pt_units} PT at
   {pt_price_usd}; sellable now: {max_exit_fraction} ({capacity_usd} pool limit)". Update the selectors in
   `check_demo.mjs` in the same commit. Then the 1M / 7M / 50M acceptance rows must pass instead of being skipped.
8. Vault view, rest: markets, exit tranches, sensitivity, liquidity-run slider and table, off-chain relations of
   layer 6, timeline.
9. PT view duration slider, recovers / stays toggle and the timeline chart (`decideAtDuration`, `timeline`,
   `timelineSummary`). `decideAtDuration` and `timeline` take `altApy = S.alt / 100` (an annual rate, not `carry`)
   and compute the carry themselves over the incident's duration, capped at expiry; `null` means cash earns the
   same as the PT. A past event then sets these controls from `p.hours` and `p.recovers` (`hours: null` = not
   stated); ask the backend whether the result should come from `decideAtDuration` or from `decideAt` with `opts`
   in that case: the two differ slightly (closest borrower, PT-reUSD event: $164,900 against $164,903).
10. Last, only if time remains: PT wallet input (guide section 3b: an address read on chain, never typed-in
    collateral or debt). Until then the header has no wallet field.

Alongside, when the code is touched anyway: path texts for `navLoss` and `discount`; the three inline swatch
styles; strings into `COPY`.

Update the state, gaps and to-do when an item is done or the backend answers.

## How to work

- One concern per change: a fix, the split, a guide update and a visual tweak are separate commits.
- Do not run a formatter over existing files. The three files as split in `9d63d93` are the baseline.
- Show a per-file summary of the diff before committing. Commit and push only when the user asks. Push after each
  verified commit, once the user approves; do not let work sit on one machine.
- Branch: `frontend`. Merge `main` in before starting (not rebase: the branch is pushed), since the backend moves
  fast.

## How to verify

Checking against the data files is not enough; the drawer crash was missed that way. Before saying a change works:

1. Open the page in a browser with the console open. No errors on load.
2. Click every one of the 9 nodes, in both displays (Layers and Graph). Each drawer opens.
3. Switch through all position presets and every failure type of each node.
4. Compare the rows of the guide's acceptance table with what the page shows, and check that the decision card
   and the exit panel agree for every preset.
5. Check phone width and dark mode for any visual change.

`node web/check_demo.mjs [page.html]` automates 1 to 5 (no packages; installed Chrome over the DevTools protocol,
`CHROME=` to override). It reads the acceptance table from `../FRONTEND_GUIDE.md` at run time, prints one
`GATE PASS` / `GATE FAIL` line per check and exits 1 on any failure or console error. Run it before each commit;
for a refactor, run it on the old and the new page and compare the output. It runs from disk: no server and no
deployment. It does not judge layout by eye. Gate 4b checks one pair of screen parts (exit panel against the
decision card); other parts are not cross-checked, so a full pass is not proof that the page is consistent.
State plainly what was checked and what was not.
