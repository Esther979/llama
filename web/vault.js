/* Vault view, the page's second view (FRONTEND_VAULT_GUIDE.md). Input: vault address + amount invested; then the
   incident and how bad; out: a verdict badge, the backend's sentence, loss if staying versus cost of exiting, and the
   dependency chain. Reads window.VAULTS and RiskModel only: never window.DASHBOARD or the PT view's state. Every
   number comes from VAULTS or from RiskModel.vaultDecideAt / vaultRun; no probability. */
(function () {
  const V = window.VAULTS,
    RM = window.RiskModel,
    C = COPY.vault;
  const $ = (s) => document.querySelector(s);

  /* ---- page switch: Position (PT) | Vaults. Each view keeps its own state; the PT drawer closes on switching. */
  function showPage(k) {
    const vault = k === "vault";
    document.querySelectorAll("[data-page]").forEach((b) => b.setAttribute("aria-pressed", b.dataset.page === k));
    $("#hdr-pt").hidden = $("#view-pt").hidden = vault;
    $("#hdr-vault").hidden = $("#view-vault").hidden = !vault;
    $("#drawer").hidden = true;
    document.body.classList.remove("drawer-open");
    if (vault) render();
  }
  document.querySelectorAll("[data-page]").forEach((b) => b.addEventListener("click", () => showPage(b.dataset.page)));
  if (!V || !RM || !RM.vaultDecideAt) {
    document.querySelector('[data-page="vault"]').disabled = true;
    return;
  }

  /* ---- formats. Money as in the PT view (3.0k, 456k, 3.00M), without "$": vault amounts are in the vault's
     currency, written after the number. Fractions as the backend writes them ("84.14%"). The amount field keeps the
     full number the manager typed (full). */
  const money = (v) => {
    const a = Math.abs(v);
    return a >= 999500
      ? (v / 1e6).toFixed(2) + "M"
      : a >= 1e4
        ? Math.round(v / 1e3) + "k"
        : a >= 1e3
          ? (v / 1e3).toFixed(1) + "k"
          : String(Math.round(v));
  };
  const full = (v) => Math.round(v).toLocaleString("en-US");
  /* the amount field reads and shows k / m units as the PT view's size field: 3,000 = 3k, 3,000,000 = 3m */
  const unitAmt = (v) => {
    const a = Math.abs(v),
      t = (x) => String(+x.toFixed(3));
    return a >= 1e6 ? t(v / 1e6) + "m" : a >= 1e3 ? t(v / 1e3) + "k" : t(v);
  };
  const amtOf = (t) => {
    const m = String(t).trim().replace(/[\s,_']/g, "").match(/^(\d*\.?\d+)([kKmM]?)$/);
    return m ? +m[1] * { "": 1, k: 1e3, K: 1e3, m: 1e6, M: 1e6 }[m[2]] : null;
  };
  const frac = (v) =>
    (Math.abs(v) >= 0.01 || v === 0 ? (v * 100).toFixed(2) : String(+(v * 100).toPrecision(3))) + "%";
  const gr = (g) => (/^[ABCD]$/.test(g || "") ? `<span class="gr ${g}">${g}</span>` : "");
  const short = (a) => (a && a.length > 14 ? a.slice(0, 6) + "…" + a.slice(-4) : a || "");
  const num = (t, comma) => {
    const s = String(t).trim().replace(/[\s_']/g, "");
    const v = parseFloat(comma ? s.replace(",", ".") : s.replace(/,/g, ""));
    return isFinite(v) ? v : null;
  };

  /* ---- data */
  const REPORT = V.report.vaults || [];
  const DET = {};
  Object.keys(V.details || {}).forEach((a) => (DET[a.toLowerCase()] = V.details[a]));
  const BELEM = "0xd6d4b804014ef27836dbe9f8f6bf6c71251548ec";
  const firstFull = REPORT.find((x) => x.coverage === "full");
  const TYPES = {
    issuer_default: "credit",
    depeg: "credit",
    pt_market_dip: "credit",
    asset_issuer: "issuer",
    liquidity_run: "run",
  };
  const groupOf = (i) => (i.analyzed === false ? "none" : TYPES[i.type] || "credit");
  const defaultInc = (v) =>
    v.worst_incident ||
    ((v.incidents.find((i) => groupOf(i) === "credit") ||
      v.incidents.find((i) => groupOf(i) === "issuer") ||
      v.incidents.find((i) => groupOf(i) === "run") ||
      {}).key);

  /* ---- state of this view only */
  const VS = {
    addr: REPORT.some((x) => x.vault_address.toLowerCase() === BELEM) ? BELEM : firstFull ? firstFull.vault_address : "",
    amount: 10000000,
    alt: null,
    /* how long the incident lasts (guide 3, "Timeline"): replaces the horizon, since the yield given up is counted
       over the incident; default the vault's horizon (exit.horizon_days), the loss stays */
    hours: null,
    recovers: false,
    inc: null,
    sev: null,
    display: "list",
    open: {},
    /* liquidity run: share of the free liquidity other depositors take first */
    share: 0.5,
  };
  const entry = () => REPORT.find((x) => x.vault_address.toLowerCase() === VS.addr.trim().toLowerCase()) || null;
  const detail = () => {
    const e = entry();
    return e && e.coverage === "full" ? DET[e.vault_address.toLowerCase()] || null : null;
  };
  function resetForVault() {
    const v = detail();
    VS.inc = v ? defaultInc(v) : null;
    VS.sev = null;
    VS.alt = v ? v.exit.alt_apy : null;
    VS.hours = v ? v.exit.horizon_days * 24 : null;
    VS.recovers = false;
  }

  /* ---- severity slider: fractions 0.5% .. 100% on a log scale, positions 0..1000 */
  const SMIN = 0.005,
    SMAX = 1,
    LOGR = 1000;
  const sevPos = (s) => (Math.log(Math.max(SMIN, s) / SMIN) / Math.log(SMAX / SMIN)) * LOGR;
  const posSev = (p) => Math.round(SMIN * Math.pow(SMAX / SMIN, p / LOGR) * 1e4) / 1e4;

  /* ---- the decision and its sentence (the backend's wording, numbers from r only) */
  function decide(v, inc, amt) {
    return RM.vaultDecideAt(inc, v.exit, amt, VS.sev === null ? inc.default_severity : VS.sev, VS.alt, null, false, VS.hours, VS.recovers);
  }
  function sentence(inc, ex, r) {
    const cur = ex.currency || "",
      name = inc.symbol || inc.key;
    if (inc.type === "asset_issuer") return C.sIssuer(name, frac(r.severity), money(r.loss_if_stay_usd), cur);
    if (r.verdict === "STAY")
      return (
        C.sStay(name, frac(r.severity), money(r.loss_if_stay_usd), cur, frac(r.L), frac(r.carry_cost)) +
        (r.severity_break_even_free !== null ? C.sStayBe(name, frac(r.severity_break_even_free)) : C.sNever)
      );
    let t =
      C.sExit(name, frac(r.severity), money(r.loss_if_stay_usd), cur, frac(r.L), money(r.exit_usd), money(r.exit_cost_usd)) +
      (r.exit_usd > r.free_usd + 1e-9 && r.penalty > 0 ? C.sPenalty : "") +
      "." +
      (r.locked_usd > 1e-9 ? C.sLocked(money(r.locked_usd), cur) : "") +
      (r.severity_break_even_free !== null ? C.sExitBe(name, frac(r.severity_break_even_free)) : "");
    if (ex.vault_free_fraction < 0.999) t += C.sEarly(frac(ex.vault_free_fraction));
    return t;
  }

  /* ---- render */
  let LAST = null;
  function bar(name, segs, val, max) {
    return `<span class="bn">${name}</span><span class="track">${segs
      .filter((s) => s[1] > 0)
      .map((s) => `<i class="${s[0]}" style="width:${Math.max(0.5, (s[1] / max) * 100)}%"></i>`)
      .join("")}</span><span class="bv">${val}</span>`;
  }
  /* The incident's path and the links between chain items come from the backend (guide section 3): items carry an
     id, details[a].dependency_edges links them ({from, to, type, grade, evidence}), inc.chain_items lists the ids on
     the selected incident's path. An edge is on the path when both its ends are. Nothing is derived by the page. */
  const pathOf = (inc) => new Set((inc && inc.chain_items) || []);
  function renderChain(v, inc) {
    const cur = v.exit.currency || "",
      on = pathOf(inc);
    $("#v-chainHead").textContent = C.chainHead;
    document.querySelectorAll("[data-vdisp]").forEach((b) => b.setAttribute("aria-pressed", b.dataset.vdisp === VS.display));
    if (VS.display === "graph") return renderGraph(v, inc);
    $("#v-chain").innerHTML = (v.dependency_chain || [])
      .map(
        (L) => `<div class="vl"><span class="vn">${L.layer}</span><div><h3>${L.name}</h3><ul>${L.items
          .map((it) => {
            const hot = on.has(it.id);
            const addr = /^0x[0-9a-f]{40}$/i.test(it.address || "")
              ? ` <a class="mono" href="https://etherscan.io/address/${it.address}" target="_blank" rel="noopener">${short(it.address)}</a>`
              : "";
            return `<li class="${hot ? "on" : ""}" data-vid="${it.id}"${hot ? ` title="${C.onPath}"` : ""}><b>${it.label}</b> ${gr(it.evidence)}${addr}${it.allocation ? ` · ${money(it.allocation)} ${cur}` : ""}${it.detail ? `<span class="note">${it.detail}</span>` : ""}${offchain(v, it)}</li>`;
          })
          .join("")}</ul></div></div>`,
      )
      .join("");
  }
  /* Layer-6 items with offchain (a token symbol) open details[a].offchain[symbol]: issuer, summary, relations grouped
     by kind, each with its source link and quote (grade D), the quote's check state as in the PT view's drawer. */
  function offchain(v, it) {
    const o = it.offchain && v.offchain && v.offchain[it.offchain],
      O = COPY.offchain;
    if (!o || !o.relations) return "";
    const groups = {};
    o.relations.forEach((r) => (groups[r.kind] = groups[r.kind] || []).push(r));
    const day = (t) => (t ? new Date(t).toLocaleString("en-GB", { timeZone: "UTC", day: "numeric", month: "short" }) : "");
    const rel = (r) => {
      const e = r.evidence || {};
      const quote = !e.quote
        ? ""
        : e.quote_found === false
          ? `<span class="note">${O.notFound}</span>`
          : `<q class="oq">${e.quote}</q><span class="note">${e.quote_found === true ? O.rechecked(day(e.checked_at)) : O.notRechecked}</span>`;
      return `<li><b>${r.entity}</b>: ${r.relation} ${gr(e.grade)}${e.official === false ? ` <span class="tp">${O.thirdParty}</span>` : ""}${e.url ? ` · <a class="osrc" href="${e.url}" target="_blank" rel="noopener">${O.source}</a>` : ""}${quote}</li>`;
    };
    const id = "v-off-" + it.offchain;
    return `<details class="offc" id="${id}" ${VS.open[id] ? "open" : ""}><summary>${O.title}: ${Object.keys(groups)
      .map((k) => `${O.kinds[k] || k} ${groups[k].length}`)
      .join(" · ")}</summary><div><p class="note">${O.issuer}: <b>${o.issuer}</b>. ${o.summary || ""}</p>${Object.keys(groups)
      .map((k) => `<h4>${O.kinds[k] || k}</h4><ul>${groups[k].map(rel).join("")}</ul>`)
      .join("")}</div></details>`;
  }
  /* ---- graph display: one node per chain item, the edges of dependency_edges */
  let GRAPH = null;
  function renderGraph(v, inc) {
    const cur = v.exit.currency || "",
      hot = pathOf(inc),
      ids = new Set((v.dependency_chain || []).flatMap((L) => L.items.map((it) => it.id))),
      edges = (v.dependency_edges || []).filter((e) => ids.has(e.from) && ids.has(e.to));
    /* layer 6 in the order of the layer-5 item it links to (others, e.g. the vault-asset issuer, first), so each sits
       under what it backs */
    const l5 = ((v.dependency_chain || []).find((L) => L.layer === 5) || { items: [] }).items.map((it) => it.id);
    const col6 = (it) => {
      const e = edges.find((x) => x.from === it.id && l5.includes(x.to));
      return e ? l5.indexOf(e.to) : -1;
    };
    let h = '<svg id="v-edges" aria-hidden="true"></svg>';
    (v.dependency_chain || []).forEach((L) => {
      const order = L.items.slice();
      if (L.layer === 6) order.sort((a, b) => col6(a) - col6(b));
      h += `<div class="band"><div class="lname"><b>${L.layer}</b>${L.name}</div><div class="grow">${order
        .map((it) => {
          const on = hot.has(it.id);
          return `<div class="node ${it.evidence === "D" ? "doc" : ""} ${on ? "hot" : ""}" data-vg="${it.id}"${on ? ` title="${C.onPath}"` : ""}><span class="nm">${it.label}</span><span class="sub">${gr(it.evidence)}${it.allocation ? ` ${money(it.allocation)} ${cur}` : ""}</span></div>`;
        })
        .join("")}</div></div>`;
    });
    $("#v-chain").innerHTML = `<div class="gscroll"><div class="graph vgraph" id="v-graph-box">${h}<div id="v-elabels"></div></div></div>`;
    GRAPH = { edges, hot };
    LAST.graph = GRAPH;
    paintGraph();
  }
  /* Edges drawn after layout, from the node boxes; redrawn on resize. Marker ids differ from the PT graph's. */
  function paintGraph() {
    const g = $("#v-graph-box"),
      svg = $("#v-edges");
    if (!g || !svg || !GRAPH) return;
    const R = g.getBoundingClientRect();
    const node = (id) => [...g.querySelectorAll("[data-vg]")].find((el) => el.dataset.vg === id);
    const box = (id) => {
      const el = node(id);
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return { x: r.left - R.left + r.width / 2, y: r.top - R.top + r.height / 2, w: r.width, h: r.height };
    };
    const clip = (a, b, pad) => {
      const dx = b.x - a.x,
        dy = b.y - a.y,
        s = Math.min(dx ? (a.w / 2 + pad) / Math.abs(dx) : 1e9, dy ? (a.h / 2 + pad) / Math.abs(dy) : 1e9);
      return [a.x + dx * s, a.y + dy * s];
    };
    /* the gutter: halfway between the layer names and the first column of nodes */
    const gutter = () => {
      const first = g.querySelector(".grow"),
        r = first.getBoundingClientRect();
      return r.left - R.left + 7;
    };
    const layerOf = (id) => {
      const el = node(id);
      return el ? [...g.querySelectorAll(".band")].indexOf(el.closest(".band")) : 0;
    };
    let cold = "",
      hotL = "",
      labs = "";
    GRAPH.edges.forEach((e) => {
      const a = box(e.from),
        b = box(e.to);
      if (!a || !b) return;
      const on = GRAPH.hot.has(e.from) && GRAPH.hot.has(e.to),
        cls = `class="e ${e.grade === "D" ? "doc" : ""} ${on ? "hot" : ""}" marker-end="url(#${on ? "vah" : "van"})"`,
        span = Math.abs(layerOf(e.from) - layerOf(e.to));
      let ln, lx, ly;
      if (span > 1) {
        /* across layers: out of the node's left side, along the gutter, into the target's left side */
        const gx = gutter(),
          xa = a.x - a.w / 2,
          xb = b.x - b.w / 2 - 6;
        ln = `<path d="M${xa} ${a.y}H${gx}V${b.y}H${xb}" ${cls}/>`;
        lx = gx;
        ly = b.y + b.h / 2 + 12;   /* under the target, beside the gutter: clear of the nodes it passes */
      } else {
        const [x1, y1] = clip(a, b, 1),
          [x2, y2] = clip(b, a, 6);
        ln = `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" ${cls}/>`;
        lx = (x1 + x2) / 2;
        ly = (y1 + y2) / 2;
      }
      if (on) {
        hotL += ln;
        labs += `<span class="elab hot ${span > 1 ? "side" : ""}" style="left:${lx}px;top:${ly}px" title="${String(e.evidence || "").replace(/"/g, "&quot;")} (${e.grade})">${C.edge[e.type] || e.type}</span>`;
      } else cold += ln;
    });
    const mk = (id, v) =>
      `<marker id="${id}" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L10 5L0 10z" style="fill:var(${v})"/></marker>`;
    svg.innerHTML = "<defs>" + mk("van", "--line-strong") + mk("vah", "--crit") + "</defs>" + cold + hotL;
    $("#v-elabels").innerHTML = labs;
  }
  /* ---- details under the card (guide section 3), each in a fold that keeps its open state in VS.open */
  const fold = (id, title, body) =>
    `<details id="${id}" ${VS.open[id] ? "open" : ""}><summary>${title}</summary><div>${body}</div></details>`;
  const vword = (v) => C.verdictWord[v] || v;
  function details(v, inc, r, amt) {
    const ex = v.exit,
      cur = ex.currency || "",
      D = C.det;
    /* exit, tranche by tranche: what this amount can take out now and at what unit cost */
    const takeFree = r.L > r.carry_cost && r.verdict !== "REVIEW",
      takeForced = r.L > r.carry_cost + r.penalty && r.verdict !== "REVIEW";
    const tr = (cls, name, amt2, cost, out) =>
      `<tr class="${cls}"><td>${name}</td><td>${money(amt2)}</td><td>${cost}</td><td>${out}</td></tr>`;
    const exitBody = `<div class="tw"><table class="vtr"><thead><tr>${D.trCols.map((h) => `<th>${h}</th>`).join("")}</tr></thead><tbody>${
      tr("free", D.free, r.free_usd, frac(r.carry_cost), r.free_usd > 0 ? (takeFree ? D.out : D.stays) : "–") +
      tr("forced", D.forced, r.forced_usd, frac(r.carry_cost + r.penalty), r.forced_usd > 0 ? (takeForced ? D.out : D.stays) : "–") +
      tr("locked", D.locked, r.locked_usd, "–", r.locked_usd > 0 ? D.cannot : "–")
    }</tbody></table></div>
    <dl><dt>${D.stay}</dt><dd>${money(r.loss_if_stay_usd)} ${cur} (${frac(r.L)})</dd><dt>${D.cost}</dt><dd>${money(r.exit_cost_usd)} ${cur}</dd><dt>${D.kept}</dt><dd>${money(r.loss_kept_usd)} ${cur}</dd><dt>${D.avoided}</dt><dd>${money(r.avoided_usd)} ${cur}</dd></dl>
    <p class="note">${D.penalty(frac(ex.force_deallocate_penalty))} ${D.all(frac(ex.vault_free_fraction), frac(ex.vault_forced_fraction))} ${gr((ex.evidence.tranches || {}).grade)} ${(ex.evidence.tranches || {}).source || ""}</p>`;
    /* what would change the answer (RiskModel.vaultSensitivity): it takes no alternative yield or duration, so it is
       computed at the vault's defaults; say so when the page's inputs differ */
    const sv = RM.vaultSensitivity(inc, ex, amt, r.severity);
    LAST.sens = sv;
    const srow = (c) =>
      `<tr class="${sv.weakest && c === sv.weakest ? "best" : ""} ${c.flips ? "flip" : ""}"><td>${c.alternative}</td><td>${gr(c.grade)}</td><td>${vword(c.verdict)}${c.flips ? ` <span class="note">(${COPY.sens.flips})</span>` : ""}</td></tr>`;
    const own = sv.candidates.filter((c) => !c.comparison),
      cmp = sv.candidates.filter((c) => c.comparison);
    const atDefault = VS.alt === ex.alt_apy && VS.hours === ex.horizon_days * 24 && !VS.recovers;
    const sensBody = `<p class="sens-head">${sv.weakest ? COPY.sens.hinges(sv.weakest.alternative, sv.weakest.grade, vword(sv.weakest.verdict)) : COPY.sens.robust}</p>
    <div class="tw"><table class="sens"><thead><tr>${COPY.sens.cols.map((h) => `<th>${h}</th>`).join("")}</tr></thead><tbody>${own.map(srow).join("")}${
      cmp.length ? `<tr class="grp"><th colspan="3">${D.otherAmount}</th></tr>${cmp.map(srow).join("")}` : ""
    }</tbody></table></div>${atDefault ? "" : `<p class="note">${D.sensDefaults(frac(ex.alt_apy), ex.horizon_days, vword(sv.verdict))}</p>`}`;
    /* loss by severity: inc.severity_grid on the slider's log scale, the current severity marked; then each market at
       the historical shocks (no probability) */
    const grid = inc.severity_grid || [],
      X = (sv2) => (sevPos(sv2) / LOGR) * 1000,
      top = Math.max(1e-9, ...grid.map((g) => g.L_high)),
      Y = (l) => 96 - (l / top) * 88;
    const lineOf = (k) => grid.map((g) => `${X(g.severity).toFixed(1)},${Y(g[k]).toFixed(2)}`).join(" ");
    const lowDiffers = grid.some((g) => Math.abs(g.L_low - g.L_high) > 1e-12);
    const outs = (inc.outcomes || []).filter((o) => o.shock != null && (o.per_market || []).length);
    const lossBody = `<div class="tlbox vgrid"><svg class="tlc" viewBox="0 0 1000 100" preserveAspectRatio="none" role="img" aria-label="${D.gridAria(grid.length)}">${
      lowDiffers ? `<polyline class="tline low" points="${lineOf("L_low")}"/>` : ""
    }<polyline class="tline" points="${lineOf("L_high")}"/><line class="tnow" x1="${X(r.severity)}" x2="${X(r.severity)}" y1="0" y2="100"/></svg>
    <span class="tly" style="top:${Y(top)}%">${frac(top)}</span><span class="tly" style="top:96%">0%</span></div>
    <div class="raxis">${D.gridTicks.map((t) => `<span style="left:${((sevPos(t) / LOGR) * 100).toFixed(3)}%">${frac(t).replace(/\.00%$/, "%")}</span>`).join("")}</div>
    <p class="note">${D.gridNote(lowDiffers)}</p>${
      outs.length
        ? `<div class="tw"><table><thead><tr>${D.pmCols.map((h) => `<th>${h}</th>`).join("")}</tr></thead><tbody>${outs
            .flatMap((o) =>
              o.per_market.map(
                (pm) =>
                  `<tr><td>${frac(o.shock)}</td><td>${pm.collateral}</td><td>${pm.oracle_falls === true ? D.yes : pm.oracle_falls === false ? D.no : "?"}</td><td>${money(pm.market_bad_debt_high)}</td><td>${money(pm.vault_loss_high)}</td></tr>`,
              ),
            )
            .join("")}</tbody></table></div><p class="note">${D.pmNote(cur)}</p>`
        : ""
    }`;
    /* markets the vault lends on */
    const mrow = (m) => {
      const o = m.oracle || {};
      return `<tr class="${(inc.affected_markets || []).includes(m.key) ? "on" : ""}"><td>${m.collateral_symbol || "–"}${m.analyzed === false ? ` <span class="note">${D.notAnalysed}</span>` : ""}</td><td>${m.collateral_type ? m.collateral_type.replace(/_/g, " ") : "–"}</td><td>${money(m.allocation)}</td><td>${frac(m.allocation / v.total_assets)}</td><td>${m.share_of_market != null ? frac(m.share_of_market) : "–"}</td><td>${o.contract_name || o.kind || "–"}${o.kind ? `<span class="note"> ${D.follows(o.tracks_market, o.tracks_underlying)}</span>` : ""}</td><td>${m.n_borrowers ?? "–"}</td><td>${m.max_ltv != null ? frac(m.max_ltv) + " / " + frac(m.lltv) : "–"}</td><td>${m.debt_within_1pct_of_liquidation != null ? money(m.debt_within_1pct_of_liquidation) : "–"}</td></tr>`;
    };
    const mkBody = `<div class="tw"><table class="vmk"><thead><tr>${D.mkCols.map((h) => `<th>${h}</th>`).join("")}</tr></thead><tbody>${(v.markets || []).map(mrow).join("")}</tbody></table></div><p class="note">${D.mkNote(cur)}</p>`;
    /* the markets table is wide: it goes under the chain, in the wide column */
    $("#v-more").innerHTML = fold("v-d-mk", D.mkTitle(v.markets.length), mkBody);
    return (
      fold("v-d-exit", D.exitTitle, exitBody) +
      fold("v-d-sens", COPY.sens.title, sensBody) +
      fold("v-d-loss", D.lossTitle(inc.symbol || inc.key), lossBody)
    );
  }
  /* ---- duration (guide 3, "Timeline"): a log rail 1 h .. 180 days over the chain, the recovers / stays toggle where
     the incident has grids for both, the summary of RiskModel.vaultTimelineSummary under it, the chart of
     RiskModel.vaultTimeline in a fold. One duration control in this view. */
  const H_MIN = 1,
    H_MAX = 4320,
    hOf = (p) => H_MIN * Math.exp((Math.log(H_MAX / H_MIN) * p) / LOGR),
    pOf = (h) => (Math.log(Math.min(H_MAX, Math.max(H_MIN, h)) / H_MIN) / Math.log(H_MAX / H_MIN)) * LOGR;
  const durText = (h) => {
    const x = h < 48 ? h : h / 24;
    return String(x < 10 ? +x.toFixed(1) : Math.round(x)) + (h < 48 ? " h" : " days");
  };
  function renderDur(v, inc, r, amt) {
    const box = $("#v-rail"),
      T = C.dur,
      R = COPY.rail,
      ex = v.exit;
    box.hidden = !inc || inc.type === "liquidity_run";
    if (box.hidden) return;
    const both = new Set((inc.duration_grids || []).map((g) => g.recovers)).size === 2,
      switches = (inc.duration_grids || []).map((g) => g.from_hours).filter((h) => h > 0);
    const rows = RM.vaultTimeline(inc, ex, amt, r.severity, VS.recovers, VS.alt),
      sum = RM.vaultTimelineSummary(inc, rows),
      vb = (x) => `<span class="vb ${VCLS[x]}">${vword(x)}</span>`;
    LAST.timeline = { rows, sum };
    document.querySelectorAll("#v-rail .rq").forEach((x) => (x.textContent = R.q));
    document.querySelectorAll("#v-rail .rlt").forEach((x) => (x.textContent = R.lasted));
    const di = $("#v-durIn");
    di.title = di.placeholder = R.durHint;
    if (document.activeElement !== di) di.value = durText(VS.hours);
    $("#v-rec").innerHTML = both
      ? `<span class="note">${R.after}</span><span class="mode sm" role="group" aria-label="${R.after}"><button data-vrec="1" aria-pressed="${VS.recovers}">${R.recovers}</button><button data-vrec="0" aria-pressed="${!VS.recovers}">${R.stays}</button></span><span class="note rwhy">${T.recWhy}</span>`
      : `<span class="note rwhy">${T.noRec}</span>`;
    const d = $("#v-dur");
    d.value = pOf(VS.hours);
    d.setAttribute("aria-valuetext", durText(VS.hours));
    $("#v-rmarks").innerHTML = switches
      .map((h) => `<i class="rm ref" style="left:${((pOf(h) / LOGR) * 100).toFixed(3)}%" data-h="${h}"><span>${T.switchAt(durText(h))}</span></i>`)
      .join("");
    $("#v-raxis").innerHTML = R.ticks.map(([h, t]) => `<span style="left:${((pOf(h) / LOGR) * 100).toFixed(3)}%">${t}</span>`).join("");
    $("#v-dsum").innerHTML = sum.duration_matters
      ? sum.changes.map((c) => `<li>${COPY.tl.change(durText(c.to_hours), vb(c.verdict_before), vb(c.verdict_after), c.reason)}</li>`).join("")
      : `<li>${COPY.tl.flat(sum.why_flat)}</li>`;
    /* the chart, on the rail's axis: loss if staying at the model's grid of durations, background by the answer */
    const X = (h) => pOf(h),
      top = Math.max(...rows.map((x) => x.loss_if_stay_usd)),
      Y = (l) => 96 - (top > 0 ? (l / top) * 88 : 0);
    const bands = rows
      .map((x, i) => {
        const x0 = i ? X(x.hours) : 0,
          x1 = i + 1 < rows.length ? X(rows[i + 1].hours) : LOGR;
        return `<rect class="tb ${VCLS[x.verdict]}" x="${x0}" y="0" width="${Math.max(0, x1 - x0)}" height="100"/>`;
      })
      .join("");
    $("#v-tlSum").textContent = T.chartTitle;
    $("#v-tl").innerHTML = `<div class="tlbox"><svg class="tlc" viewBox="0 0 1000 100" preserveAspectRatio="none" role="img" aria-label="${COPY.tl.aria(rows.length)}">${bands}${switches
      .map((h) => `<line class="tref" x1="${X(h)}" x2="${X(h)}" y1="0" y2="100"/>`)
      .join("")}<polyline class="tline" points="${rows.map((x) => `${X(x.hours).toFixed(1)},${Y(x.loss_if_stay_usd).toFixed(2)}`).join(" ")}"/><line class="tnow" x1="${X(VS.hours)}" x2="${X(VS.hours)}" y1="0" y2="100"/></svg>
      <span class="tly" style="top:${Y(top)}%">${money(top)}</span><span class="tly" style="top:96%">0</span></div>
      <div class="raxis">${R.ticks.map(([h, t]) => `<span style="left:${((pOf(h) / LOGR) * 100).toFixed(3)}%">${t}</span>`).join("")}</div>
      <p class="note">${T.chartNote(ex.currency || "")}</p>`;
  }
  const VCLS = { STAY: "stay", EXIT: "cap", EXIT_PARTIAL: "cap", REVIEW: "reduce" };
  function renderRun(v, amt) {
    const ex = v.exit,
      cur = ex.currency || "",
      worst = v.incidents.find((i) => i.key === v.worst_incident) || null;
    const Lw = worst ? RM.vaultDecideAt(worst, ex, amt, null, VS.alt, null, false, VS.hours, VS.recovers).L : 0;
    const rows = [0, 0.5, 1].map((sh) => RM.vaultRun(ex, amt, sh, Lw));
    LAST.run = rows;
    const run = v.incidents.find((i) => i.key === VS.inc) || {},
      note = run.note || "";
    $("#v-decision").innerHTML = `<div class="vband"><span class="lbl">${C.runHead} · ${v.vault_name}</span><p class="why">${
      note.charAt(0).toUpperCase() + note.slice(1)
    }.</p></div><div class="dbody"><div class="tw"><table><thead><tr>${C.runCols
      .map((h) => `<th>${h}</th>`)
      .join("")}</tr></thead><tbody>${rows
      .map(
        (r) =>
          `<tr><td>${Math.round(r.others_take * 100)}%</td><td>${money(r.free_usd)}</td><td>${money(r.forced_usd)}</td><td>${money(r.locked_usd)}</td><td>${money(r.expected_loss_on_locked_usd)}</td></tr>`,
      )
      .join("")}</tbody></table></div><p class="note">${C.runNote(worst && worst.symbol, worst ? frac(worst.default_severity) : "")} ${C.cur(cur)}</p>
    <label class="q" for="v-share">${C.runSlider}</label><input type="range" id="v-share" min="0" max="100" step="1" value="${Math.round(VS.share * 100)}" />
    <div id="v-runOut"></div>${
      run && run.run && run.run.text ? `<p class="note">${C.runWhole} ${run.run.text}</p>` : ""
    }</div>`;
    RUNCTX = { ex, amt, Lw, cur };
    runOut();
  }
  /* the slider's result only, so a drag keeps its element */
  let RUNCTX = null;
  function runOut() {
    if (!RUNCTX || !$("#v-runOut")) return;
    const { ex, amt, Lw, cur } = RUNCTX,
      x = RM.vaultRun(ex, amt, VS.share, Lw);
    LAST.runAt = x;
    $("#v-runOut").innerHTML = `<p class="why">${C.runAt(Math.round(VS.share * 100) + "%")}</p><dl><dt>${C.runCols[1]}</dt><dd>${money(x.free_usd)} ${cur}</dd><dt>${C.runCols[2]}</dt><dd>${money(x.forced_usd)} ${cur}</dd><dt>${C.runCols[3]}</dt><dd>${money(x.locked_usd)} ${cur}</dd><dt>${C.runCols[4]}</dt><dd>${money(x.expected_loss_on_locked_usd)} ${cur}</dd></dl>`;
  }
  function render() {
    const e = entry(),
      v = detail();
    LAST = { vault: e, detail: v };
    $("#v-addr").value = VS.addr;
    $("#v-pick").value = e ? e.vault_address : "";
    const msg = $("#v-msg");
    msg.hidden = true;
    $("#v-steps").hidden = $("#v-cols").hidden = !v;
    if (!e) {
      msg.hidden = false;
      msg.textContent = C.notFound;
      return;
    }
    if (!v) {
      msg.hidden = false;
      msg.textContent = C.notCovered(e.vault_name, e.note || e.coverage);
      return;
    }
    const ex = v.exit,
      cur = ex.currency || "",
      amt = Math.min(VS.amount, v.total_assets);
    if (VS.amount > v.total_assets) {
      msg.hidden = false;
      msg.textContent = C.above(money(v.total_assets), cur);
    }
    $("#v-amt").value = unitAmt(VS.amount);
    $("#v-amt").title = full(VS.amount);
    $("#v-alt").value = String(+(VS.alt * 100).toFixed(4));

    /* incident list, grouped; not analysed ones greyed (disabled) with their note */
    const g = { credit: [], issuer: [], run: [], none: [] };
    v.incidents.forEach((i) => g[groupOf(i)].push(i));
    $("#v-q1").textContent = C.q1;
    $("#v-n1").textContent = C.hint;
    $("#v-inc").innerHTML = Object.keys(g)
      .filter((k) => g[k].length)
      .map(
        (k) =>
          `<optgroup label="${C.groups[k]}">${g[k]
            .map((i) =>
              k === "none"
                ? `<option value="${i.key}" disabled>${i.symbol || i.key} · ${i.note || ""}</option>`
                : `<option value="${i.key}">${k === "run" ? C.runOpt : i.symbol || i.key}${i.type && k === "credit" ? ` · ${i.type.replace(/_/g, " ")}` : ""}</option>`,
            )
            .join("")}</optgroup>`,
      )
      .join("");
    const inc = v.incidents.find((i) => i.key === VS.inc && i.analyzed !== false) || null;
    $("#v-inc").value = inc ? inc.key : "";
    LAST.inc = inc;
    renderChain(v, inc);
    if (!inc || inc.type === "liquidity_run") $("#v-rail").hidden = true;
    $("#v-more").innerHTML = "";
    if (!inc) {
      $("#v-sevstep").hidden = true;
      $("#v-decision").innerHTML = "";
      return;
    }
    if (inc.type === "liquidity_run") {
      $("#v-sevstep").hidden = true;
      renderRun(v, amt);
      return;
    }

    /* severity, its anchors and the break-even zones */
    const r = decide(v, inc, amt),
      sev = r.severity;
    LAST.r = r;
    LAST.sentence = sentence(inc, ex, r);
    renderDur(v, inc, r, amt);
    $("#v-sevstep").hidden = false;
    $("#v-q2").textContent = C.q2(inc.symbol || inc.key);
    $("#v-sev").value = sevPos(sev);
    $("#v-sevOut").textContent = frac(sev);
    $("#v-ticks").innerHTML = (inc.severity_anchors || [])
      .map((a) => `<i style="left:${(sevPos(a.severity) / LOGR) * 100}%" title="${a.label}: ${frac(a.severity)} (${a.grade})"></i>`)
      .join("");
    const bf = r.severity_break_even_free,
      bc = r.severity_break_even_forced,
      w = (s) => (s === null ? 100 : (sevPos(s) / LOGR) * 100);
    $("#v-zones").innerHTML =
      inc.type === "asset_issuer"
        ? ""
        : `<div class="zones" role="img" aria-label="Severity ranges: stay, withdraw the free part, force out the rest"><i class="zs" style="width:${w(bf)}%"></i><i class="zp" style="width:${w(bc) - w(bf)}%"></i><i class="zc" style="width:${100 - w(bc)}%"></i></div>`;
    $("#v-sevNote").textContent =
      (inc.type === "asset_issuer" ? "" : C.sevNote(bf === null ? null : frac(bf), bc === null ? null : frac(bc)) + " ") +
      C.anchors;

    /* decision card */
    const vcls = VCLS[r.verdict];
    const badge = r.verdict === "EXIT_PARTIAL" ? C.badge.EXIT_PARTIAL(money(r.exit_usd)) : C.badge[r.verdict];
    const sub =
      r.verdict === "EXIT_PARTIAL" ? C.sub.EXIT_PARTIAL(money(r.locked_usd), cur) : r.verdict === "REVIEW" ? C.sub.REVIEW : "";
    const act = r.exit_cost_usd + r.loss_kept_usd,
      max = Math.max(r.loss_if_stay_usd, act, 1e-9);
    const bars =
      r.verdict === "REVIEW"
        ? `<div class="bars">${bar(C.barStay, [["b-loss", r.loss_if_stay_usd]], money(r.loss_if_stay_usd), max)}</div>`
        : `<div class="bars">${bar(C.barStay, [["b-loss", r.loss_if_stay_usd]], money(r.loss_if_stay_usd), max)}${bar(
            C.barExit,
            [
              ["b-cost", r.exit_cost_usd],
              ["b-loss", r.loss_kept_usd],
            ],
            money(act),
            max,
          )}</div><div class="bkey"><span><i class="b-loss"></i>${C.keyLoss}</span><span><i class="b-cost"></i>${C.keyCost}</span></div>`;
    $("#v-decision").innerHTML = `<div class="vband ${vcls}"><span class="lbl">${C.lbl(inc.symbol || inc.key, frac(sev))} · ${e.vault_name}</span>
    <div class="verdict">${badge}${sub ? `<small>${sub}</small>` : ""}</div><p class="why">${LAST.sentence}</p></div>
    <div class="dbody">${bars}<p class="note">${C.assumes} ${C.cur(cur)}</p>${
      inc.type === "asset_issuer" ? `<p class="note">${C.issuerNote}</p>` : ""
    }<p class="note">${C.assumption(frac(VS.alt))}</p>${details(v, inc, r, amt)}</div>`;
  }

  /* ---- static parts and events (on this view's own elements only) */
  $("#v-addr-lbl").textContent = C.addrLabel;
  $("#v-amt-lbl").textContent = C.amountLabel;
  $("#v-alt-lbl").textContent = C.altLabel;
  $("#v-amt").placeholder = "e.g. 100k or 3m";
  const opt = (x) =>
    `<option value="${x.vault_address}">${x.vault_name} · ${x.chain} · ${x.protocol} · $${money(x.tvl_usd || 0)}</option>`;
  $("#v-pick").innerHTML =
    `<option value="">${C.pick}</option>` +
    `<optgroup label="${C.groupFull}">${REPORT.filter((x) => x.coverage === "full").map(opt).join("")}</optgroup>` +
    `<optgroup label="${C.groupOther}">${REPORT.filter((x) => x.coverage !== "full").map(opt).join("")}</optgroup>`;
  const setVault = (a) => {
    VS.addr = a;
    resetForVault();
    render();
  };
  $("#v-pick").addEventListener("change", (ev) => ev.target.value && setVault(ev.target.value));
  $("#v-addr").addEventListener("change", (ev) => setVault(ev.target.value.trim()));
  $("#v-amt").addEventListener("change", (ev) => {
    const v = amtOf(ev.target.value);
    if (v !== null && v > 0 && isFinite(v)) VS.amount = v;
    render();
  });
  $("#v-alt").addEventListener("change", (ev) => {
    const v = num(ev.target.value, true);
    if (v !== null && v >= 0 && v <= 50) VS.alt = v / 100;
    render();
  });
  $("#v-inc").addEventListener("change", (ev) => {
    VS.inc = ev.target.value;
    VS.sev = null;
    render();
  });
  document.querySelectorAll("[data-vdisp]").forEach((b) =>
    b.addEventListener("click", () => {
      VS.display = b.dataset.vdisp;
      render();
    }),
  );
  new ResizeObserver(() => VS.display === "graph" && paintGraph()).observe($("#v-chain"));
  $("#view-vault").addEventListener(
    "toggle",
    (ev) => {
      if (ev.target.tagName === "DETAILS" && ev.target.id) VS.open[ev.target.id] = ev.target.open;
    },
    true,
  );
  $("#view-vault").addEventListener("input", (ev) => {
    if (ev.target.id !== "v-share") return;
    VS.share = +ev.target.value / 100;
    runOut();
  });
  /* a typed duration, as in the PT view: hours, or with h / d / w; clamped to the rail */
  $("#v-durIn").addEventListener("change", (ev) => {
    const m = String(ev.target.value).trim().replace(",", ".").match(/^(\d*\.?\d+)\s*(h|hr|hrs|hours?|d|days?|w|wk|weeks?)?$/i);
    if (m && +m[1] > 0) {
      const u = (m[2] || "h")[0].toLowerCase();
      VS.hours = Math.min(H_MAX, Math.max(H_MIN, +m[1] * (u === "w" ? 168 : u === "d" ? 24 : 1)));
    }
    ev.target.value = durText(VS.hours);
    render();
  });
  $("#v-dur").addEventListener("input", (ev) => {
    VS.hours = hOf(+ev.target.value);
    render();
  });
  $("#view-vault").addEventListener("click", (ev) => {
    const b = ev.target.closest("[data-vrec]");
    if (!b) return;
    VS.recovers = b.dataset.vrec === "1";
    render();
  });
  $("#v-sev").addEventListener("input", (ev) => {
    VS.sev = posSev(+ev.target.value);
    render();
  });
  resetForVault();

  /* For check_demo.mjs: read the state and the last result; set inputs as the controls would. */
  window.VaultView = {
    state: VS,
    last: () => LAST,
    set(o) {
      if ("addr" in o) {
        VS.addr = o.addr;
        resetForVault();
      }
      Object.keys(o).forEach((k) => k !== "addr" && (VS[k] = o[k]));
      render();
    },
    sentence,
    frac,
    money,
    show: showPage,
  };
})();
