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
    drawerRow: "Past pattern",
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
