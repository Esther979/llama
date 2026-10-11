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
    hz: null,
    inc: null,
    sev: null,
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
    VS.hz = v ? v.exit.horizon_days : null;
  }

  /* ---- severity slider: fractions 0.5% .. 100% on a log scale, positions 0..1000 */
  const SMIN = 0.005,
    SMAX = 1,
    LOGR = 1000;
  const sevPos = (s) => (Math.log(Math.max(SMIN, s) / SMIN) / Math.log(SMAX / SMIN)) * LOGR;
  const posSev = (p) => Math.round(SMIN * Math.pow(SMAX / SMIN, p / LOGR) * 1e4) / 1e4;

  /* ---- the decision and its sentence (the backend's wording, numbers from r only) */
  function decide(v, inc, amt) {
    return RM.vaultDecideAt(inc, v.exit, amt, VS.sev === null ? inc.default_severity : VS.sev, VS.alt, VS.hz);
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
  function onPath(item, inc) {
    if (!inc) return false;
    const paths = (inc.propagation_paths || []).join(" | "),
      aff = inc.affected_markets || [];
    return (
      (!!item.label && paths.includes(item.label)) ||
      (!!item.market_id && aff.some((m) => item.market_id.startsWith(String(m).split(":").pop()))) ||
      (!!item.address && !!inc.token && item.address.toLowerCase() === inc.token.toLowerCase()) ||
      (!!item.offchain && item.offchain === inc.symbol)
    );
  }
  function renderChain(v, inc) {
    const cur = v.exit.currency || "";
    $("#v-chainHead").textContent = C.chainHead;
    $("#v-chain").innerHTML = (v.dependency_chain || [])
      .map(
        (L) => `<div class="vl"><span class="vn">${L.layer}</span><div><h3>${L.name}</h3><ul>${L.items
          .map((it) => {
            const on = onPath(it, inc);
            const addr = /^0x[0-9a-f]{40}$/i.test(it.address || "")
              ? ` <a class="mono" href="https://etherscan.io/address/${it.address}" target="_blank" rel="noopener">${short(it.address)}</a>`
              : "";
            return `<li class="${on ? "on" : ""}"${on ? ` title="${C.onPath}"` : ""}><b>${it.label}</b> ${gr(it.evidence)}${addr}${it.allocation ? ` · ${money(it.allocation)} ${cur}` : ""}${it.detail ? `<span class="note">${it.detail}</span>` : ""}</li>`;
          })
          .join("")}</ul></div></div>`,
      )
      .join("");
  }
  function renderRun(v, amt) {
    const ex = v.exit,
      cur = ex.currency || "",
      worst = v.incidents.find((i) => i.key === v.worst_incident) || null;
    const Lw = worst ? RM.vaultDecideAt(worst, ex, amt, null, VS.alt, VS.hz).L : 0;
    const rows = [0, 0.5, 1].map((sh) => RM.vaultRun(ex, amt, sh, Lw));
    LAST.run = rows;
    const note = (v.incidents.find((i) => i.key === VS.inc) || {}).note || "";
    $("#v-decision").innerHTML = `<div class="vband"><span class="lbl">${C.runHead} · ${v.vault_name}</span><p class="why">${
      note.charAt(0).toUpperCase() + note.slice(1)
    }.</p></div><div class="dbody"><div class="tw"><table><thead><tr>${C.runCols
      .map((h) => `<th>${h}</th>`)
      .join("")}</tr></thead><tbody>${rows
      .map(
        (r) =>
          `<tr><td>${Math.round(r.others_take * 100)}%</td><td>${money(r.free_usd)}</td><td>${money(r.forced_usd)}</td><td>${money(r.locked_usd)}</td><td>${money(r.expected_loss_on_locked_usd)}</td></tr>`,
      )
      .join("")}</tbody></table></div><p class="note">${C.runNote(worst && worst.symbol, worst ? frac(worst.default_severity) : "")} ${C.cur(cur)}</p></div>`;
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
    $("#v-amt").value = full(VS.amount);
    $("#v-alt").value = String(+(VS.alt * 100).toFixed(4));
    $("#v-hz").value = String(VS.hz);

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
    const vcls = { STAY: "stay", EXIT: "cap", EXIT_PARTIAL: "cap", REVIEW: "reduce" }[r.verdict];
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
    }<p class="note">${C.assumption(frac(VS.alt), VS.hz)}</p></div>`;
  }

  /* ---- static parts and events (on this view's own elements only) */
  $("#v-addr-lbl").textContent = C.addrLabel;
  $("#v-amt-lbl").textContent = C.amountLabel;
  $("#v-alt-lbl").textContent = C.altLabel;
  $("#v-hz-lbl").textContent = C.hzLabel;
  $("#v-amt").placeholder = "e.g. 100,000";
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
    const v = num(ev.target.value, false);
    if (v !== null && v > 0) VS.amount = v;
    render();
  });
  $("#v-alt").addEventListener("change", (ev) => {
    const v = num(ev.target.value, true);
    if (v !== null && v >= 0 && v <= 50) VS.alt = v / 100;
    render();
  });
  $("#v-hz").addEventListener("change", (ev) => {
    const v = num(ev.target.value, true);
    if (v !== null && v > 0 && v <= 3650) VS.hz = v;
    render();
  });
  $("#v-inc").addEventListener("change", (ev) => {
    VS.inc = ev.target.value;
    VS.sev = null;
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
