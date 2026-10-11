/* User-facing strings of the demo page, as one COPY object (web/CLAUDE.md, "Files").
   Strings move here step by step: a sentence that is new or being changed comes here; the others move when their
   render function is next edited. Values are strings, or small functions that only place numbers into a sentence. */
const COPY = {
  /* Step hints. An incident is set by hand or loaded from a real past event (no detector, no invented incidents). */
  steps: {
    hint: "Pick any dependency, then set the failure and how bad by hand, or load a past event at the top right.",
  },

  /* Past events (d.past_incidents, guide section 3c): a pattern applied to this position, not something that
     happened to it. */
  past: {
    tag: "Past pattern",
    band: (label) => `Pattern from ${label}`,
    banner: (label, what, source) =>
      `<b>Pattern from ${label}</b>: ${what}, applied to this position. It did not happen to PT-sUSDe. ${source}. Moving the dependency, the failure or the severity turns it into a what-if test.`,
    sevNote: (v) => `Severity of the past event: ${v}. Move the slider to turn it into a what-if test.`,
    lasting: (dur, recovered) => `, lasting ${dur}${recovered ? ", then recovered" : ""}`,
    drawerRow: "Past pattern",
  },

  /* "What would change the answer" (RiskModel.sensitivity, guide section 5): one assumption at a time replaced by
     its stated alternative, the decision rerun. */
  sens: {
    title: "What would change the answer",
    hinges: (alt, grade, verdict) => `The answer hinges on: ${alt} (grade ${grade}) → ${verdict}.`,
    robust: "No tested assumption changes the answer.",
    cols: ["If instead", "Grade", "Answer"],
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
    source: (src) => `Losses, the decision and these texts come from the backend model (RiskModel.decideAtDuration, decisionText). ${src}`,
  },

  /* Time rail: how long the incident lasts (guide sections 5b and 6). Event texts are RiskModel.propagationEvents'
     own; the recovers reason is RiskModel.recoveryToggle's. */
  rail: {
    lasted: (dur) => `The incident has lasted <b>${dur}</b>`,
    play: "Play",
    pause: "Pause",
    after: "After the incident",
    recovers: "Recovers",
    stays: "Stays",
    stepLine: (dur, rec) =>
      `Lasts ${dur}${rec === null ? "" : rec ? ", recovers" : ", stays"}: drag the time rail on the chain below.`,
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

  /* "How it spreads": RiskModel.propagation's steps in causal order (guide section 6). */
  spread: {
    title: (n) => `How it spreads, step by step (${n})`,
    input: "your input",
  },

  /* The real-borrower presets are someone else's position, read on chain. */
  position: {
    notYours: (label) => `Position: ${label}. A real borrower of this market, read on chain, not your position.`,
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
    hzLabel: "Horizon, days",
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
    anchors: "Ticks: historical anchors (C).",
    notFound:
      "This vault is not in the analysed list. Add it to sample_data/rockawayx_vaults.csv and run vault_pipeline.py.",
    notCovered: (name, note) => `${name}: ${note}. No numbers for this vault.`,
    above: (total, cur) => `Amount above the vault's total assets (${total} ${cur}): computed for the whole vault.`,
    chainHead: "What this deposit depends on",
    /* Edge labels of the vault graph; each edge is read from a data field (see vault.js, graphEdges). */
    edge: {
      chain: "settles on",
      adapter: "adapter",
      market: "lends on",
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
    runCols: ["Others take", "Free now", "With penalty", "Locked", "Loss if locked"],
    runNote: (worst, sev) =>
      worst
        ? `Loss on the locked part if ${worst} hits at ${sev}.`
        : "No analysed credit incident: the locked part carries no modelled loss.",
    issuerNote: "Second-order effects on borrowers (their debt is in the same asset) are not modelled.",
    assumption: (alt, hz) => `Alternative yield ${alt} a year, horizon ${hz} days: assumptions (D).`,
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
      other: "Other",
    },
  },
};
