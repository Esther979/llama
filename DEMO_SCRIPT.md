# Demo script (3 minutes): Dependency Risk Desk

Page: `web/demo.html` on `frontend` (opened from disk in Chrome, light mode, window about 1440 px wide). Data: sample
of 10 Oct 2026 (borrowers at block 26163209, Pendle quotes 09:23 UTC, vaults at block 26163394). Every number below
was recomputed from `sample_data/` with the model; after a data refresh, re-read them from the page (they move a little).

The story in one line: **noticing the incident is easy; the page shows what it does to the book, layer by layer, and
when.** Scene 1 carries 60% of the time because it is the brief's worked example (five layers, incident at the oracle,
"how fast").

## Before the judges arrive

- Open the page, leave the first screen as it loads (real borrower closest to liquidation, PT-reUSD oracle pattern,
  EXIT). Do not pre-click anything: the first screen is the opener.
- Keep the Layers display (the list icon) selected; the Graph display is switched on live in scene 1.
- Check the duration field reads `1 h` and the Simulate switch is on "A past incident".

## Scene 0 (0:00–0:15): the first screen

Say: "Every number on this page is read on chain or from a live quote: 13 real borrowers of the Morpho PT-sUSDe
market, real Pendle sell quotes, the oracle's own contract. No probabilities: you pick the incident and its severity,
we tell you what it costs to stay and what it costs to leave."

Point at the card: "This is a real borrower, 0.99% from liquidation. We apply the pattern of the PT-reUSD oracle drop
of 25 August, which we back-tested 9 out of 9 positions. Doing nothing loses $165k, selling everything costs $5.7k:
EXIT."

## Scene 1 (0:15–1:40): the incident travels through the five layers, and when

1. **Switch Simulate to "Manual".** Open the "Incident type" menu: the first level lists the dependencies by layer;
   hover "USDe" (layer 2) and pick "Loses value". Set Severity to **3%**. A "Recovers / Stays" toggle appears next to
   the duration (only for off-chain causes: USDe, Ethena, sUSDe NAV). Leave **Recovers**.
   Say: "A 3% USDe depeg, like the daily low of 1 February this year."
2. **Type `6` in the duration field** (6 hours). Read the Layers display top to bottom:
   - Layer 2 **Origin**: USDe falls 3%.
   - Layer 4 **Affected**: the PT redeems to sUSDe, so it falls 3% too; a holder who can wait gets it back.
   - Layer 3 **Unchanged**: "the meta-oracle switches only after a deviation above 0.75% lasting 16 h; this incident
     lasts 6 h: the lending oracle does not move."
   - Layer 5 **Unchanged**: not liquidated, the line is 0.99% away.
   - Verdict **STAY**. Say: "Six hours in, the incident is visible everywhere, but it has not reached this book."
3. **Press Play.** The thumb sweeps 1 h to 180 days in about 9 s and pauses just past the red mark at 16 h: layers 3
   and 5 flash to **Affected**, the card flips to **EXIT**. When the sweep ends, **type `16`** to land exactly on the
   event: "doing nothing loses $172,215; selling $3,249,472 now costs $5,743."
   Say: "At hour 16 the oracle's challenge timelock expires, it switches to the backup feed with USDe/USD, the lending
   market sees the 3% and liquidates this position. That 16 h is not our assumption: it is `challengeTimelock` read
   from the MetaOracleDeviationTimelock contract, 57,600 seconds."
4. **Click the Graph icon.** The lit path runs USDe → sUSDe → PT → Morpho market → position along the crawled edges.
   Open the fold **"How it spreads, step by step"** under the chain: the same path as steps, each with its evidence
   grade. Switch back to Layers.
5. **Click "Show 2 dependencies and evidence" under Layer 3.** The drawer shows the oracle as found by the crawler:
   MetaOracleDeviationTimelock, deviation threshold 0.75%, challenge timelock 16 h, primary = linear discount oracle
   (no market input), backup = Chainlink USDe/USD. Say: "Dependency discovery is ABI-driven: 82 contracts and 96
   links behind this one position, read from verified source, plus 35 off-chain relations of Ethena with the quoted
   document for each." Close the drawer.
6. **Flip the toggle to "Stays"** (still at 16 h, then type `6`): EXIT at every duration, loss $97k at 6 h, because a
   permanent 3% on the collateral is a permanent loss on the equity. Say: "Whether USDe comes back is decided
   off-chain, so it is your assumption; we show both answers."
   Flip back to **Recovers**, type `16`.
7. **Open "What would change the answer"** on the card: the weakest assumption is the duration: "if the incident
   lasts 8 h, less than the 16 h timelock, the verdict is STAY". Open **"Loss if staying, by how long the incident
   lasts"** under the chain: the timeline chart, STAY band up to 16 h, EXIT after. Say: "That is the answer the manager
   needs at three in the morning: you have until the timelock, not a minute longer."

## Scene 2 (1:40–2:05): same incident, different holding

1. **Change "PT holding type" to "PT held outright"**; the size field becomes editable and shows `10m`.
   With Recovers: **STAY at every duration**. Layer 3 still switches at 16 h, but its text says it matters only for a
   levered position: nothing to liquidate.
2. **Flip to "Stays"**: **SELL $4.5M** (sell to the pool limit, 45%): staying loses $300k, acting costs $187k. Point
   at "Can you get out?": "Pendle takes at most $4.5M today; a $10M book cannot leave in one go. The exit chart below
   is the cost of acting at every share sold, with the lowest total marked." Drag the "Cash earns" slider: the chart
   moves with the yield given up.
   Say: "Same incident, same severity: the levered borrower must leave at hour 16, the outright holder can wait, and a
   $10M holder is capped by the pool. That is why the decision has to be made per position."

## Scene 3 (2:05–2:50): a vault deposit, Belem RWA EURCV

1. **Click "Vaults"** at the top right. Belem RWA EURCV is preselected; **type `4.7m`** in "Amount invested" (a
   deposit the size of the vault; the default 10m is above the vault's 4.71M and shows a note). Worst incident
   preselected: **mGLOeuro issuer default**, severity 84.14% (the median severe stablecoin failure).
   Read the card: **EXIT 1.03M**: staying loses about 2.9M EUR (61.62% of the deposit), exiting 1.03M now costs
   492 EUR, about 3.67M EUR cannot be withdrawn now.
   Say: "Only the free tranche can leave now: idle plus the liquidity market, then what `forceDeallocate` can pull
   from the other markets. The rest is lent against the token that just failed."
   Then **type `1m`**: the badge becomes a full **EXIT**, the whole 1M leaves (362k free, the rest forced, nothing
   locked), cost 477 EUR against a 616k loss. Say: "A small depositor gets out; a large one is stuck. The amount is
   part of the answer."
2. **Drag the severity slider down** across the green / amber / red zones: below **20.09%** the badge flips to
   **STAY**. Say: "That break-even is the number for the desk: the vault is worth leaving once you believe mGLOeuro
   loses more than a fifth."
3. **Click the Graph icon** in "Dependency mapping": six layers, chain → vault → Morpho Blue → six markets →
   collateral and oracles → issuers; the mGLOeuro path lit, 12 links drawn by the backend (dashed = assumption).
   Switch to Layers and open the **layer 6 off-chain block for mGLOeuro**: 17 relations with source links, e.g. the
   NAV feed "submitted manually by feed admins", updated monthly. Say: "The hidden dependency is not a contract: it is
   a monthly manual NAV. A failure shows up here before any oracle moves."
4. **Open "Exit, tranche by tranche"**: free part (idle + liquidity market), forced part through VaultV2
   `forceDeallocate` with its on-chain penalty, locked remainder; and the liquidity-run line: "if all depositors
   withdrew, only 7.68% of the vault could leave without penalty."

## Scene 4 (2:50–3:00): close

Say: "33 RockawayX vaults in the input file, 12 Ethereum Morpho vaults with full numbers. Break-even severities of
the worst incident: Tori 7.9%, YIELD 10.1%, Huma 11.8%, Belem 20.1%, NUVA 21.4%. Everything is reproducible: one
pipeline, 28 model gates and 50 browser gates, no probabilities and no invented incidents. The page answers the
question you asked: how much to leave, when, and why."

## Do not click during the demo

- The duration field accepts `16`, `3d`, `1w`; the Play button stops at any other input. After Play, type the hour
  you want to talk about: the sweep ends at 180 days.
- In "A past incident" mode steps 1 and 2 are read-only; switch to Manual before touching the severity.
- Stream xUSD and Elixir deUSD past events have no duration (they run at the default); keep to USDe Feb 2026 and
  PT-reUSD if a judge asks for a past event.
- `Ethereum mainnet · Chain halts` is listed but not modelled (no exit and no liquidation during a halt): say so if
  asked, do not pick it.
- The vault view's WBTC / wstETH / cbBTC incidents are greyed ("not analysed"): volatile collateral is the known gap.
- The vault time rail is flat for Belem ("the duration does not change the answer": no affected market has an
  oracle timer). Do not play it; the dynamic duration story is the PT view's.

## If a judge asks

- "Is the discovery automatic?" Yes: `crawl.py` calls every address-returning view of every verified contract from
  the Morpho market down (depth 5), turns Morpho market ids into nodes, classifies oracles from source; the page's
  five layers are that graph arranged in the brief's order; the drawers list the contracts found.
- "Where is the probability?" Nowhere, by the organisers' request: the output is the break-even severity and the
  loss at the severity you choose; historical anchors sit on the slider for scale.
- "Why a PT-reUSD event on a sUSDe position?" It is a pattern (an oracle reporting a price too low) applied to this
  position, labelled as such; the real sUSDe event is the USDe low of 1 Feb 2026, in the same list.
- "How fresh?" Snapshot of 10 Oct; the refresh is one pipeline (about 15 minutes), the block and time of each source
  are in the drawers.
