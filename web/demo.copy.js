/* User-facing strings of the demo page, as one COPY object (web/CLAUDE.md, "Files").
   Strings move here step by step: a sentence that is new or being changed comes here; the others move when their
   render function is next edited. Values are strings, or small functions that only place numbers into a sentence. */
const COPY = {
  /* Incidents are set by hand: there is no detector (team decision). The two examples are invented quick picks. */
  examples: {
    feedLabel: "Example incidents:",
    feedFromData: (n) => `From the data: ${n}`,
    feedShow: (n) => `${n} invented ${n === 1 ? "example" : "examples"}`,
    feedNone: "None",
    protoNote: "Incidents are set by hand. The examples are invented quick picks.",
    tag: "Example",
    suffix: " · invented example",
    band: "Example",
    countNote: (n) =>
      `${n} invented ${n === 1 ? "example" : "examples"} to start from. Any other choice is a what-if test.`,
    noneNote: "Pick any dependency to run a what-if test.",
    group: "Invented examples",
    drawerRow: "Example",
    drawerSuffix: " (invented example, set by hand)",
    sevNote: (v) => `Example value: ${v}. Move right to test it getting worse.`,
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
