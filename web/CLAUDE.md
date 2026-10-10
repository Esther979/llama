# web/CLAUDE.md — front end (Risk Desk demo)

Front end for the Belem Capital track: one static page that takes a single position, a simulated or detected
incident and its severity, and returns a stay / exit recommendation with its reasoning.
The backend rules are in the root `CLAUDE.md`. This file covers `web/` only.

Reply to the user in the language they write in. Code, comments, commit messages and repo docs stay in English.

## Files (target layout)

| File                                 | Holds                                               | Never holds                                       |
| ------------------------------------ | --------------------------------------------------- | ------------------------------------------------- |
| `demo.html`                          | Markup and element ids                              | Inline styles, numbers, sentences built in script |
| `demo.css`                           | Design tokens in `:root`, then component styles     | Anything read from data                           |
| `demo.copy.js`                       | Every user-facing string, as one `COPY` object      | Logic                                             |
| `demo.js`                            | State, calls to `RiskModel`, rendering, events      | Colours, sizes, literal sentences                 |
| `risk_model.js`                      | Backend's model. Read-only here                     | —                                                 |
| `../sample_data/dashboard.sample.js` | Backend's data (`window.DASHBOARD`). Read-only here | —                                                 |

No framework and no build step. The page must open from disk by double-click.

The page loads the backend's two files in place:

```html
<script src="../sample_data/dashboard.sample.js"></script>
<script src="risk_model.js"></script>
```

Do not copy or move those two files. The backend regenerates them, and a copy goes stale on the next push.
If the page is ever served over HTTP, serve from the repo root, not from `web/`, or the data path breaks.

## Separation rules

- State is expressed as classes or data attributes (`data-verdict="stay"`, `.hot`, `.origin`, `.hyp`). CSS decides
  how each state looks.
- Script may set inline values only for computed geometry: bar widths, SVG coordinates, chart points.
- Every colour comes from a token. Light and dark values are defined together. Colour means verdict state only
  (stay / reduce / exit); dashed means assumption (grade D).
- A visual change should produce a diff in `demo.css` only. A wording change should produce a diff in
  `demo.copy.js` only. If a change needs more files than that, say so before making it.

## Source of truth

- `../FRONTEND_GUIDE.md` and its acceptance table decide behaviour. Re-read it after every `git pull`; it changes.
- No loss formulas in the page: every number comes from `RiskModel.*`. No snapshot numbers: read `window.DASHBOARD`.
- No probability anywhere. The backend's probability fields are legacy; do not use them.
- Failure labels, units and ranges come from `failure_types.types`. A key the page does not know must appear as one
  more option, not break the page.
- Edges, including the two to the position, come from `ui.edges`. Do not add page-made edges.
- If the data lacks something, ask the user to raise it with the backend. Do not invent it.
- Never edit the Python files, `sample_data/`, `risk_model.js` or the guides from a front-end task.

## UX decisions to keep

- First screen shows only: the verdict, one comparison (do nothing vs act), and the incident path.
  Everything else opens on demand (folds, evidence drawer).
- Inputs run in thinking order, left to right: where, what and how bad. Sliders update live; no Run button.
- One mode (Prototype): any dependency can be failed by hand; detected incidents are listed first. Preview was
  removed on 10 Oct.
- Two dependency views. Layers (default) and Graph. Same incident and numbers in both.
- Detected and what-if incidents look different (solid tag vs dashed tag).
- Sample alerts are invented and always labelled as such.
- Plain words. One number per sentence. Amounts in USD, shares as % of the position.
- Every number in the drawer shows its source and its evidence grade (A to D).
- Works at phone width; the graph may scroll sideways inside its own container.

## Current state (`frontend`, 11 Oct, after the CSS / JS split)

What is on the branch:

- `web/demo.html` (markup), `web/demo.css` (both former `<style>` blocks, in order) and `web/demo.js` (the former
  inline script), moved line for line: rebuilding the old single file from the three gives it byte for byte.
  The page loads `../sample_data/dashboard.sample.js` and `risk_model.js` in place, as shown above. There is no
  `demo.copy.js` yet: user-facing strings are still in `demo.js` (118 sentences, 30 of them inside HTML templates).
- Still against the separation rules: three SVG legend swatches in `demo.js` (`renderExit`) carry inline colour
  styles that are not geometry.
- Preview mode is removed (Prototype only). Step 3 and every probability input are gone: the verdict comes from
  `RiskModel.decideAt`, the step-2 zones and "selling starts at / pool limit from" from `breakEvenSeverity`.
  Wide % sliders use a log scale shared with the zone bar.
- Edges come from `ui.edges` only (data id `position` drawn as the page's `pos`); all 18 drawers open.
- `main` is merged in: the model now has `atSize`, `carryOf`, `sensitivity`, `decideAtDuration`, `timeline`,
  `timelineSummary`; the data has `time_model` and real-borrower presets. `FRONTEND_GUIDE.md` is `main`'s version.

Checked after the split with `node web/check_demo.mjs`: no console errors, banner hidden, 18/18 drawers, 48 preset x
failure combinations, 15/15 of the guide's 10M acceptance rows (model and on-screen verdict), no horizontal scroll at
390px, dark background in dark mode; the same output as the single file before the split. `python3
check_js_port.py` passes all 19 gates after the `4329aae` merge. Not checked: the guide's 1M / 7M / 50M rows (the
page has no size input yet; the script reports them as SKIPPED), and dark / phone layouts by eye.

Gaps against the current guide (its section 0 sets this order): 1. carry is computed by the page instead of
`RiskModel.carryOf` (verdicts are wrong whenever "cash earns" is not 5.01%); 2. "what would change the answer" is
built by the page instead of `sensitivity`; 3. no `atSize` (no position size or wallet input).
Answer to the guide's open point: the page is `web/demo.html` and it has no position-size input yet.

No detector exists (team decision, guide rule 3): `d.detected` is always empty; the sample feed stays, labelled
as invented.

This file loads when a file in `web/` is opened (the page is there now); otherwise read it at the start of the
session.

## To-do, in order

1. ~~Bring the branch up to date: merge `main` into `frontend`.~~ Done twice (`80a806e`, then `4329aae`); merge,
   not rebase, because `frontend` is pushed. Repeat after every backend push, then run `check_js_port.py`.
2. ~~Move the page to `web/demo.html`, set the two script paths and the error message.~~ Done in `96665fd`
   (own commit; loads from disk, checks above).
3. ~~Fix the PT / lending drawer crash from duplicate position edges.~~ Done: data edges only.
4. Split into the four files of the target layout. Done for `demo.css` and `demo.js` (pure move, own commit).
   Left: `demo.copy.js`. Moving the strings into one `COPY` object rewrites most render functions, so it is its own
   commit, checked with `check_demo.mjs` (same output before and after).
5. Follow the current guide. Done: step 3 and all probability code removed, verdict from `decideAt`, zones from
   `breakEvenSeverity`. Left, in the guide's order: carry via `carryOf`, "what would change the answer" from
   `sensitivity`, position size / wallet input via `atSize` (then check the 1M / 7M / 50M rows).
6. Duration slider, recovers / stays toggle and the timeline chart (`decideAtDuration`, `timeline`,
   `timelineSummary`).
7. Assumptions panel: keep "cash earns after selling"; "share of the book" is display-only and optional.
8. Wording left from the probability model ("if severe"); path texts for `navLoss` and `discount`.
   ("if severe" in the position line is fixed.)

Update both sections when an item is done.

## How to work

- One concern per change: a fix, the split, a guide update and a visual tweak are separate commits.
- Do not run a formatter over existing files. The local `demo.html` was formatted once; treat that as the
  baseline and do not reformat again.
- Show a per-file summary of the diff before committing. Commit and push only when the user asks.
- Branch: `frontend`. Rebase on `main` before starting, since the backend moves fast.

## How to verify

Checking against the data files is not enough; the drawer crash was missed that way. Before saying a change works:

1. Open the page in a browser with the console open. No errors on load.
2. Click every one of the 9 nodes, in both views and both modes. Each drawer opens.
3. Switch through all position presets and every failure type of each node.
4. Compare the rows of the guide's acceptance table with what the page shows.
5. Check phone width and dark mode for any visual change.

`node web/check_demo.mjs [page.html]` automates 1 to 5 (no packages; installed Chrome over the DevTools protocol,
`CHROME=` to override). It reads the acceptance table from `../FRONTEND_GUIDE.md` at run time, prints one
`GATE PASS` / `GATE FAIL` line per check and exits 1 on any failure or console error. Run it before each commit;
for a refactor, run it on the old and the new page and compare the output. It does not judge layout by eye.
State plainly what was checked and what was not.
