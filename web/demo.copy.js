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
