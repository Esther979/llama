/* User-facing strings of the demo page, as one COPY object (web/CLAUDE.md, "Files").
   Strings move here step by step: a sentence that is new or being changed comes here; the others move when their
   render function is next edited. Values are strings, or small functions that only place numbers into a sentence. */
const COPY = {
  /* Step hints. An incident is set by hand or loaded from a real past event (no detector, no invented incidents). */
  steps: {
    q1: "Incident type",
    q2: "Severity",
    /* the incident as one line: where, then what */
    inc: (node, fail) => `${node} · ${fail}`,
  },

  /* How the incident is set: a past event or by hand, one or the other. */
  mode: {
    label: "Simulate",
    past: "A past incident",
    manual: "Manual",
  },

  /* Past events (d.past_incidents, guide section 3c): a pattern applied to this position, not something that
     happened to it. */
  past: {
    tag: "Past pattern",
    band: (label) => `Pattern from ${label}`,
    banner: (label, what, source) =>
      `<b>Pattern from ${label}</b>: ${what}, applied to this position. It did not happen to PT-sUSDe. ${source}. Switch to Manual to test other values.`,
    sevNote: (v) => `Severity of the past event: ${v}.`,
    info: "About this past event: what happened, the source, how it applies here",
    lasting: (dur, recovered) => `, lasting ${dur}${recovered ? ", then recovered" : ""}`,
    drawerRow: "Past pattern",
  },

  /* "What would change the answer" (RiskModel.sensitivity, guide section 5): one assumption at a time replaced by
     its stated alternative, the decision rerun. */
  sens: {
    title: "What would change the answer",
    hinges: (alt, grade, verdict) => `The answer hinges on: ${alt} → ${verdict}.`,
    robust: "No tested assumption changes the answer.",
    cols: ["If instead", "Answer"],
    others: "Other positions, same incident",
    flips: "changes the answer",
    loses: (v) => `doing nothing loses ${v}`,
    verdict: { STAY: "Stay", REDUCE: "Reduce", SELL_TO_CAP: "Sell to the pool limit", EXIT: "Exit" },
    severity: "Severity",
    stayAll: (max) => `Stay at every severity up to ${max}.`,
    stayBelow: (s, below) => `Stay below ${s}${below ? " (below this slider)" : ""}. `,
    noCap: "The pool limit is not reached on this slider.",
    cap: (pc, s) => `Sell up to the ${pc} pool limit from ${s}.`,
    rule: "Rule",
    ruleText:
      "Assume the incident has happened at this severity. Pick the share x that minimises x × (slippage + yield given up) + (1 − x) × loss. Never beyond the largest size Pendle quoted.",
  },

  /* Decision card (guide section 5). The sentence, reasons, break-even, hinge and rule are RiskModel.decisionText's
     own texts; these are only the card's labels and the few lines built from the decision's numbers. */
  card: {
    whatIf: "What-if",
    actExit: (v) => `Sell all ${v} now.`,
    actStay: "Keep the position.",
    actStayLoss: "Keep the position: selling costs more than it saves.",
    badge: { STAY: "Stay", EXIT: "Exit", sell: (v) => `Sell ${v}` },
    noLoss: "no direct loss",
    ofPosition: (p) => `${p} of the position`,
    allPool: "all the pool will take",
    stuck: (v) => `${v} stuck`,
    sellableToday: "Sellable today",
    ifPlaysOut: "If this plays out",
    noneFor: (s) => `None for ${s}`,
    none: "None",
    doNothing: "Do nothing",
    act: "Act",
    sellPc: (p) => `Sell ${p}`,
    tipLoss: (v) => `Loss if you do nothing ${v}`,
    tipCost: (v) => `Cost of selling ${v}`,
    tipKept: (v) => `Loss on the part you keep ${v}`,
    keyLoss: "Loss",
    keyCost: "Cost of selling",
    stuckLine: (a, b) => `<b>${a} cannot be sold through Pendle now.</b> With the rest you keep, ${b} stays at risk.`,
    range: (lo, hi) => `Loss is between ${lo} and ${hi} depending on the oracle; the decision uses the high end.`,
  },

  /* Time rail: how long the incident lasts (guide sections 5b and 6). Event texts are RiskModel.propagationEvents'
     own; the recovers reason is RiskModel.recoveryToggle's. */
  rail: {
    q: "Time frame",
    lasted: "The incident has lasted:",
    durHint: "Drag the rail or type a duration: 16, 16h, 3d, 1w (1 hour to 180 days)",
    play: "Play",
    pause: "Pause",
    after: "After the incident",
    recovers: "Recovers",
    stays: "Stays",
    recovery: "Recovery",
    markTip: (dur, verdict, layers) => `From ${dur}: ${[verdict, layers].filter(Boolean).join("; ")}. Click to go there.`,
    layerShort: (n, from, to) => `layer ${n} ${from} → ${to}`,
    oracle: (dur) => `oracle switch ${dur}`,
    expiry: "PT expiry",
    pastMark: (dur) => `the past event: ${dur}`,
    ticks: [
      [1, "1 h"],
      [6, "6 h"],
      [24, "1 d"],
      [168, "7 d"],
      [720, "30 d"],
      [2160, "90 d"],
      [4320, "180 d"],
    ],
    jump: (dur) => `Go to ${dur}, where the path changes`,
    from: (dur) => `From ${dur}`,
    answer: "answer",
    layer: (n, from, to, text) => `Layer ${n}: ${from} → ${to}: ${text}`,
    state: {
      unchanged: "unchanged",
      hit: "hit",
      origin: "origin",
      not_applicable: "not applicable",
      not_modelled: "not modelled",
      unknown: "unknown",
    },
    none: "Between 1 hour and 180 days the path does not change with the duration.",
    carryNote: (v, dur) =>
      `Sale cost includes the yield given up over the incident (${dur}, at most until expiry): ${v} of the amount sold.`,
  },

  /* Timeline chart (guide 5b): RiskModel.timeline's loss if staying against the duration, on the rail's log axis;
     the summary is RiskModel.timelineSummary's. Not a control. */
  tl: {
    title: "Loss if staying, by how long the incident lasts",
    flat: (why) => `The duration does not change the answer: ${why}.`,
    change: (dur, a, b, why) => `From ${dur}: ${a} → ${b} (${why}).`,
    now: "now",
    aria: (n) => `Loss if staying at ${n} durations from 1 hour to 180 days, on a log scale; background coloured by the answer.`,
    assume: "Held constant over the incident: pool depth as today, the borrow APR and the PT's implied APY.",
  },

  /* Exit chart (RiskModel.actCostCurve): the cost of acting at every share sold now. */
  exit: {
    foldTitle: "Cost of selling, by share sold",
    barNow: "Sellable today",
    barLater: "If this plays out",
    none: "None",
    curveRow: (drop) => `(the Morpho liquidation curve's nearest row: a ${drop} oracle drop)`,
    keySale: "Sale cost",
    keyKept: "Loss on the part kept",
    keyTotal: "Total (the two added)",
    keyNo: "Beyond Pendle's limit: cannot sell now",
    lowest: (v, x) => `Lowest ${v} at x = ${x}`,
    carry: (cash, pt, dur, share, usd) =>
      `Cash earns ${cash} vs the PT's ${pt} a year. Over this ${dur} incident, selling gives up ${share} of the amount sold (${usd} on a full sale): a short incident leaves the chart almost unchanged; a longer one (step 3) moves it.`,
    carryNone: (pt) => `Cash earns at least the PT's ${pt} a year: selling gives up no yield, so the cash yield does not move the chart.`,
    be: "Break-even severity:",
    beStart: "selling starts",
    beCap: "to the pool limit / all",
    beNever: "not on this slider",
    beRange: (lo, hi) => `(slider ${lo} to ${hi})`,
    sell: (p) => `Sell ${p}`,
    xAxis: "Share sold now, x",
    refuses: ["Pendle refuses", "sales this large"],
    aria: (cap) =>
      `Cost of acting against the share sold now: the total (sale cost plus loss on the rest) and the sale cost alone. Pendle quotes up to ${cap}.`,
    tip: (sale, kept, total) => `Sale cost ${sale} + loss kept ${kept} = ${total}`,
    interp: "Slippage between two quoted sizes is interpolated.",
  },

  /* Layers display in the explainer's propagation form: "Layer n · name", a state badge, the layer's text. */
  layers: {
    head: (n, name) => `Layer ${n} · ${name}`,
    position: "Your position",
    state: {
      origin: "Origin",
      hit: "Affected",
      unchanged: "Unchanged",
      not_applicable: "Not applicable",
      not_modelled: "Not modelled",
      unknown: "Unknown",
    },
  },

  /* "How it spreads": RiskModel.propagation's steps in causal order (guide section 6). */
  spread: {
    title: (n) => `How it spreads, step by step (${n})`,
    input: "your input",
  },

  /* Header inputs of the PT view (guide 3b, to-do 8): the position size and the cash yield, the manager's two
     assumptions. */
  size: {
    label: "Position size (USD)",
    assumed: (g, source) => `<span class="asm" title="${source}">assumed</span> ${g}`,
    typed: "your input",
    onChain: (g) => `read on chain ${g}`,
    altLabel: (g) => `Cash earns (if sell), % APY ${g}`,
    line: (units, price, share, cap) => `${units} PT at ${price}; sellable now: ${share} (${cap} pool limit).`,
    editHint: "Size of a real borrower, read on chain: pick “PT held outright” or the market-average preset to set your own.",
    editHintWallet: "Size of this wallet's position, read on chain.",
  },

  /* Wallet (guide 3b, to-do 10): an address whose position is read on chain; never typed-in numbers. */
  wallet: {
    label: "Wallet (optional)",
    placeholder: "0x… a borrower of this market, or a wallet read on chain",
    add: "+ Wallet (optional)",
    optBorrower: (coll, ltv) => `borrower of this market · collateral ${coll} · LTV ${ltv}`,
    optWallet: "wallet read on chain",
    invalid: "Not an Ethereum address (0x and 40 hexadecimal characters).",
    notRead: (a) =>
      `Not read on chain: rerun <span class="mono">python3 onchain_positions.py --wallet ${a}</span>, then the export.`,
    noPT: (block) => `This wallet holds no PT-sUSDe in the wallet or in this Morpho market at block ${block}.`,
    found: (labels, block, g) => `Read on chain at block ${block} ${g}: ${labels}.`,
  },

  /* The real-borrower presets are someone else's position, read on chain. */
  position: {
    notYours: (label) => `Position: ${label}. A real borrower of this market, read on chain, not your position.`,
    wallet: (label, block) => `Position: ${label}, read on chain at block ${block}.`,
    realTag: "Real borrower, not your position",
    walletTag: "Your wallet, read on chain",
    holding: "PT holding type",
  },

  /* Vault view (second view; FRONTEND_VAULT_GUIDE.md). The sentences follow the backend's wording
     (vault_pipeline.sentence), so at the default severity and amount they equal inc.decision_text.text. */
  vault: {
    addrLabel: "Vault address",
    pick: "Vaults in the list…",
    groupFull: "Analysed",
    groupOther: "Listed, not analysed",
    amountLabel: "Amount invested (your input)",
    altLabel: "Alternative yield, % APY",
    q1: "Which incident?",
    hint: "Every number assumes the incident has happened. Pick the incident, then how bad.",
    groups: {
      credit: "Credit incidents (a collateral or underlying fails)",
      issuer: "Vault asset issuer fails",
      run: "Morpho liquidity incident",
      none: "Not analysed",
    },
    q2: (sym) => `How much does ${sym} lose?`,
    sevNote: (beFree, beForced) =>
      beFree === null
        ? "Withdrawing does not pay at any severity on this slider."
        : `Withdrawing the free part pays once it loses more than ${beFree}` +
          (beForced !== null && beForced !== beFree ? `; forcing out the rest from ${beForced}.` : "."),
    anchors: "Ticks: historical anchors.",
    notFound:
      "This vault is not in the analysed list. Add it to sample_data/rockawayx_vaults.csv and run vault_pipeline.py.",
    notCovered: (name, note) => `${name}: ${note}. No numbers for this vault.`,
    above: (total, cur) => `Amount above the vault's total assets (${total} ${cur}): computed for the whole vault.`,
    chainHead: "Dependency mapping",
    /* Edge labels of the vault graph, by dependency_edges[].type (backend). */
    edge: {
      settlement: "settles on",
      adapter: "adapter",
      allocation: "lends on",
      collateral: "collateral",
      issuer: "issued by",
      underlying: "underlying",
      asset: "vault asset",
    },
    onPath: "on this incident's path",
    badge: {
      STAY: "Stay",
      EXIT: "Exit",
      EXIT_PARTIAL: (amt) => `Exit ${amt}`,
      REVIEW: "Review",
    },
    sub: {
      EXIT_PARTIAL: (locked, cur) => `${locked} ${cur} cannot be withdrawn now`,
      REVIEW: "withdrawing does not help",
    },
    lbl: (sym, sev) => `If ${sym} loses ${sev}`,
    assumes: "Every number assumes the incident has happened, at the severity on the slider.",
    cur: (c) => `Amounts in ${c}.`,
    runOpt: "Other depositors withdraw first",
    barStay: "Stay",
    barExit: "Exit now",
    keyLoss: "Loss",
    keyCost: "Cost of exiting (yield given up, penalty)",
    sIssuer: (name, sev, loss, cur) =>
      `If ${name} loses ${sev}, every depositor loses ${loss} ${cur}. Withdrawing returns ${name}, so it does not remove this risk; only swapping out of ${name} does, at a cost not measured here.`,
    sStay: (name, sev, loss, cur, L, carry) =>
      `If ${name} loses ${sev}, staying loses ${loss} ${cur} (${L} of the deposit), less than the cost of exiting (${carry} of the amount withdrawn: yield given up). `,
    sStayBe: (name, be) => `Exiting pays once ${name} loses more than ${be}.`,
    sNever: "Exiting does not pay at any severity.",
    sExit: (name, sev, loss, cur, L, amt, cost) =>
      `If ${name} loses ${sev}, staying loses ${loss} ${cur} (${L} of the deposit); exiting ${amt} now costs ${cost} ${cur}`,
    sPenalty: " including the force-deallocation penalty",
    sLocked: (amt, cur) => ` ${amt} ${cur} cannot be withdrawn now.`,
    sExitBe: (name, be) => ` Exiting pays once ${name} loses more than ${be}.`,
    sEarly: (f) => ` Act early: if all depositors withdrew, only ${f} of the vault could leave without penalty.`,
    runHead: "If other depositors withdraw first",
    runSlider: "Share of the free liquidity other depositors take first",
    runAt: (p) => `If others take ${p} first, for your amount:`,
    runWhole: "For the whole vault, at the default severity:",
    runCols: ["Others take", "Free now", "With penalty", "Locked", "Loss if locked"],
    runNote: (worst, sev) =>
      worst
        ? `Loss on the locked part if ${worst} hits at ${sev}.`
        : "No analysed credit incident: the locked part carries no modelled loss.",
    issuerNote: "Second-order effects on borrowers (their debt is in the same asset) are not modelled.",
    assumption: (alt) =>
      `Alternative yield ${alt} a year (your assumption); the yield given up is counted over the incident's duration, set in step 3.`,
    /* Duration of a vault incident (guide 3, "Timeline"). */
    dur: {
      recWhy: "Whether the token comes back after the incident is your assumption; liquidations during it stay.",
      noRec: "This incident has one loss grid: recovering does not change it.",
      switchAt: (dur) => `oracle switch ${dur}`,
      chartTitle: "Loss if staying, by how long the incident lasts",
      chartNote: (cur) =>
        `Amounts in ${cur}. Held constant over the incident: the vault's allocations, its market liquidity and the yields.`,
    },
    verdictWord: { STAY: "Stay", EXIT: "Exit", EXIT_PARTIAL: "Exit part", REVIEW: "Review" },
    /* Details under the vault card (guide section 3). */
    det: {
      exitTitle: "Exit, tranche by tranche",
      trCols: ["Tranche", "Amount", "Unit cost", "Now"],
      free: "Free now (idle and the liquidity market)",
      forced: "With penalty (forceDeallocate from other markets)",
      locked: "Locked (lent out, no liquidity)",
      out: "withdraw",
      stays: "keep",
      cannot: "cannot leave now",
      stay: "Loss if you stay",
      cost: "Cost of exiting now",
      kept: "Loss still kept",
      avoided: "Loss avoided by exiting",
      penalty: (p) => `Force-deallocation penalty ${p} (read on chain).`,
      all: (free, forced) =>
        `If all depositors withdrew, ${free} of the vault could leave without penalty and ${forced} more with it.`,
      otherAmount: "Another amount, same incident",
      sensDefaults: (alt, hz, v) =>
        `Computed at the vault's defaults (alternative yield ${alt}, ${hz} days, the loss stays), where the answer is ${v}: the model's sensitivity takes no other inputs.`,
      lossTitle: (sym) => `Vault loss by how much ${sym} loses`,
      gridAria: (n) => `Vault loss at ${n} severities from 0.5% to 100%, on the slider's log scale; the current severity marked.`,
      gridTicks: [0.005, 0.01, 0.05, 0.1, 0.3, 1],
      gridNote: (low) =>
        `Share of the vault's assets lost (bad debt of every real borrower, taken pro rata by the lenders).${low ? " Dashed: if the lending oracles do not follow the shock." : ""}`,
      pmCols: ["Shock", "Collateral", "Oracle follows", "Market bad debt", "Vault loss"],
      yes: "yes",
      no: "no",
      pmNote: (cur) => `Each market at the historical shocks of the slider's anchors; amounts in ${cur}.`,
      mkTitle: (n) => `Markets the vault lends on (${n})`,
      mkCols: ["Collateral", "Type", "Allocation", "Of vault", "Of market", "Oracle", "Borrowers", "Max LTV / limit", "Debt within 1% of liquidation"],
      notAnalysed: "(not analysed)",
      follows: (mkt, und) =>
        `(follows ${[mkt ? "its market" : null, und ? "the underlying" : null].filter(Boolean).join(" and ") || "neither"})`,
      mkNote: (cur) => `Read on chain at the vault's block; amounts in ${cur}. The affected markets of this incident are highlighted.`,
    },
  },

  /* Off-chain dependencies from the issuer's documents (d.offchain; guide section 8). */
  offchain: {
    title: "Off-chain (issuer documents)",
    card: (n) => `${n} off-chain relations from Ethena's documents`,
    issuer: "Issuer",
    seeEthena: "The same issuer documents as Ethena.",
    openEthena: "Open Ethena's off-chain relations",
    source: "source",
    thirdParty: "third-party source",
    rechecked: (day) => `quote re-checked ${day}`,
    notRechecked: "not re-checked: the source page refused the checker",
    notFound: "not found on the page at the last check, so not shown as a quote",
    kinds: {
      issuer: "Issuer",
      custodian: "Custodians",
      counterparty: "Counterparties",
      exchange: "Hedging exchanges",
      reserve_asset: "Reserve assets",
      reserve_fund: "Reserve fund",
      attestation: "Attestations",
      audit: "Audits",
      governance: "Governance",
      oracle: "Oracles",
      redemption: "Redemption",
      regulator: "Regulators",
      admin_role: "Admin roles",
      underlying: "Underlying",
      infrastructure: "Infrastructure",
      originator: "Originators",
      legal_structure: "Legal structure",
      parent_credit: "Parent credit",
      service_provider: "Service providers",
      reserve_custodian: "Reserve custodians",
      underlying_asset: "Underlying assets",
      borrower: "Borrowers",
      asset_manager: "Asset managers",
      market_maker: "Market makers",
      bridge: "Bridges",
      other: "Other",
    },
  },
};
