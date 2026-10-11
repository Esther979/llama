# Five-minute presentation: Dependency Risk Desk

Focus: the PT view, the reasoning, and how the dependencies are found. The page does the clicking:

```bash
npm i --no-save playwright                      # once, repo root
node web/demo_autopilot.mjs --skip 12,14,15     # 13 stops; → in the browser advances, ← repeats the cue, Esc quits
```

Rehearse with `--auto 20 --captions` (a 20 s timer per stop, the cue at the bottom of the page), then without captions.
Numbers are from the 10 Oct 2026 sample; after a data refresh, read them off the page again.
About 700 words at a normal pace; if short of time, cut the lines marked [cut].

| Time | Stop | On screen | Point |
|---|---|---|---|
| 0:00 | 1 | First screen: real borrower, PT-reUSD pattern, EXIT | The brief's sentence; three things the system does |
| 0:40 | 2 | Graph display of the stack | How dependencies are discovered |
| 1:15 | 3 | USDe 3%, 6 h, Layers: STAY | Propagation layer by layer |
| 1:50 | 4 | Play, then 16 h: EXIT | Time: the 16 h timelock read from the contract |
| 2:25 | 5 | Graph lit, "How it spreads" | Path = crawled edges, with grades |
| 2:45 | 6 | Layer 3 evidence drawer | Every number opens to its source |
| 3:05 | 7 | Stays, 6 h | The one off-chain assumption, shown both ways |
| 3:20 | 8 | Sensitivity and timeline folds | The weakest assumption; "until the timelock" |
| 3:40 | 9 | PT held outright, $10M, recovers: STAY | Same incident, different holder |
| 3:55 | 10 | Stays: SELL $4.5M, exit chart | Pool limit; three holders, three answers |
| 4:15 | 11 | Vaults: Belem RWA EURCV, 4.7m | Same engine on a vault deposit |
| 4:35 | 13 | Severity down: STAY | Break-even 20.09% |
| 4:45 | 16 | Back to top | Close |

## Speech

**Stop 1 (0:00). First screen.**
Belem's brief puts it in one line: the hard part is not noticing the incident, it is working out what it does to
your book, and how fast. Dependency Risk Desk is built around that sentence. You give it one position, here a Pendle
PT-sUSDe held as collateral on Morpho, and it does three things. It discovers the dependency stack from contract
code. It propagates a failure through that stack, layer by layer and hour by hour. And it turns the result into one
decision in money: how much to sell now, how much to keep, and why. Everything on this screen is read on chain or
from a live quote: this is a real borrower of this market, 0.99% from liquidation. No probabilities anywhere, by
design: we answer "what if this happens", not "how likely".

**Stop 2 (0:40). Graph display.**
How do we find the stack? Not from a list we typed. A crawler starts at the Morpho market, pulls the verified source
of every contract from Etherscan, calls every function that returns an address, walks the arrays, turns Morpho market
ids into nodes, and keeps going five levels deep. Behind this one position it found 82 contracts and 96 links. Then we
classify what each dependency does, from its source. This oracle is not "an oracle": it is a MetaOracleDeviationTimelock
over a linear-discount price, with a Chainlink backup, and that distinction is the whole story you are about to see.
[cut] On top of the on-chain graph, 35 off-chain relations for Ethena, custodians, exchanges, the reserve fund, each
with a source document and a quote. The nine nodes you see are that graph arranged in the brief's five layers.

**Stop 3 (1:15). USDe 3%, 6 h.**
Now an incident: a 3% USDe depeg, the size of the daily low on 1 February. Six hours in. Layer 2 is the origin.
Layer 4 is affected: the PT redeems to sUSDe, so it falls 3% too. But layer 3, the oracle, is unchanged: the
meta-oracle switches to its backup only after a deviation above 0.75% lasting 16 hours. Layer 5 is unchanged: nobody
is liquidated. Verdict: STAY. Six hours in, the incident is on every screen, but it has not reached this book.

**Stop 4 (1:50). Play, then 16 h.**
Watch what time does. (Play runs.) At hour 16 the challenge timelock expires, the oracle switches, the lending market
sees the 3%, and this position is liquidated. STAY becomes EXIT: doing nothing loses 172 thousand dollars; selling
everything now costs 5,700. The 16 hours is not our assumption. It is `challengeTimelock`, 57,600 seconds, read from
the contract. That is the answer to "how fast".

**Stop 5 (2:25). Graph lit, "How it spreads".**
The same path on the graph: USDe to sUSDe to the PT to the Morpho market to the position. Every arrow is an edge the
crawler found, not one we drew. [cut] And as a list of steps, each with its evidence grade: A measured on chain, B
verified in source and back-tested, C analogy, D assumption.

**Stop 6 (2:45). Layer 3 drawer.**
The evidence behind layer 3: the contracts the crawler found, the threshold, the timelock, the primary and the backup
feed. Every number on this page opens like this.

**Stop 7 (3:05). Stays.**
One thing the contracts cannot tell us: whether USDe comes back. That is decided off-chain, so it is the manager's
assumption, and we show both. If it stays down, it is EXIT at any duration: 97 thousand already at hour six.

**Stop 8 (3:20). Sensitivity and timeline.**
"What would change the answer" names the weakest assumption. Here it is the duration: if the incident ends at hour 8,
under the timelock, the verdict is STAY. The timeline shows it: a STAY band until 16 hours, EXIT after. At three in
the morning, that is the number you need: you have until the timelock.

**Stop 9 (3:40). PT held outright.**
Same incident, same severity, a different holder: the PT held outright, 10 million. If USDe recovers, STAY at every
duration. The oracle still switches at hour 16, but there is nothing to liquidate.

**Stop 10 (3:55). Stays, SELL $4.5M.**
If it does not recover: sell 4.5 million, because that is all Pendle will take today. Staying loses 300 thousand,
acting costs 187. The chart is the cost of acting at every share sold; the lowest point is the recommendation. Same
incident, three holders, three answers. That is why the decision is made per position, not per asset.

**Stop 11 (4:15). Vaults.**
The same engine works on a vault deposit. Belem's own RWA EURCV vault, a deposit the size of the vault, its worst
incident, an mGLOeuro issuer default: exit 1.03 million now, which is all the free and forced tranches allow; 3.67
million is lent against the token that just failed and cannot leave.

**Stop 13 (4:35). Severity down.**
Drag the severity down: below 20.09% it is STAY. That break-even is the number for the desk.

**Stop 16 (4:45). Close.**
To sum up. Dependencies discovered from code, not typed. Impact from the venue's own liquidation rules, back-tested
nine out of nine on the August PT-reUSD incident. A decision in money, with the assumption it hinges on. All on live
data, reproducible with one pipeline and two automated checks. Thank you.

## Likely questions

- **Is the discovery really automatic?** Yes: `crawl.py` from the Morpho market, depth 5, every address-returning
  view of every verified contract; oracle types from source (`oracle_types.py`). The page's five layers are that
  graph in the brief's order; the drawers list what was found. The nine nodes are the arrangement, not the input.
- **Why no probability?** The organisers asked for none: sudden events cannot be predicted. The output is the
  break-even severity and the loss at the severity you choose; historical anchors sit on the slider for scale.
- **Why a PT-reUSD event on a sUSDe position (first screen)?** A pattern (an oracle reporting too low), labelled as
  such; the sUSDe event itself, the USDe low of 1 Feb 2026, is in the same list.
- **How fresh is the data?** A snapshot of 10 Oct (borrowers at block 26163209, vaults at 26163394); the refresh is
  one pipeline of about 15 minutes; each source's block and time is in the drawers.
- **What is not covered?** Volatile collateral in vaults (WBTC, wstETH, cbBTC), chain halts, Solana vaults.
