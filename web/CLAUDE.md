# web/CLAUDE.md — front end (Risk Desk demo)

Front end for the Belem Capital track: one static page with two views. The position view (PT, the default) takes
a single position and an incident set by hand (node, failure, severity) and returns a stay / exit recommendation
with its reasoning. The vault view takes a vault address and an amount invested and does the same for a vault
deposit. A switch at the top right of the header changes view.
The backend rules are in the root `CLAUDE.md`. This file covers `web/` only.

Reply to the user in the language they write in. Code, comments, commit messages and repo docs stay in English.

## Files (target layout)

| File                                 | Holds                                              | Never holds                                       |
| ------------------------------------ | -------------------------------------------------- | ------------------------------------------------- |
| `demo.html`                          | Markup and element ids                             | Inline styles, numbers, sentences built in script |
| `demo.css`                           | Design tokens in `:root`, then component styles    | Anything read from data                           |
| `demo.copy.js` (not created yet)     | User-facing strings, as one `COPY` object          | Logic                                             |
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
- There is no incident detector (team decision). The two sample incidents are invented quick picks and must always
  be labelled as invented. The page still calls them "detected" and has a "Detector feed" control; see to-do 3.
- Two page views, switched at the top right of the header: Position (PT), the default, and Vaults.
- In the PT view, two dependency views: Layers (default) and Graph. Same incident and numbers in both.
- Plain words. One number per sentence. Amounts in USD, shares as % of the position.
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
- **Inputs.** Vault address (text field plus a dropdown from `VAULTS.report.vaults`, matched case-insensitively;
  default Belem RWA EURCV) and amount invested (default 10,000,000, in the vault's asset). Then scenario
  (`details[a].incidents`, default `worst_incident`) and severity.
- **Units differ from the PT view.** Vault severities are fractions (0.8414), not percent; money is in the
  vault's currency (EURCV for Belem), not always USD, even though result fields end in `_usd`.
- **Coverage.** 33 vaults: 12 `full`, 4 `partial`, 6 `not_supported`, 11 `out_of_scope`. Only `full` ones get
  numbers; the others are listed greyed with their `note`. Incidents with `analyzed: false` (WBTC, wstETH, cbBTC)
  are listed greyed, never with a loss.
- **Model.** `RiskModel.vaultDecideAt(inc, v.exit, amount, severity, altApy, horizonDays)` for the verdict (STAY /
  EXIT / EXIT_PARTIAL / REVIEW), `vaultLossAt`, `vaultRun` (liquidity run: no badge, a table), `vaultSensitivity`,
  `vaultTimeline`, `vaultTimelineSummary`. No probability: do not show `outcomes[].probability`, `expected_loss`,
  `tail_loss_95` or `break_even`.
- **Same UX rules as the PT view.** First screen: badge, the sentence (guide section 4), loss if staying versus
  cost of exiting. Dependency chain (6 layers), markets, exit tranches, sensitivity and timeline open on demand.
- **A slip in the vault guide.** Its rule 2 and its assumptions line name `RiskModel.vaultDecide`; its files table
  says that function is probability-based and must not be used. Use `vaultDecideAt` everywhere and tell the
  backend.
- **The amount default exceeds the Belem vault.** 10,000,000 is above its total assets (about 4.7M EURCV); the
  guide has a message for that case. Show it; do not silently cap the input.

## Current state (`frontend` at `8baf37b`)

What is on the branch:

- `web/demo.html` (markup), `web/demo.css` (both former `<style>` blocks, in order) and `web/demo.js` (the former
  inline script), moved line for line: rebuilding the old single file from the three gives it byte for byte.
  The page loads `../sample_data/dashboard.sample.js` and `risk_model.js` in place, as shown above.
- No `demo.copy.js` yet: user-facing strings are still in `demo.js` (118 sentences, 30 of them inside HTML
  templates). They move step by step (see "Separation rules").
- Still against the separation rules: three SVG legend swatches in `demo.js` (`renderExit`) carry inline colour
  styles that are not geometry.
- Step 3 and every probability input are gone: the verdict comes from `RiskModel.decideAt`, the step-2 zones and
  "selling starts at / pool limit from" from `breakEvenSeverity`. Wide % sliders use a log scale shared with the
  zone bar.
- Edges come from `ui.edges` only (data id `position` drawn as the page's `pos`).
- Carry comes from `RiskModel.carryOf(d, S.alt / 100)`; the "cash earns" field is a text field
  (`inputmode="decimal"`) that accepts "4,5" as well as "4.5".
- `main` was merged at `9fd615e` (in `a4d9f9e`). The backend pushes often, so run
  `git log HEAD..origin/main --oneline` before starting and merge first.

Checked at `8baf37b`: `python3 check_js_port.py` passes all 21 gates; `node web/check_demo.mjs` passes: no console errors,
banner hidden, 18/18 drawers, 48 preset x failure combinations, 15/15 of the guide's 10M acceptance rows (model and
on-screen verdict), no horizontal scroll at 390px, dark background in dark mode. Not checked: the guide's 1M / 7M /
50M rows (no size input yet; reported as SKIPPED), layout by eye in dark mode and at phone width, and whether the
decision card and the exit panel agree (gap 1 below; the script has no check for it yet). The carry change was
also compared old vs new on 564 cases (every preset, failure and four severities at cash 0 / 2 / 4%): no verdict
changed, 9 REDUCE sizes moved by 1-3 points.

Gaps, most visible first:

1. **The exit panel contradicts the decision card for the two real-borrower presets.** With
   `lev_closest_to_liquidation` ($3.25M) and a 2% USDe depeg the card says "Selling $3.25M now" while the exit
   panel says "Today: up to $1.46M (45%)". With a 0.5% depeg the panel says "If this plays out: up to $3.25M
   (100%) … after liquidators sell first": more than "today", and no liquidation happens. Cause: `MAXX`, `CURVE`,
   the "All sale sizes" table, the chart and the layer-4 fact use `d.max_exit_fraction` and `d.exit_curve`, which
   describe the $10M size input; the model returns `sellable_now = 1` for the real borrowers.
2. "What would change the answer" is built by the page, not by `sensitivity`. Its numbers come from `decideAt`, and
   it has no "cash earns 1% less" row, so it cannot carry that bug; what is missing is the content: the duration,
   must-sell and carry alternatives and the weakest assumption.
3. No `atSize`: no position size or wallet input. The page is `web/demo.html` and shows the size as a fixed,
   assumed $10M.
4. The page's wording still describes a detector (UX section above).

Answered by the backend (guide section 0b, merged):

- Slider ranges: `min` / `max` in `failure_types.types` are the range the model covers. The page may narrow a
  range (depeg 1–60 is fine) but must not widen it. Cascade is now 1–40 in the data. The starting value is the
  page's choice. Pass the page's slider range to `breakEvenSeverity`.
- Exit curve per position: `RiskModel.sizeCurve(d, P.collateral_usd)`. `decideAt` and `inject` already use it.
  `d.exit_curve` and `d.max_exit_fraction` belong to the size input's position only and must not be used for the
  real-borrower or wallet presets. This is the fix for gap 1.
- New on `main`: `RiskModel.decisionText(...)` returns the headline, reasons, break-even and the assumption the
  answer hinges on, in the backend's wording (guide section 0, priority 4).

This file loads when a file in `web/` is opened; otherwise read it at the start of the session.

## To-do, in order

Done: `main` merged (repeat after every backend push, then `python3 check_js_port.py`); page moved to
`web/demo.html`; position edges from the data; probability removed, verdict from `decideAt`, zones from
`breakEvenSeverity`; split into `demo.html`, `demo.css`, `demo.js`; `check_demo.mjs` written; `main` merged at
`9fd615e` (`a4d9f9e`); carry from `RiskModel.carryOf`, decimal comma accepted (`8baf37b`).

2. Fix gap 1. First add a gate to `check_demo.mjs`: for every preset and failure, the "today" amount in the exit
   panel is at least the amount the card says to sell, and "If this plays out" names liquidators only when
   `sellable_later < sellable_now`. It should fail on the current page. Then take the sellable share and amounts
   from the `decideAt` result, and the curve, table and chart from `RiskModel.sizeCurve(d, P.collateral_usd)`.
3. Wording: no detector. Rename the sample feed to example incidents (invented), remove "Detector feed",
   "detected now", "the detector is not connected yet" and the "Detected" tag. Ask the user before removing the two
   samples themselves.
4. Vault view, first cut: header switch, address and amount inputs, scenario and severity, verdict badge, the
   sentence, loss if staying versus cost of exiting, and the dependency chain. Add the vault acceptance rows and a
   "PT view unchanged after switching back" gate to `check_demo.mjs`. The backend's demo script opens on this view
   (Belem vault, mGLOeuro, "exit above 20%"), so it comes before the PT view's remaining refinements.
5. "What would change the answer" from `RiskModel.sensitivity` (candidates table, other positions in their own
   group, `weakest`).
6. Decision sentence and reasons from `RiskModel.decisionText` (guide section 5). It also removes page-built
   sentences, so fewer strings are left to move into `COPY`.
7. Position size input in the header through `RiskModel.atSize` (default `size_input.default_usd`, marked D until
   typed). It replaces "share of the book", which is then removed. Then the 1M / 7M / 50M acceptance rows must pass
   instead of being skipped.
8. Vault view, rest: markets, exit tranches, sensitivity, liquidity-run slider and table, off-chain relations of
   layer 6, timeline.
9. PT view duration slider, recovers / stays toggle and the timeline chart (`decideAtDuration`, `timeline`,
   `timelineSummary`).
10. Last, only if time remains: PT wallet input.

Alongside, when the code is touched anyway: path texts for `navLoss` and `discount`; the three inline swatch
styles; strings into `COPY`.

Update the state, gaps and to-do when an item is done or the backend answers.

## How to work

- One concern per change: a fix, the split, a guide update and a visual tweak are separate commits.
- Do not run a formatter over existing files. The three files as split in `9d63d93` are the baseline.
- Show a per-file summary of the diff before committing. Commit and push only when the user asks. Push after each
  verified commit; do not let work sit on one machine.
- Branch: `frontend`. Merge `main` in before starting (not rebase: the branch is pushed), since the backend moves
  fast.

## How to verify

Checking against the data files is not enough; the drawer crash was missed that way. Before saying a change works:

1. Open the page in a browser with the console open. No errors on load.
2. Click every one of the 9 nodes, in both views. Each drawer opens.
3. Switch through all position presets and every failure type of each node.
4. Compare the rows of the guide's acceptance table with what the page shows, and check that the decision card
   and the exit panel agree for every preset.
5. Check phone width and dark mode for any visual change.

`node web/check_demo.mjs [page.html]` automates 1 to 5 (no packages; installed Chrome over the DevTools protocol,
`CHROME=` to override). It reads the acceptance table from `../FRONTEND_GUIDE.md` at run time, prints one
`GATE PASS` / `GATE FAIL` line per check and exits 1 on any failure or console error. Run it before each commit;
for a refactor, run it on the old and the new page and compare the output. It runs from disk: no server and no
deployment. It does not judge layout by eye, and until to-do 2 it does not check that two parts of the screen
agree with each other, so a full pass is not proof that the page is consistent.
State plainly what was checked and what was not.
