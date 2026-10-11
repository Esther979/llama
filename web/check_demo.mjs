#!/usr/bin/env node
/* Browser check for web/demo.html (web/CLAUDE.md, "How to verify", steps 1 to 4, plus phone width and dark mode).
   Drives the installed Chrome over the DevTools protocol: no packages, Node 22+ (global WebSocket).
   Usage: node web/check_demo.mjs [page.html]   (default web/demo.html; CHROME=/path/to/chrome overrides the browser)
   Exit code 1 on any console error, failed check or acceptance mismatch. */

import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const PAGE = pathToFileURL(resolve(process.argv[2] || join(HERE, "demo.html"))).href;
const GUIDE = resolve(HERE, "..", "FRONTEND_GUIDE.md");
const VGUIDE = resolve(HERE, "..", "FRONTEND_VAULT_GUIDE.md");
const CHROME =
  process.env.CHROME ||
  [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
  ].find((p) => existsSync(p));
if (!CHROME) {
  console.error("Chrome not found; set CHROME=/path/to/chrome");
  process.exit(2);
}

let failures = 0;
const gate = (ok, label) => {
  console.log(`${ok ? "GATE PASS" : "GATE FAIL"}  ${label}`);
  if (!ok) failures++;
};

/* ---- the guide's acceptance table (section 9), read at run time so it follows the guide */
function acceptanceRows() {
  const md = readFileSync(GUIDE, "utf8");
  const sec = md.slice(md.indexOf("## 9. Acceptance tests"));
  const rows = [];
  for (const line of sec.split("\n")) {
    if (!/^\| *\d+M *\|/.test(line)) continue;
    const c = line.split("|").slice(1, -1).map((x) => x.trim());
    const [nodeFail, sev] = [c[2].replace(/`/g, ""), c[3]];
    const [node, fail] = nodeFail.split(":");
    const num = (t) => (t === "-" ? null : +t.replace(/[$,%h]/g, ""));
    const [bs, bc] = c[11].split("/").map((t) => num(t.trim()));
    rows.push({
      size: +c[0].replace("M", "") * 1e6,
      preset: c[1].replace(/`/g, ""),
      node,
      fail,
      sev: num(sev),
      verdict: c[4],
      sell: num(c[5]),
      sale: num(c[6]),
      stay: num(c[7]),
      kept: num(c[8]),
      oracle: { True: true, False: false, None: null }[c[9]],
      later: +c[10],
      beStart: bs,
      beCap: bc,
    });
  }
  return rows;
}

/* ---- the guide's past-incident table (section 3c), read at run time */
function pastRows() {
  const md = readFileSync(GUIDE, "utf8");
  const i = md.indexOf("## 3c."), sec = i < 0 ? "" : md.slice(i, md.indexOf("\n## ", i + 5));
  const num = (t) => (t === "-" ? null : +t.replace(/[$,%]/g, ""));
  const rows = [];
  for (const line of sec.split("\n")) {
    const c = line.split("|").slice(1, -1).map((x) => x.trim().replace(/`/g, ""));
    if (c.length !== 9 || !/^[a-z]/.test(c[0]) || c[0] === "key") continue;
    const [bs, bc] = c[8].split("/").map((t) => num(t.trim()));
    rows.push({ key: c[0], preset: c[1], verdict: c[2], sell: num(c[3]), sale: num(c[4]), stay: num(c[5]),
      oracle: { true: true, false: false }[c[6]], liquidated: c[7] === "yes", beStart: bs, beCap: bc });
  }
  return rows;
}

/* ---- the vault guide's acceptance tables (section 6), read at run time */
function vaultRows() {
  const md = readFileSync(VGUIDE, "utf8");
  const i = md.indexOf("## 6."), sec = i < 0 ? "" : md.slice(i, md.indexOf("\n## ", i + 5));
  const n = (t) => +t.replace(/[,%]/g, "");
  const dec = [], run = [];
  for (const line of sec.split("\n")) {
    const c = line.split("|").slice(1, -1).map((x) => x.trim().replace(/`/g, ""));
    if (c.length === 10 && c[0] !== "Vault" && !/^-+$/.test(c[0])) {
      const [bf, bc] = c[9].split("/").map((t) => n(t.trim()) / 100);
      dec.push({ vault: c[0], inc: c[1], amount: n(c[2]), sev: /default/.test(c[3]) ? null : n(c[3]) / 100,
        verdict: c[4], stay: n(c[5]), exit: n(c[6]), cost: n(c[7]), locked: n(c[8]), beFree: bf, beForced: bc });
    } else if (c.length === 5 && /^\d+%$/.test(c[0])) {
      run.push({ share: n(c[0]) / 100, free: n(c[1]), forced: n(c[2]), locked: n(c[3]), loss: n(c[4]) });
    }
  }
  const m = sec.match(/Liquidity run, ([^,]+), amount ([\d,]+)/);
  return { dec, run, runVault: m ? m[1].trim() : null, runAmount: m ? n(m[2]) : null };
}

/* ---- minimal DevTools client */
async function launch() {
  const profile = mkdtempSync(join(tmpdir(), "check-demo-"));
  const proc = spawn(CHROME, [
    "--headless=new",
    "--disable-gpu",
    "--no-first-run",
    "--no-default-browser-check",
    "--allow-file-access-from-files",
    "--remote-debugging-port=0",
    `--user-data-dir=${profile}`,
    "about:blank",
  ]);
  const wsUrl = await new Promise((ok, ko) => {
    let buf = "";
    const t = setTimeout(() => ko(new Error("Chrome did not start")), 20000);
    proc.stderr.on("data", (d) => {
      buf += d;
      const m = buf.match(/DevTools listening on (ws:\/\/\S+)/);
      if (m) {
        clearTimeout(t);
        ok(m[1]);
      }
    });
  });
  const ws = new WebSocket(wsUrl);
  await new Promise((ok) => ws.addEventListener("open", ok, { once: true }));
  let id = 0;
  const pending = new Map(),
    listeners = [];
  ws.addEventListener("message", (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pending.has(msg.id)) {
      const { ok, ko } = pending.get(msg.id);
      pending.delete(msg.id);
      msg.error ? ko(new Error(msg.error.message)) : ok(msg.result);
    } else listeners.forEach((f) => f(msg));
  });
  const send = (method, params = {}, sessionId) =>
    new Promise((ok, ko) => {
      const n = ++id;
      pending.set(n, { ok, ko });
      ws.send(JSON.stringify({ id: n, method, params, sessionId }));
    });
  const close = () => {
    ws.close();
    proc.kill();
    try {
      rmSync(profile, { recursive: true, force: true });
    } catch {}
  };
  return { send, on: (f) => listeners.push(f), close };
}

async function openPage(b, { width = 1400, dark = false } = {}) {
  const { targetId } = await b.send("Target.createTarget", { url: "about:blank" });
  const { sessionId } = await b.send("Target.attachToTarget", { targetId, flatten: true });
  const s = (m, p) => b.send(m, p, sessionId);
  const errors = [];
  b.on((msg) => {
    if (msg.sessionId !== sessionId) return;
    if (msg.method === "Runtime.exceptionThrown")
      errors.push(msg.params.exceptionDetails.exception?.description || msg.params.exceptionDetails.text);
    if (msg.method === "Runtime.consoleAPICalled" && msg.params.type === "error")
      errors.push(msg.params.args.map((a) => a.value ?? a.description).join(" "));
    if (msg.method === "Log.entryAdded" && msg.params.entry.level === "error")
      errors.push(`${msg.params.entry.text} ${msg.params.entry.url || ""}`.trim());
  });
  await s("Runtime.enable");
  await s("Log.enable");
  await s("Page.enable");
  await s("Emulation.setDeviceMetricsOverride", {
    width,
    height: 900,
    deviceScaleFactor: 1,
    mobile: width < 600,
  });
  await s("Emulation.setEmulatedMedia", {
    features: [{ name: "prefers-color-scheme", value: dark ? "dark" : "light" }],
  });
  const loaded = new Promise((ok) =>
    b.on((m) => m.sessionId === sessionId && m.method === "Page.loadEventFired" && ok()),
  );
  await s("Page.navigate", { url: PAGE });
  await loaded;
  const ev = async (expr) => {
    const r = await s("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true });
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text);
    return r.result.value;
  };
  return { ev, errors };
}

/* ---- checks */
const b = await launch();
try {
  /* 1. load */
  const p = await openPage(b);
  const boot = await p.ev(`({
    data: !!window.DASHBOARD, model: !!window.RiskModel,
    banner: document.querySelector("#banner").hidden,
    css: getComputedStyle(document.body).backgroundColor !== "rgba(0, 0, 0, 0)",
    verdict: !!document.querySelector("#decision .verdict") })`);
  gate(boot.data && boot.model, "1. backend files load (window.DASHBOARD, window.RiskModel)");
  gate(boot.banner, "1. load-error banner hidden");
  gate(boot.css, "1. demo.css applied");
  gate(boot.verdict, "1. a verdict is rendered on load");

  /* 1b. first screen (guide 3c, user decision): the PT-reUSD event on the real borrower closest to liquidation,
     its banner shown, the card says it is a pattern and someone else's position */
  const first = await p.ev(`(() => {
    const b = document.querySelector("#pastBanner"), card = document.querySelector("#decision");
    return { past: S.past, pos: S.pos, verdict: model().verdict, banner: !!b && !b.hidden && /Pattern from/.test(b.textContent),
      cardPattern: /Pattern from/.test(card.querySelector(".lbl").textContent),
      notYours: /not your position/.test(card.textContent),
      replay: document.querySelector("#replay").value };
  })()`);
  gate(first.past === "pt_reusd_aug_2026" && first.pos === "lev_closest_to_liquidation" && first.replay === first.past,
    `1b. first screen preselects ${first.past} on ${first.pos}`);
  gate(first.verdict === "EXIT" && first.banner && first.cardPattern && first.notYours,
    `1b. first screen: verdict ${first.verdict}, event banner ${first.banner}, card says pattern ${first.cardPattern} and not your position ${first.notYours}`);

  /* 2. every node opens its drawer, clicked in both views */
  const drawers = await p.ev(`(() => {
    const bad = [], seen = new Set(), keys = Object.keys(NODES);
    for (const view of ["list", "graph"]) {
      document.querySelector('[data-view="' + view + '"]').click();
      /* expanding a layer re-renders the list: expand one at a time, querying again after each click */
      if (view === "list") for (;;) {
        const x = document.querySelector('button[data-more][aria-expanded="false"]');
        if (!x) break;
        x.click();
      }
      for (const k of keys) {
        const el = document.querySelector('button[data-n="' + k + '"]');
        if (!el) { bad.push(view + ":" + k + " (no button)"); continue; }
        el.click();
        const dr = document.querySelector("#drawer");
        if (dr.hidden || !dr.textContent.trim()) bad.push(view + ":" + k);
        else seen.add(view + ":" + k);
        closeDrawer();
      }
    }
    return { n: seen.size, of: 2 * keys.length, bad };
  })()`);
  gate(drawers.bad.length === 0, `2. drawers open: ${drawers.n}/${drawers.of}${drawers.bad.length ? " missing " + drawers.bad.join(", ") : ""}`);

  /* 2b. no detector and no invented incidents (team decision): no such wording on the page, in its menus or in the
     drawer of a past event's dependency; no prototype bar */
  const words = await p.ev(`(() => {
    const fire = (el, v) => { el.value = v; el.dispatchEvent(new Event("change", { bubbles: true })); };
    const PL = typeof PAST !== "undefined" ? PAST : [];
    if (PL.length) fire(document.querySelector("#replay"), PL[0].key);
    const opts = [...document.querySelectorAll("option, optgroup")].map((o) => o.label || o.textContent).join(" | ");
    if (typeof pastOf === "function" && pastOf()) nodeEvidence(pastOf().node);
    const txt = document.body.innerText + " | " + opts;
    closeDrawer();
    const hits = (txt.match(/[^.|\\n]*(detect|anomal|sample alert|invented)[^.|\\n]*/gi) || [])
      .concat(txt.match(/[^.|\\n]*\\bExamples?\\b[^.|\\n]*/g) || []);
    return { hits: hits.slice(0, 4), proto: !!document.querySelector("#proto, #feed") };
  })()`);
  gate(words.hits.length === 0, `2b. no detector or invented-incident wording${words.hits.length ? ": " + words.hits.join(" / ") : ""}`);
  gate(!words.proto, "2b. no prototype bar or example feed");

  /* 2d. "Load a past incident pattern" lists d.past_incidents; each sets node, failure and severity and passes its
     opts; moving the severity turns it into a what-if */
  const past = await p.ev(`(() => {
    if (typeof PAST === "undefined") return { n: 0, bad: ["the page has no d.past_incidents list"], optsMatter: false, whatIf: false };
    const fire = (el, v) => { el.value = v; el.dispatchEvent(new Event("change", { bubbles: true })); };
    const sel = document.querySelector("#replay"), bad = [];
    const keys = [...sel.options].map((o) => o.value).filter(Boolean);
    if (keys.join() !== PAST.map((x) => x.key).join()) bad.push("options " + keys.join() + " vs data " + PAST.map((x) => x.key).join());
    for (const pk of ["spot", "lev_closest_to_liquidation"]) {
      fire(document.querySelector("#pos"), pk);
      for (const x of PAST) {
        fire(sel, x.key);
        if (S.past !== x.key || S.node !== x.node || S.fail !== x.fail || Math.abs(S.sev - x.sev) > 1e-9)
          bad.push(x.key + ": state " + [S.past, S.node, S.fail, S.sev].join("/"));
        const want = RiskModel.decideAt(d, pk, x.node, x.fail, x.sev, carry(), x.opts), got = model().sev;
        if (got.verdict !== want.verdict || Math.abs(got.loss_if_stay_usd - want.loss_if_stay_usd) > 1)
          bad.push(pk + " " + x.key + ": page " + got.verdict + " " + Math.round(got.loss_if_stay_usd) + " vs model with opts " + want.verdict + " " + Math.round(want.loss_if_stay_usd));
      }
    }
    /* opts must matter somewhere, or this gate proves nothing */
    const u = PAST.find((x) => x.key === "usde_feb_2026");
    const optsMatter = !!u && RiskModel.decideAt(d, "spot", u.node, u.fail, u.sev, 0).loss_if_stay_usd
      !== RiskModel.decideAt(d, "spot", u.node, u.fail, u.sev, 0, u.opts).loss_if_stay_usd;
    fire(sel, PAST[0].key);
    const sv = document.querySelector("#sev");
    sv.value = String(+sv.value + 1); sv.dispatchEvent(new Event("input", { bubbles: true }));
    const whatIf = S.past === null && document.querySelector("#pastBanner").hidden && document.querySelector("#replay").value === "";
    fire(sel, "");
    return { n: keys.length, bad, optsMatter, whatIf };
  })()`);
  gate(past.bad.length === 0 && past.n > 0, `2d. past events: ${past.n} listed, each sets its incident and passes its opts${past.bad.length ? ": " + past.bad.slice(0, 3).join("; ") : ""}`);
  gate(past.optsMatter, "2d. opts change the result (USDe Feb 2026 on spot), so the gate above is meaningful");
  gate(past.whatIf, "2d. moving the severity turns a past event into a what-if (banner hidden, dropdown reset)");

  /* 2e. the guide's past-incident table (section 3c), on screen */
  const pr = pastRows();
  const pres = await p.ev(`(() => {
    const rows = ${JSON.stringify(pr)}, out = [];
    const fire = (el, v) => { el.value = v; el.dispatchEvent(new Event("change", { bubbles: true })); };
    for (const r of rows) {
      fire(document.querySelector("#pos"), r.preset);
      fire(document.querySelector("#replay"), r.key);
      const m = model(), x = m.sev, be = m.be, txt = document.querySelector("#decision .verdict").textContent, d2 = [];
      const want = r.verdict === "STAY" ? "Stay" : r.verdict === "EXIT" ? "Exit" : "Sell " + money(x.sell_usd);
      const eq = (a, b, tol, name) => { if (a === null || b === null ? a !== b : Math.abs(a - b) > tol) d2.push(name + " " + a + " vs " + b); };
      if (S.past !== r.key) d2.push("not selected");
      if (x.verdict !== r.verdict) d2.push("verdict " + x.verdict + " vs " + r.verdict);
      eq(Math.round(x.sell_fraction * 100), r.sell, 0, "sell %");
      eq(Math.round(x.sale_cost_usd), r.sale, 1, "sale cost");
      eq(Math.round(x.loss_if_stay_usd), r.stay, 1, "loss if stay");
      if (x.oracle_falls !== r.oracle) d2.push("oracle " + x.oracle_falls + " vs " + r.oracle);
      if ((x.liquidated || []).includes(true) !== r.liquidated) d2.push("liquidated " + JSON.stringify(x.liquidated));
      eq(be.start === null ? null : +be.start.toFixed(3), r.beStart, 1e-3, "break-even start");
      eq(be.cap === null ? null : +be.cap.toFixed(3), r.beCap, 1e-3, "break-even cap");
      if (!txt.startsWith(want)) d2.push("screen '" + txt + "' vs '" + want + "'");
      out.push({ row: r.key + " " + r.preset, d: d2 });
    }
    fire(document.querySelector("#replay"), "");
    return out;
  })()`);
  const pok = pres.filter((r) => !r.d.length).length;
  gate(pres.length > 0 && pok === pres.length, `2e. guide 3c past-incident rows: ${pok}/${pres.length} match (model and screen)`);
  pres.filter((r) => r.d.length).forEach((r) => console.log(`           ${r.row}: ${r.d.join("; ")}`));

  /* 2c. off-chain dependencies in the evidence drawer (guide section 8) */
  const off = await p.ev(`(() => {
    const o = d.offchain || {}, out = {};
    const links = (id) => { nodeEvidence(id); return document.querySelectorAll("#drawer a.osrc").length; };
    out.ethena = [links("ethena"), o.USDe ? o.USDe.counts.relations : null];
    out.susde = [links("susde"), o.sUSDe ? o.sUSDe.counts.relations : null];
    /* quote wording per relation: true -> quote + "re-checked", null -> quote + "not re-checked" (the source page
       refused the checker), false -> no quote + "not found" */
    out.quoteBad = []; out.quoteN = { true: 0, null: 0, false: 0 };
    for (const [id, key] of [["ethena", "USDe"], ["susde", "sUSDe"]]) {
      if (!o[key]) continue;
      nodeEvidence(id);
      const lis = [...document.querySelectorAll("#drawer .offc li")];
      for (const r of o[key].relations) {
        const e = r.evidence || {}, qf = e.quote_found === true ? "true" : e.quote_found === false ? "false" : "null";
        if (!e.quote) continue;
        out.quoteN[qf]++;
        const li = lis.find((x) => x.textContent.includes(r.relation));
        const t = li ? li.textContent : "", hasQ = !!(li && li.querySelector("q"));
        const ok = qf === "true" ? hasQ && /re-checked/.test(t) && !/not re-checked|not found/.test(t)
          : qf === "null" ? hasQ && /not re-checked/.test(t) && !/not found/.test(t)
          : !hasQ && /not found/.test(t);
        if (!ok) out.quoteBad.push(r.entity + " (quote_found " + qf + "): " + (li ? t.slice(-70) : "row missing"));
      }
    }
    nodeEvidence("usde");
    const b = document.querySelector('#drawer button[data-drawer="ethena"]');
    if (b) b.click();
    out.usdeOpensEthena = !!b && document.querySelectorAll("#drawer a.osrc").length === out.ethena[1];
    /* "Contracts behind it" lists one entry per member, off-chain members excluded */
    out.offIds = [];
    for (const k of Object.keys(NODES)) {
      nodeEvidence(k);
      const dt = [...document.querySelectorAll("#drawer dt")].find((x) => x.textContent === "Contracts behind it");
      const shown = dt ? dt.nextElementSibling.innerHTML.split("<br>").length : 0;
      const want = (NODES[k].members || []).filter((m) => !m.startsWith("offchain:")).length;
      if (shown !== want) out.offIds.push(k + " " + shown + " shown vs " + want);
    }
    closeDrawer();
    return out;
  })()`);
  gate(off.ethena[1] !== null && off.ethena[0] === off.ethena[1] && off.susde[0] === off.susde[1],
    `2c. off-chain source links: ethena ${off.ethena[0]}/${off.ethena[1]}, susde ${off.susde[0]}/${off.susde[1]}`);
  gate(off.usdeOpensEthena, "2c. the usde drawer links to Ethena's off-chain relations");
  gate(off.quoteBad.length === 0,
    `2c. quote wording by quote_found (true ${off.quoteN.true}, null ${off.quoteN.null}, false ${off.quoteN.false})${off.quoteBad.length ? ": " + off.quoteBad.join("; ") : ""}`);
  gate(off.offIds.length === 0, `2c. "Contracts behind it" lists on-chain members only${off.offIds.length ? ": " + off.offIds.join(", ") : ""}`);

  /* 3. every preset x every failure of every node, through the page's own controls */
  const sweep = await p.ev(`(() => {
    const bad = []; let n = 0;
    const fire = (el, v) => { el.value = v; el.dispatchEvent(new Event("change", { bubbles: true })); };
    fire(document.querySelector("#replay"), "");   /* what-if tests: no past event */
    for (const pk of Object.keys(PRE)) {
      fire(document.querySelector("#pos"), pk);
      for (const k of Object.keys(NODES)) for (const f of fails(k)) {
        try {
          setNode(k, f);
          fire(document.querySelector("#fail"), f);
          const v = document.querySelector("#decision .verdict");
          if (!v || !v.textContent.trim()) bad.push(pk + " " + k + ":" + f);
          n++;
        } catch (e) { bad.push(pk + " " + k + ":" + f + " " + e); }
      }
    }
    return { n, bad };
  })()`);
  gate(sweep.bad.length === 0 && sweep.n > 0, `3. presets x failures rendered: ${sweep.n}${sweep.bad.length ? " failed " + sweep.bad.slice(0, 5).join("; ") : ""}`);

  /* 4. acceptance table, model result and on-screen verdict */
  const rows = acceptanceRows();
  const atPage = rows.filter((r) => r.size === 1e7);
  const res = await p.ev(`(() => {
    const rows = ${JSON.stringify(atPage)}, out = [];
    const fire = (el, v) => { el.value = v; el.dispatchEvent(new Event("change", { bubbles: true })); };
    fire(document.querySelector("#replay"), "");   /* section 9 rows are what-if tests: no opts */
    for (const r of rows) {
      fire(document.querySelector("#pos"), r.preset);
      setNode(r.node, r.fail, r.sev);
      const m = model(), x = m.sev, be = m.be, txt = document.querySelector("#decision .verdict").textContent;
      const want = r.verdict === "STAY" ? "Stay" : r.verdict === "EXIT" ? "Exit" : "Sell " + money(x.sell_usd);
      const d = [];
      const eq = (a, b, tol, name) => { if (a === null || b === null ? a !== b : Math.abs(a - b) > tol) d.push(name + " " + a + " vs " + b); };
      if (x.verdict !== r.verdict) d.push("verdict " + x.verdict + " vs " + r.verdict);
      eq(Math.round(x.sell_fraction * 100), r.sell, 0, "sell %");
      eq(Math.round(x.sale_cost_usd), r.sale, 1, "sale cost");
      eq(Math.round(x.loss_if_stay_usd), r.stay, 1, "loss if stay");
      eq(Math.round(x.loss_kept_usd), r.kept, 1, "loss kept");
      if (x.oracle_falls !== r.oracle) d.push("oracle " + x.oracle_falls + " vs " + r.oracle);
      eq(+x.sellable_later.toFixed(4), r.later, 1e-4, "sellable later");
      eq(be.start === null ? null : +be.start.toFixed(3), r.beStart, 1e-3, "break-even start");
      eq(be.cap === null ? null : +be.cap.toFixed(3), r.beCap, 1e-3, "break-even cap");
      if (!txt.startsWith(want)) d.push("screen '" + txt + "' vs '" + want + "'");
      out.push({ row: r.preset + " " + r.node + ":" + r.fail + " @" + r.sev, d });
    }
    return out;
  })()`);
  const ok = res.filter((r) => !r.d.length).length;
  gate(ok === res.length && res.length > 0, `4. acceptance rows at $10M: ${ok}/${res.length} match (model and screen)`);
  res.filter((r) => r.d.length).forEach((r) => console.log(`           ${r.row}: ${r.d.join("; ")}`));
  /* 4b. the exit panel agrees with the decision card, for every preset x failure at four severities */
  const agree = await p.ev(`(() => {
    const bad = []; let n = 0;
    const fire = (el, v) => { el.value = v; el.dispatchEvent(new Event("change", { bubbles: true })); };
    /* parse the page's money(): $1.23M, $456k, $4.5k, $789 */
    const usd = (t) => { const m = t.match(/\\$([\\d.,]+)([Mk]?)/); if (!m) return null;
      return +m[1].replace(/,/g, "") * (m[2] === "M" ? 1e6 : m[2] === "k" ? 1e3 : 1); };
    const dd = (label) => { const dt = [...document.querySelectorAll("#exit dt")].find((x) => x.textContent === label);
      return dt ? dt.nextElementSibling.textContent : ""; };
    fire(document.querySelector("#replay"), "");
    for (const pk of Object.keys(PRE)) {
      fire(document.querySelector("#pos"), pk);
      for (const k of Object.keys(NODES)) for (const f of fails(k)) {
        const fl = FAIL[f];
        for (const sv of [fl.min, fl.def, (fl.min + fl.max) / 2, fl.max]) {
          setNode(k, f, sv);
          const m = model(), r = m.sev, today = usd(dd("Today")), later = dd("If this plays out"), tag = pk + " " + k + ":" + f + " @" + +sv.toFixed(2);
          n++;
          if (today === null) { bad.push(tag + ": no 'Today' amount"); continue; }
          if (r.sell_usd > today * 1.005 + 500) bad.push(tag + ": card sells " + money(r.sell_usd) + ", panel says today " + money(today));
          if (/liquidators/i.test(later) && !(r.sellable_later < r.sellable_now - 1e-9))
            bad.push(tag + ": panel names liquidators, sellable " + r.sellable_now.toFixed(3) + " -> " + r.sellable_later.toFixed(3));
        }
      }
    }
    return { n, bad };
  })()`);
  gate(agree.bad.length === 0, `4b. exit panel agrees with the decision card: ${agree.n - agree.bad.length}/${agree.n} cases`);
  agree.bad.slice(0, 8).forEach((x) => console.log("           " + x));
  if (agree.bad.length > 8) console.log(`           ... and ${agree.bad.length - 8} more`);
  const other = rows.length - atPage.length;
  if (other) console.log(`SKIPPED    4. ${other} acceptance rows at other sizes: the page has no position-size input yet`);

  /* 6. vault view (FRONTEND_VAULT_GUIDE.md) */
  const vr = vaultRows();
  const vault = await p.ev(`(() => {
    const out = { bad: [], dec: [], run: [], sent: { n: 0, bad: [] }, msgs: {} };
    const VV = window.VaultView;
    if (!VV) { out.bad.push("no vault view"); return out; }
    const fire = (el, v) => { el.value = v; el.dispatchEvent(new Event("change", { bubbles: true })); };
    /* 6a. snapshot the PT view, use the vault view, switch back, compare */
    fire(document.querySelector("#replay"), PAST.length ? PAST[0].key : "");
    nodeEvidence("oracle");
    const snap = () => JSON.stringify({ S, pt: document.querySelector("#view-pt").innerText,
      hdr: [...document.querySelectorAll("#hdr-pt select")].map((x) => x.value), sev: document.querySelector("#sev").value });
    const before = snap();
    document.querySelector('[data-page="vault"]').click();
    out.vaultShown = !document.querySelector("#view-vault").hidden && document.querySelector("#view-pt").hidden
      && document.querySelector("#drawer").hidden;
    const addrOf = (name) => (VAULTS.report.vaults.find((x) => x.vault_name === name) || {}).vault_address;
    /* 6b. the decision table */
    for (const r of ${JSON.stringify(vr.dec)}) {
      const a = addrOf(r.vault);
      if (!a) { out.dec.push({ row: r.vault, d: ["vault not in the list"] }); continue; }
      fire(document.querySelector("#v-pick"), a);
      fire(document.querySelector("#v-amt"), String(r.amount));
      fire(document.querySelector("#v-inc"), r.inc);
      if (r.sev !== null) VV.set({ sev: r.sev });
      /* the page must give exactly the guide's call on today's data, and the guide's verdict; the guide's numbers
         are compared too, but only reported (they may predate a data refresh) */
      const L = VV.last(), x = L.r || {}, d2 = [], drift = [];
      const v = VAULTS.details[a.toLowerCase()], inc = v.incidents.find((i) => i.key === r.inc);
      const want = RiskModel.vaultDecideAt(inc, v.exit, Math.min(r.amount, v.total_assets), r.sev, null, null);
      for (const k of ["verdict", "loss_if_stay_usd", "exit_usd", "exit_cost_usd", "locked_usd", "severity_break_even_free", "severity_break_even_forced"])
        if (x[k] !== want[k]) d2.push(k + " page " + x[k] + " vs model " + want[k]);
      if (x.verdict !== r.verdict) d2.push("verdict " + x.verdict + " vs guide " + r.verdict);
      const badge = document.querySelector("#v-decision .verdict").textContent.toUpperCase();
      if (!badge.startsWith(r.verdict === "EXIT_PARTIAL" ? "EXIT " : r.verdict)) d2.push("badge '" + badge + "'");
      const pc2 = (f) => (f === null ? null : Math.round(f * 10000) / 100);
      [["loss if stay", Math.round(x.loss_if_stay_usd), r.stay], ["exit", Math.round(x.exit_usd), r.exit],
       ["exit cost", Math.round(x.exit_cost_usd), r.cost], ["locked", Math.round(x.locked_usd), r.locked],
       ["break-even free %", pc2(x.severity_break_even_free), pc2(r.beFree)],
       ["break-even forced %", pc2(x.severity_break_even_forced), pc2(r.beForced)]]
        .forEach(([n, g, w]) => { if (g === null || w === null ? g !== w : Math.abs(g - w) > (n.endsWith("%") ? 0.005 : 1)) drift.push(n + " " + g + " (guide " + w + ")"); });
      out.dec.push({ row: r.vault + " " + r.inc + " " + r.amount, d: d2, drift });
    }
    /* 6c. the liquidity-run table */
    const ra = addrOf(${JSON.stringify(vr.runVault)});
    if (ra) {
      fire(document.querySelector("#v-pick"), ra);
      fire(document.querySelector("#v-amt"), String(${vr.runAmount}));
      const run = VAULTS.details[ra.toLowerCase()].incidents.find((i) => i.type === "liquidity_run");
      fire(document.querySelector("#v-inc"), run.key);
      const rows = VV.last().run || [];
      for (const w of ${JSON.stringify(vr.run)}) {
        const g = rows.find((x) => Math.abs(x.others_take - w.share) < 1e-9);
        const ok = g && [["free_usd", w.free], ["forced_usd", w.forced], ["locked_usd", w.locked], ["expected_loss_on_locked_usd", w.loss]]
          .every(([k, v]) => Math.abs(Math.round(g[k]) - v) <= 1);
        out.run.push({ share: w.share, ok: !!ok, got: g ? [g.free_usd, g.forced_usd, g.locked_usd, g.expected_loss_on_locked_usd].map(Math.round) : null });
      }
      out.runShown = document.querySelector("#v-decision table") !== null && document.querySelector("#v-sevstep").hidden;
    }
    /* 6d. the sentence equals the backend's at the default severity and amount */
    for (const e of VAULTS.report.vaults.filter((x) => x.coverage === "full")) {
      fire(document.querySelector("#v-pick"), e.vault_address);
      fire(document.querySelector("#v-amt"), "10000000");
      const v = VAULTS.details[e.vault_address.toLowerCase()];
      for (const inc of v.incidents.filter((i) => i.analyzed !== false && i.type !== "liquidity_run" && i.decision_text)) {
        fire(document.querySelector("#v-inc"), inc.key);
        out.sent.n++;
        /* the backend writes money in full ("2,902,610"); the page writes it as the PT view does ("2.90M"):
           convert the backend's amounts, then every word and every value must match */
        /* the PT view's money rule, written here so the gate does not trust the page's own formatter */
        const short = (v) => { const a = Math.abs(v); return a >= 999500 ? (v / 1e6).toFixed(2) + "M"
          : a >= 1e4 ? Math.round(v / 1e3) + "k" : a >= 1e3 ? (v / 1e3).toFixed(1) + "k" : String(Math.round(v)); };
        const want = inc.decision_text.text.replace(/\\b\\d{1,3}(?:,\\d{3})+\\b(?!\\.\\d|%)/g, (t) => short(+t.replace(/,/g, "")));
        const got = VV.last().sentence, shown = document.querySelector("#v-decision .why").textContent;
        if (got !== want || shown !== got) out.sent.bad.push(e.vault_name + " " + inc.key + ": " + got + " || want " + want);
      }
    }
    /* 6e. messages: a listed vault without numbers, an unknown address, an amount above the vault */
    const other = VAULTS.report.vaults.find((x) => x.coverage !== "full");
    fire(document.querySelector("#v-pick"), other.vault_address);
    out.msgs.notCovered = !document.querySelector("#v-msg").hidden && document.querySelector("#v-cols").hidden;
    fire(document.querySelector("#v-addr"), "0x0000000000000000000000000000000000000001");
    out.msgs.notFound = !document.querySelector("#v-msg").hidden && /not in the analysed list/.test(document.querySelector("#v-msg").textContent);
    fire(document.querySelector("#v-addr"), "0xD6D4B804014EF27836DBE9F8F6BF6C71251548EC");
    fire(document.querySelector("#v-amt"), "10,000,000");
    out.msgs.above = /above the vault's total assets/.test(document.querySelector("#v-msg").textContent)
      && document.querySelector("#v-amt").value === "10,000,000" && VV.last().r.amount < 1e7;
    /* 6f. graph display: one node per chain item, edges drawn, the incident's path marked; same decision as Layers */
    out.graph = { bad: [], vaults: 0, incidents: 0 };
    for (const e of VAULTS.report.vaults.filter((x) => x.coverage === "full")) {
      VV.set({ addr: e.vault_address, amount: 1e6, display: "list" });
      const v = VAULTS.details[e.vault_address.toLowerCase()];
      for (const i of v.incidents.filter((i) => i.analyzed !== false && i.type !== "liquidity_run")) {
        VV.set({ inc: i.key, sev: null, display: "list" });
        const listHot = document.querySelectorAll("#v-chain li.on").length, card = document.querySelector("#v-decision").innerText;
        VV.set({ display: "graph" });
        const nodes = document.querySelectorAll("#v-graph-box [data-vg]").length,
          items = v.dependency_chain.reduce((n, L) => n + L.items.length, 0),
          lines = document.querySelectorAll("#v-edges > line, #v-edges > path").length,
          want = (VV.last().graph || { edges: [] }).edges.length,
          hot = document.querySelectorAll("#v-graph-box .node.hot").length,
          hotE = document.querySelectorAll("#v-edges > .hot").length;
        const tag = e.vault_name + " " + i.key;
        if (nodes !== items) out.graph.bad.push(tag + ": nodes " + nodes + " vs items " + items);
        if (lines !== want || want < items - 1 - (v.dependency_chain[5] || { items: [] }).items.filter((x) => !/vault asset|issuer|depeg/.test(x.label)).length)
          out.graph.bad.push(tag + ": edges drawn " + lines + " of " + want);
        if (hot < 2 || hotE < 1) out.graph.bad.push(tag + ": path marked on " + hot + " nodes, " + hotE + " edges");
        if (hot !== listHot) out.graph.bad.push(tag + ": " + hot + " marked in Graph vs " + listHot + " in Layers");
        if (document.querySelector("#v-decision").innerText !== card) out.graph.bad.push(tag + ": the card changed with the display");
        out.graph.incidents++;
      }
      out.graph.vaults++;
    }
    const belem = VAULTS.report.vaults.find((x) => x.vault_name === "Belem RWA EURCV");
    if (belem) {
      VV.set({ addr: belem.vault_address, display: "graph" });
      const path = [...document.querySelectorAll("#v-graph-box .node.hot .nm")].map((x) => x.textContent).join(" | ");
      out.graph.belem = path;
      if (!path.includes("mGLOeuro / EURCV") || !path.includes("mGLOeuro issuer")) out.graph.bad.push("Belem mGLOeuro path: " + path);
    }
    VV.set({ display: "list" });
    /* back to the PT view: same state and text as before */
    document.querySelector('[data-page="pt"]').click();
    out.ptSame = snap() === before && !document.querySelector("#view-pt").hidden && document.querySelector("#view-vault").hidden;
    fire(document.querySelector("#replay"), "");
    return out;
  })()`);
  gate(vault.vaultShown, "6a. the Vaults switch shows the vault view and hides the PT view (drawer closed)");
  const vok = vault.dec.filter((r) => !r.d.length).length;
  gate(vault.dec.length > 0 && vok === vault.dec.length,
    `6b. vault guide decision rows: ${vok}/${vault.dec.length} give the guide's verdict and badge, and exactly the model's numbers`);
  vault.dec.filter((r) => r.d.length).forEach((r) => console.log(`           ${r.row}: ${r.d.join("; ")}`));
  const drifted = vault.dec.filter((r) => r.drift && r.drift.length);
  if (drifted.length) {
    console.log(`NOTE       6b. ${drifted.length} of the guide's rows differ from the model on today's vault data (raise with the backend):`);
    drifted.forEach((r) => console.log(`           ${r.row}: ${r.drift.join("; ")}`));
  }
  gate(vault.run.length > 0 && vault.run.every((r) => r.ok) && vault.runShown,
    `6c. liquidity-run rows: ${vault.run.filter((r) => r.ok).length}/${vault.run.length} match, shown as a table without a severity slider`);
  vault.run.filter((r) => !r.ok).forEach((r) => console.log(`           share ${r.share}: got ${JSON.stringify(r.got)}`));
  gate(vault.sent.n > 0 && vault.sent.bad.length === 0,
    `6d. vault sentence equals the backend's decision_text (amounts in the page's short form): ${vault.sent.n - vault.sent.bad.length}/${vault.sent.n}`);
  vault.sent.bad.slice(0, 3).forEach((x) => console.log("           " + x));
  gate(vault.msgs.notCovered && vault.msgs.notFound && vault.msgs.above,
    `6e. vault messages: not analysed ${vault.msgs.notCovered}, unknown address ${vault.msgs.notFound}, amount above the vault ${vault.msgs.above}`);
  gate(vault.graph && vault.graph.bad.length === 0 && vault.graph.incidents > 0,
    `6f. vault graph: ${vault.graph ? vault.graph.vaults : 0} vaults, ${vault.graph ? vault.graph.incidents : 0} incidents: one node per item, every derived edge drawn, the path marked as in Layers, same card`);
  if (vault.graph) vault.graph.bad.slice(0, 5).forEach((x) => console.log("           " + x));
  gate(vault.ptSame, "6a. switching back restores the PT view exactly (state, text, controls)");
  vault.bad.forEach((x) => console.log("           " + x));

  gate(p.errors.length === 0, `1. no console errors during checks 1-4${p.errors.length ? ": " + p.errors.slice(0, 3).join(" | ") : ""}`);

  /* phone width and dark mode */
  const phone = await openPage(b, { width: 390 });
  /* read after a pause: on a phone, the browser widens the layout viewport after layout when content overflows */
  const settle = (expr) => `new Promise((ok) => setTimeout(() => ok(${expr}), 600))`;
  const ph = await phone.ev(settle(`({ sw: document.documentElement.scrollWidth, w: innerWidth })`));
  gate(ph.sw <= 391 && ph.w <= 391 && phone.errors.length === 0, `5. phone width 390px: layout ${ph.w}px wide, scrollWidth ${ph.sw}, no errors`);
  const phv = await phone.ev(`(() => { const b = document.querySelector('[data-page="vault"]');
    if (b) b.click();
    const gb = document.querySelector('[data-vdisp="graph"]');
    if (gb) gb.click();   /* the graph display: wide, it must scroll inside its own box */
    return ${settle(`{ has: !!b, sw: document.documentElement.scrollWidth, w: innerWidth }`)}; })()`);
  gate(phv.has && phv.sw <= 391 && phv.w <= 391 && phone.errors.length === 0,
    `5. phone width 390px, vault view (graph display): ${phv.has ? `layout ${phv.w}px wide, scrollWidth ${phv.sw}` : "no vault view"}`);
  const dark = await openPage(b, { dark: true });
  const dk = await dark.ev(`(() => { const c = getComputedStyle(document.body).backgroundColor.match(/\\d+/g).map(Number);
    return { bg: getComputedStyle(document.body).backgroundColor, lum: (c[0] + c[1] + c[2]) / 3 }; })()`);
  gate(dk.lum < 80 && dark.errors.length === 0, `5. dark mode: dark page background (${dk.bg}), no errors`);
} catch (e) {
  gate(false, "check crashed: " + e.message);
} finally {
  b.close();
}
console.log(failures ? `\n${failures} check(s) failed` : "\nAll checks passed");
process.exit(failures ? 1 : 0);
