#!/usr/bin/env node
/* Browser check for web/demo.html (web/CLAUDE.md, "How to verify", steps 1 to 4, plus phone width and dark mode).
   Drives the installed Chrome over the DevTools protocol: no packages, Node 22+ (global WebSocket).
   Usage: node web/check_demo.mjs [--quick] [page.html]   (default web/demo.html; CHROME=/path/to/chrome overrides the
   browser). Full run about 40 s. --quick (about 15 s, while working): the big sweeps sampled (2g one duration, 4b and
   7b fewer cases) and Play only started and stopped, not swept to the end; every gate still runs.
   Exit code 1 on any console error, failed check, acceptance mismatch or a step that hangs (90 s per step). */

import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ARGS = process.argv.slice(2),
  QUICK = ARGS.includes("--quick");
const PAGE = pathToFileURL(resolve(ARGS.find((a) => !a.startsWith("--")) || join(HERE, "demo.html"))).href;
const STEP_MS = +process.env.STEP_MS || 90000;
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

/* ---- the duration path (guide section 5b), written here so the gates do not trust the page's own code: the
   decision for the page's state (S.hours, S.recovers, S.alt), and the inputs o every other function gets */
const DUR = `const durR = (pk = S.pos) => RiskModel.decideAtDuration(d, pk, S.node, S.fail, S.sev, S.hours, S.recovers, S.alt / 100);
  const durO = (pk, r) => { const o = { hours: S.hours, collateral_usd: r.position_value_usd, collateral_oracle_usd: r.collateral_usd,
    debt_usd: r.debt_usd, sale_value_usd: PRE[pk].collateral_usd }; if (S.recovers) o.permanent = 0; return o; };
  /* same words, numbers within 0.2% (a duration moves the PT value slightly) */
  const closeText = (a, b) => { const re = /\\d[\\d,]*(?:\\.\\d+)?/g, na = a.match(re) || [], nb = b.match(re) || [];
    if (a.replace(re, "#") !== b.replace(re, "#") || na.length !== nb.length) return false;
    return na.every((x, i) => { const u = +x.replace(/,/g, ""), v = +nb[i].replace(/,/g, ""); return Math.abs(u - v) <= Math.max(2e-3 * Math.abs(v), 0.011); }); };`;

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

/* ---- the guide's propagation table (section 6), read at run time */
function propRows() {
  const md = readFileSync(GUIDE, "utf8");
  const i = md.indexOf("## 6. "), sec = i < 0 ? "" : md.slice(i, md.indexOf("\n## ", i + 5));
  const rows = [];
  for (const line of sec.split("\n")) {
    const c = line.split("|").slice(1, -1).map((x) => x.trim().replace(/`/g, ""));
    if (c.length !== 7 || !/^(spot|lev_)/.test(c[0])) continue;
    const [node, fail] = c[1].split(":");
    const opts = c[3] === "null" ? null : Function("return (" + c[3] + ")")();
    rows.push({ preset: c[0], node, fail, sev: +c[2].replace("%", ""), opts, states: c[4].split("·").map((x) => x.trim()),
      position: c[5], verdict: c[6] });
  }
  return rows;
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
  /* every step fails after STEP_MS instead of hanging (e.g. a tab sent to the background stops its timers) */
  const ev = async (expr) => {
    let timer;
    const r = await Promise.race([
      s("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true }),
      new Promise((_, no) => (timer = setTimeout(() => no(new Error(`a page step took over ${STEP_MS / 1000} s (hang, or the tab is in the background)`)), STEP_MS))),
    ]).finally(() => clearTimeout(timer));
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text);
    return r.result.value;
  };
  return { ev, errors, s, targetId };
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
      hours: S.hours, recovers: S.recovers, toggle: !!document.querySelector("#rec [data-rec]"),
      reason: (document.querySelector("#rec .rwhy") || { title: "" }).title,
      cardPattern: /Pattern from/.test((card.querySelector(".vtags") || { textContent: "" }).textContent),
      notYours: /not your position/.test(card.textContent),
      replay: document.querySelector("#replay").value };
  })()`);
  gate(first.past === "pt_reusd_aug_2026" && first.pos === "lev_closest_to_liquidation" && first.replay === first.past,
    `1b. first screen preselects ${first.past} on ${first.pos}`);
  gate(first.verdict === "EXIT" && first.banner && first.cardPattern && first.notYours,
    `1b. first screen: verdict ${first.verdict}, event banner ${first.banner}, card says pattern ${first.cardPattern} and not your position ${first.notYours}`);
  gate(first.hours === 1 && first.recovers === true && !first.toggle && first.reason.length > 0,
    `1b. first screen at the event's duration (${first.hours} h, recovers ${first.recovers}), the recovers reason shown instead of a toggle`);

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
    const OLD = ["Type unknown", "Upstream feeds are not resolved yet", "Not resolved. Needs the on-chain crawler",
      "Not verified. Planned: on-chain read from the sUSDe contract", "Starting probabilities are samples"];
    const oldHits = [];
    for (const k of Object.keys(NODES)) { nodeEvidence(k); const tx = document.querySelector("#drawer").innerText; OLD.forEach((o) => tx.includes(o) && oldHits.push(k + ": " + o)); }
    closeDrawer();
    OLD.forEach((o) => document.body.innerText.includes(o) && oldHits.push("page: " + o));
    const hits = oldHits.concat(txt.match(/[^.|\\n]*(detect|anomal|sample alert|invented)[^.|\\n]*/gi) || [])
      .concat(txt.match(/[^.|\\n]*\\bExamples?\\b[^.|\\n]*/g) || []);
    return { hits: hits.slice(0, 4), proto: !!document.querySelector("#proto, #feed") };
  })()`);
  gate(words.hits.length === 0, `2b. no detector or invented-incident wording${words.hits.length ? ": " + words.hits.join(" / ") : ""}`);
  gate(!words.proto, "2b. no prototype bar or example feed");

  /* 2d. "Load a past incident pattern" lists d.past_incidents; each sets node, failure, severity, the duration
     (p.hours, or the default) and the recovers toggle (guide 5b); moving the severity turns it into a what-if */
  const past = await p.ev(`(() => {
    ${DUR}
    if (typeof PAST === "undefined") return { n: 0, bad: ["the page has no d.past_incidents list"], optsMatter: false, whatIf: false };
    const fire = (el, v) => { el.value = v; el.dispatchEvent(new Event("change", { bubbles: true })); };
    const sel = document.querySelector("#replay"), bad = [];
    const keys = [...sel.options].map((o) => o.value).filter(Boolean);
    if (keys.join() !== PAST.map((x) => x.key).join()) bad.push("options " + keys.join() + " vs data " + PAST.map((x) => x.key).join());
    for (const pk of ["spot", "lev_closest_to_liquidation"]) {
      fire(document.querySelector("#pos"), pk);
      for (const x of PAST) {
        fire(sel, x.key);
        const wh = x.hours != null ? x.hours : DEF_H, wr = x.hours != null && !!x.recovers;
        if (S.past !== x.key || S.node !== x.node || S.fail !== x.fail || Math.abs(S.sev - x.sev) > 1e-9 || S.hours !== wh || S.recovers !== wr)
          bad.push(x.key + ": state " + [S.past, S.node, S.fail, S.sev, S.hours, S.recovers].join("/"));
        const want = RiskModel.decideAtDuration(d, pk, x.node, x.fail, x.sev, wh, wr, S.alt / 100), got = model().sev;
        if (JSON.stringify(got) !== JSON.stringify(want))
          bad.push(pk + " " + x.key + ": page " + got.verdict + " " + Math.round(got.loss_if_stay_usd) + " vs decideAtDuration " + want.verdict + " " + Math.round(want.loss_if_stay_usd));
      }
    }
    /* the event's recovery must matter somewhere, or this gate proves nothing */
    const u = PAST.find((x) => x.key === "usde_feb_2026");
    const optsMatter = !!u && RiskModel.decideAtDuration(d, "spot", u.node, u.fail, u.sev, u.hours, true).loss_if_stay_usd
      !== RiskModel.decideAtDuration(d, "spot", u.node, u.fail, u.sev, u.hours, false).loss_if_stay_usd;
    /* past or manual, one or the other (user decision, 11 Oct): in past mode steps 1 and 2 are read-only and a
       severity input changes nothing, a click on a chain node only opens its drawer; Manual keeps the values as a
       what-if with every control editable and no banner; Past again loads the last event chosen */
    fire(sel, PAST[0].key);
    const wrap = sel.closest(".pastwrap"), tip = document.querySelector("#pastBanner"), top0 = document.querySelector("#steps").getBoundingClientRect().top;
    const ro = ["#incBtn", "#sev"].every((q) => document.querySelector(q).disabled) && !!wrap && !wrap.hidden && S.mode === "past"
      /* shown as text, the controls hidden (plan C) */
      && document.querySelector("#casc").hidden && document.querySelector("#sevRow").hidden
      && document.querySelector("#ro1").textContent === COPY.steps.inc(NODES[S.node].label, FAIL[S.fail].label) && document.querySelector("#ro2").textContent === sevText();
    /* the event's description is a tooltip of the asterisk at the select's top right: not shown with the select
       focused, shown with the asterisk focused (keyboard; hover is checked below with the mouse), never moving the
       panel */
    const info = document.querySelector("#pastInfo");
    sel.focus();
    const tipOff = !!wrap && wrap.contains(tip) && !!info && getComputedStyle(tip).display === "none" && sel.getAttribute("aria-describedby") === "pastBanner";
    sel.blur();
    info && info.focus({ focusVisible: true });
    const tipOn = getComputedStyle(tip).display === "block" && /Pattern from/.test(tip.textContent);
    info && info.blur();
    const sv = document.querySelector("#sev"), before = [S.node, S.fail, S.sev].join();
    sv.value = String(+sv.value + 1); sv.dispatchEvent(new Event("input", { bubbles: true }));
    const nb = document.querySelector('button[data-n="usde"]');
    if (nb) nb.click();
    closeDrawer();
    const fixed = [S.node, S.fail, S.sev].join() === before && S.past === PAST[0].key;
    document.querySelector('[data-mode="manual"]').click();
    const still = document.querySelector("#steps").getBoundingClientRect().top === top0;
    const whatIf = S.mode === "manual" && S.past === null && [S.node, S.fail, S.sev].join() === before && wrap.hidden && still
      && !document.querySelector("#casc").hidden && !document.querySelector("#sevRow").hidden && document.querySelector("#ro1").hidden
      && document.querySelector("#pastBanner").hidden && ["#incBtn", "#sev"].every((q) => !document.querySelector(q).disabled)
      && !/Pattern from/.test(document.querySelector("#decision").textContent);
    document.querySelector('[data-mode="past"]').click();
    const back = S.mode === "past" && S.past === PAST[0].key;
    document.querySelector('[data-mode="manual"]').click();
    return { n: keys.length, bad, optsMatter, whatIf: ro && tipOff && tipOn && fixed && whatIf && back, parts: { ro, tipOff, tipOn, fixed, whatIf, still, back } };
  })()`);
  gate(past.bad.length === 0 && past.n > 0, `2d. past events: ${past.n} listed, each sets its incident, duration and recovers toggle; the page equals decideAtDuration${past.bad.length ? ": " + past.bad.slice(0, 3).join("; ") : ""}`);
  gate(past.optsMatter, "2d. the recovers toggle changes the result (USDe Feb 2026 on spot), so the gate above is meaningful");
  /* hover with a real mouse: over the select the description stays hidden, over the asterisk it shows */
  const hv = await p.ev(`(() => { const s = document.querySelector("#replay"); s.value = PAST[0].key; s.dispatchEvent(new Event("change", { bubbles: true }));
    window.scrollTo(0, 0);
    const box = (q) => { const r = document.querySelector(q).getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; };
    return { sel: box("#replay"), info: box("#pastInfo") }; })()`);
  const tipShown = async (pt) => {
    await p.s("Input.dispatchMouseEvent", { type: "mouseMoved", x: pt.x, y: pt.y });
    return p.ev(`getComputedStyle(document.querySelector("#pastBanner")).display === "block"`);
  };
  const overSel = await tipShown(hv.sel), overInfo = await tipShown(hv.info);
  await p.s("Input.dispatchMouseEvent", { type: "mouseMoved", x: 1, y: 1 });
  gate(!overSel && overInfo, `2d. mouse: the past event's description shows over the asterisk (${overInfo}), not over the select (${overSel})`);
  /* every select opens downward under its box (real clicks; base-select where the browser has it) */
  const down = [];
  for (const q of ["#pos", "#replay"]) {
    const bx = await p.ev(`(() => { const e = document.querySelector("${q}"); e.scrollIntoView({ block: "center" }); const b = e.getBoundingClientRect(); return { x: b.left + b.width / 2, y: b.top + b.height / 2 }; })()`);
    await p.s("Input.dispatchMouseEvent", { type: "mousePressed", x: bx.x, y: bx.y, button: "left", clickCount: 1 });
    await p.s("Input.dispatchMouseEvent", { type: "mouseReleased", x: bx.x, y: bx.y, button: "left", clickCount: 1 });
    const r = await p.ev(`new Promise((ok) => setTimeout(() => { const e = document.querySelector("${q}");
      const tops = [...e.querySelectorAll("option")].map((o) => o.getBoundingClientRect()).filter((b) => b.height > 0).map((b) => b.top);
      ok({ base: CSS.supports("appearance", "base-select"), open: e.matches(":open"), below: tops.length > 0 && Math.min(...tops) >= e.getBoundingClientRect().bottom - 1 }); }, 300))`);
    await p.s("Input.dispatchKeyEvent", { type: "keyDown", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 });
    await p.s("Input.dispatchKeyEvent", { type: "keyUp", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 });
    down.push({ q, ...r });
  }
  const badDown = down.filter((r) => r.base && !(r.open && r.below));
  gate(badDown.length === 0, `2d. selects open downward under their box (${down.map((r) => r.q + (r.base ? (r.open && r.below ? " down" : " NOT down") : " native")).join(", ")})`);
  /* step 1's incident menu (user decision, 11 Oct): real mouse and keys. The first level opens downward; hovering a
     dependency with several failures opens them to its right; a click there sets node and failure; a dependency with
     one failure is chosen directly; arrows / right / Enter work; Escape closes */
  const mbad = [];
  await p.ev(`document.querySelector('[data-mode="manual"]').click()`);
  const mmove = async (type, pt) => p.s("Input.dispatchMouseEvent", { type, x: pt.x, y: pt.y, button: "left", buttons: type === "mouseMoved" ? 0 : 1, clickCount: 1 });
  const mclick = async (pt) => { await mmove("mousePressed", pt); await mmove("mouseReleased", pt); };
  const mat = (q) => p.ev(`(() => { const e = document.querySelector(${JSON.stringify(q)}); if (!e) return null; const b = e.getBoundingClientRect(); return { x: b.left + Math.min(40, b.width / 2), y: b.top + b.height / 2, l: b.left, r: b.right, t: b.top, b: b.bottom }; })()`);
  await p.ev(`document.querySelector("#incBtn").scrollIntoView({ block: "center" })`);
  const btn = await mat("#incBtn");
  await mclick(btn);
  const menu = await mat("#incMenu");
  if (!menu || menu.t < btn.b - 1) mbad.push("the first level does not open downward");
  const multi = await p.ev(`Object.keys(NODES).find((k) => fails(k).length > 1)`), single = await p.ev(`Object.keys(NODES).find((k) => fails(k).length === 1)`);
  const it = await mat(`#incMenu > .citem[data-cn="${multi}"]`);
  await mmove("mouseMoved", it);
  const fl = await p.ev(`fails(${JSON.stringify(multi)}).slice(-1)[0]`);
  const sub = await mat(`#incMenu > .citem[data-cn="${multi}"] .citem[data-cf="${fl}"]`);
  if (!sub || sub.l < it.r - 2 - 40) mbad.push("the second level does not open to the right");
  if (sub) await mclick(sub);
  let st = await p.ev(`({ node: S.node, fail: S.fail, open: !document.querySelector("#incMenu").hidden, txt: document.querySelector("#incTxt").textContent })`);
  if (st.node !== multi || st.fail !== fl || st.open || !st.txt.includes(await p.ev(`FAIL[${JSON.stringify(fl)}].label`))) mbad.push("second-level click: " + JSON.stringify(st));
  await mclick(await mat("#incBtn"));
  await mclick(await mat(`#incMenu > .citem[data-cn="${single}"]`));
  st = await p.ev(`({ node: S.node, fail: S.fail })`);
  if (st.node !== single || st.fail !== (await p.ev(`fails(${JSON.stringify(single)})[0]`))) mbad.push("single-failure click: " + JSON.stringify(st));
  /* keys: open, down, right into a second level, Enter */
  const mkey = (k) => p.s("Input.dispatchKeyEvent", { type: "keyDown", key: k, code: k, windowsVirtualKeyCode: { ArrowDown: 40, ArrowRight: 39, Enter: 13, Escape: 27 }[k] });
  await p.ev(`document.querySelector("#incBtn").focus()`);
  await mkey("Enter");
  for (let i = 0; i < 12; i++) { if (await p.ev(`!!(document.activeElement && document.activeElement.querySelector && document.activeElement.querySelector(".csub"))`)) break; await mkey("ArrowDown"); }
  const kn = await p.ev(`document.activeElement.dataset.cn`);
  await mkey("ArrowRight");
  const kf = await p.ev(`document.activeElement.dataset.cf`);
  await mkey("Enter");
  st = await p.ev(`({ node: S.node, fail: S.fail, open: !document.querySelector("#incMenu").hidden })`);
  if (!kf || st.node !== kn || st.fail !== kf || st.open) mbad.push("keys: " + JSON.stringify({ kn, kf, st }));
  await p.ev(`document.querySelector("#incBtn").focus()`);
  await mkey("Enter"); await mkey("Escape");
  if (await p.ev(`!document.querySelector("#incMenu").hidden`)) mbad.push("Escape does not close");
  await p.ev(`document.querySelector('[data-mode="past"]').click()`);
  gate(mbad.length === 0, `2d. incident menu: downward, second level to the right on hover, click sets node and failure, single-failure dependency direct, keys, Escape${mbad.length ? ": " + mbad.join("; ") : ""}`);
  gate(past.whatIf, `2d. past or manual: past = steps 1-2 read-only (severity and chain clicks change nothing), the event's description a tooltip on the asterisk only (hidden with the select focused, the panel does not move), Manual = editable what-if from the same values, Past again = the last event${past.whatIf ? "" : " " + JSON.stringify(past.parts)}`);

  /* 2e. the guide's past-incident table (section 3c), on screen. The page values the position at the end of the
     incident (guide 5b: $164,900 instead of $164,903), so amounts match within 0.1%. The table's oracle and
     liquidation columns used the event's own duration; for an event without one the page uses its default
     duration, so those two columns are compared only for events with a stated duration. */
  const pr = pastRows();
  const presAll = await p.ev(`(() => {
    const rows = ${JSON.stringify(pr)}, out = [];
    let noDur = 0;
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
      eq(Math.round(x.loss_if_stay_usd), r.stay, Math.max(1, r.stay * 1e-3), "loss if stay");
      if (pastOf().hours != null) {
        if (x.oracle_falls !== r.oracle) d2.push("oracle " + x.oracle_falls + " vs " + r.oracle);
        if ((x.liquidated || []).includes(true) !== r.liquidated) d2.push("liquidated " + JSON.stringify(x.liquidated));
      } else noDur++;
      eq(be.start === null ? null : +be.start.toFixed(3), r.beStart, 1e-3, "break-even start");
      eq(be.cap === null ? null : +be.cap.toFixed(3), r.beCap, 1e-3, "break-even cap");
      if (!txt.startsWith(want)) d2.push("screen '" + txt + "' vs '" + want + "'");
      out.push({ row: r.key + " " + r.preset, d: d2 });
    }
    document.querySelector('[data-mode="manual"]').click();
    return { rows: out, noDur, defH: DEF_H };
  })()`);
  const pres = presAll.rows, pnod = presAll.noDur;
  const pok = pres.filter((r) => !r.d.length).length;
  gate(pres.length > 0 && pok === pres.length, `2e. guide 3c past-incident rows: ${pok}/${pres.length} match (model and screen; amounts within 0.1%)`);
  if (pnod) console.log(`NOTE       2e. oracle / liquidated columns not compared on ${pnod} rows: events without a stated duration run at the default ${presAll.defH} h`);
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

  /* 2f. the guide's propagation rows (section 6), in both displays. A row whose opts are a past event's is set through
     that event; one with a duration through the time rail (recovers off unless opts say permanent 0); a row without
     opts (no duration: the oracle switch applies) at 16 h, recovers off. The position step's numbers match within
     0.2% (the page values the PT at the end of the incident). */
  const prow = propRows();
  const prop = await p.ev(`(() => {
    ${DUR}
    const rows = ${JSON.stringify(prow)}, out = [];
    const fire = (el, v) => { el.value = v; el.dispatchEvent(new Event("change", { bubbles: true })); };
    const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
    for (const r of rows) {
      const tag = r.preset + " " + r.node + ":" + r.fail + " " + r.sev + "% " + JSON.stringify(r.opts);
      document.querySelector('[data-mode="manual"]').click();
      fire(document.querySelector("#pos"), r.preset);
      const ev = r.opts && PAST.find((x) => x.node === r.node && x.fail === r.fail && Math.abs(x.sev - r.sev) < 1e-9 && same(x.opts, r.opts));
      if (ev) fire(document.querySelector("#replay"), ev.key);
      else {
        setNode(r.node, r.fail, r.sev);
        S.recovers = !!r.opts && r.opts.permanent === 0;
        setHours(r.opts && r.opts.hours != null ? r.opts.hours : 16);
      }
      const d2 = [], pg = model().pg;
      if (!pg) { out.push({ tag, d: ["no propagation on the page"] }); continue; }
      for (const view of ["list", "graph"]) {
        document.querySelector('[data-view="' + view + '"]').click();
        if (view === "list") {
          const st = [...document.querySelectorAll("#chain .lay[data-ln]")].map((x) => x.dataset.state);
          if (st.join() !== r.states.join()) d2.push("layers " + st.join(" · "));
          const pos = document.querySelector("#chain .lay.pos .eff");
          if (!pos || !closeText(pos.textContent, r.position)) d2.push("position row '" + (pos && pos.textContent) + "'");
        } else {
          const lit = [...document.querySelectorAll("#graph .node.hot")].map((x) => x.dataset.g);
          const hotLayers = new Set(pg.layers.filter((l) => l.state === "origin" || l.state === "hit").map((l) => l.n));
          const layerOf = (k) => (k === "pos" ? 0 : NODES[k].layer);
          lit.filter((k) => k !== "pos" && !hotLayers.has(layerOf(k))).forEach((k) => d2.push("graph lights " + k + " on an unchanged layer"));
          hotLayers.forEach((n) => { if (!lit.some((k) => layerOf(k) === n)) d2.push("graph: no node lit on layer " + n); });
          const o = document.querySelector('#graph .node.origin');
          if (!o || o.dataset.g !== pg.origin.node) d2.push("graph origin " + (o && o.dataset.g));
        }
      }
      if (model().verdict !== r.verdict) d2.push("verdict " + model().verdict);
      document.querySelector('[data-view="list"]').click();
      out.push({ tag, d: d2 });
    }
    document.querySelector('[data-mode="manual"]').click();
    return out;
  })()`);
  const pdone = prop, prok = pdone.filter((r) => !r.d.length).length;
  gate(pdone.length > 0 && prok === pdone.length, `2f. guide 6 propagation rows: ${prok}/${pdone.length} match in both displays (layer states, position step, verdict, lit graph)`);
  pdone.filter((r) => r.d.length).forEach((r) => console.log(`           ${r.tag}: ${r.d.join("; ")}`));

  /* 2g. card, zones, path and spread list agree, for every preset x failure (two severities, two durations) and every
     past event: the card equals decideAtDuration; the zones, decisionText and propagation equal the model's with its
     inputs o and its carry (guide 5b, one mechanism); card, decisionText and propagation give one verdict; the card's
     sentence is the headline; the spread list is the steps, ending with the result */
  const agree2 = await p.ev(`(() => {
    ${DUR}
    const bad = []; let n = 0, failed = 0;
    const fire = (el, v) => { el.value = v; el.dispatchEvent(new Event("change", { bubbles: true })); };
    const one = (tag) => {
      const m = model(), r = durR(), o = durO(S.pos, r), cy = r.carry, f = FAIL[S.fail];
      if (!m.pg || !m.t) { bad.push(tag + ": no propagation / decisionText on the page"); return; }
      if (JSON.stringify(m.sev) !== JSON.stringify(r)) bad.push(tag + ": card differs from decideAtDuration");
      if (JSON.stringify(m.be) !== JSON.stringify(RiskModel.breakEvenSeverity(d, S.pos, S.node, S.fail, cy, f.min, f.max, 400, o))) bad.push(tag + ": zones differ from breakEvenSeverity with the duration inputs");
      const t = RiskModel.decisionText(d, S.pos, S.node, S.fail, S.sev, cy, o), pg = RiskModel.propagation(d, S.pos, S.node, S.fail, S.sev, cy, o);
      if (JSON.stringify(m.t) !== JSON.stringify(t)) bad.push(tag + ": decisionText differs from the model");
      if (JSON.stringify(m.pg) !== JSON.stringify(pg)) bad.push(tag + ": propagation differs from the model");
      if (!(m.verdict === t.verdict && t.verdict === pg.verdict)) bad.push(tag + ": verdicts " + [m.verdict, t.verdict, pg.verdict].join("/"));
      if (t.unchecked.length || pg.unchecked.length) bad.push(tag + ": unchecked numbers");
      /* the card repeats nothing the page shows (user decision, 11 Oct): no incident / severity label, an action-only
         sentence (Exit: the amount sold; Stay: keep), the backend's headline as its tooltip, no position paragraph */
      const whyEl = document.querySelector("#decision .why"), r0 = m.sev;
      if (r0.verdict === "EXIT" ? !whyEl || !whyEl.textContent.includes(money(r0.sell_usd)) || whyEl.title !== t.headline
          : r0.verdict === "STAY" ? !whyEl || !/^Keep the position/.test(whyEl.textContent) : !!whyEl)
        bad.push(tag + ": action line '" + (whyEl ? whyEl.textContent : "") + "'");
      if (document.querySelector("#decision .lbl") || /^Position: /m.test(document.querySelector("#decision .dbody").innerText)) bad.push(tag + ": incident label or position paragraph still on the card");
      /* not on the card (user decision, 11 Oct): the break-even sentence, the propagation rule, the model / source note */
      const card = document.querySelector("#decision .dbody").textContent;
      if (card.includes(t.break_even) || card.includes(cap1(t.rule)) || /come from the backend model/.test(card)) bad.push(tag + ": break-even, rule or source note still on the card");
      const lis = [...document.querySelectorAll("#spread li")];
      if (lis.length !== pg.steps.length) bad.push(tag + ": spread list " + lis.length + " vs " + pg.steps.length + " steps");
      pg.steps.forEach((x, i) => { if (lis[i] && !lis[i].textContent.startsWith(x.text)) bad.push(tag + ": spread step " + i); });
      const res = pg.steps[pg.steps.length - 1];
      if (res.node !== "result" || !res.text.startsWith(pg.verdict)) bad.push(tag + ": last step is not the result");
      const pos = pg.steps.find((x) => x.node === "position"), row = document.querySelector("#chain .lay.pos .eff");
      if (pos && (!row || row.textContent !== pos.text)) bad.push(tag + ": position row differs from the position step");
      /* the explainer's form: each layer row = "Layer n · name", its state badge and its text; the result card = the
         verdict and the result step; no static layer facts */
      const lays = [...document.querySelectorAll("#chain .lay[data-ln]")];
      pg.layers.forEach((l, i) => {
        const el = lays[i];
        if (!el || !el.querySelector(".lname2").textContent.startsWith("Layer " + l.n + " · ")
            || el.querySelector(".st").textContent !== (COPY.layers.state[l.state] || l.state) || el.querySelector(".eff").textContent !== l.text)
          bad.push(tag + ": layer " + l.n + " row");
      });
      const rc = document.querySelector("#chain .lay.res");
      if (!rc || rc.querySelector(".vb").textContent !== pg.verdict || rc.querySelector(".eff").textContent !== res.text) bad.push(tag + ": result card");
      if (document.querySelector("#chain .fact")) bad.push(tag + ": a static layer fact is still shown");
    };
    const check = (tag) => { n++; const b = bad.length; try { one(tag); } catch (e) { bad.push(tag + ": " + e); } if (bad.length > b) failed++; };
    document.querySelector('[data-view="list"]').click();
    document.querySelector('[data-mode="manual"]').click();
    for (const pk of Object.keys(PRE)) {
      fire(document.querySelector("#pos"), pk);
      for (const [h, rec] of ${QUICK} ? [[24, false]] : [[6, true], [6, false], [24, true], [24, false]]) {
        setHours(h); S.recovers = rec;
        for (const k of Object.keys(NODES)) for (const f of fails(k))
          for (const sv of [FAIL[f].def, FAIL[f].max]) { setNode(k, f, sv); check(pk + " " + k + ":" + f + " @" + sv + " " + h + "h rec " + rec); }
      }
      for (const x of (typeof PAST !== "undefined" ? PAST : [])) { fire(document.querySelector("#replay"), x.key); check(pk + " past " + x.key); document.querySelector('[data-mode="manual"]').click(); }
    }
    return { n, failed, bad };
  })()`);
  gate(agree2.n > 0 && agree2.bad.length === 0, `2g. card, path and spread list agree with decisionText and propagation: ${agree2.n - agree2.failed}/${agree2.n} cases`);
  agree2.bad.slice(0, 5).forEach((x) => console.log("           " + x));

  /* 3. every preset x every failure of every node, through the page's own controls */
  const sweep = await p.ev(`(() => {
    const bad = []; let n = 0;
    const fire = (el, v) => { el.value = v; el.dispatchEvent(new Event("change", { bubbles: true })); };
    document.querySelector('[data-mode="manual"]').click();   /* what-if tests: no past event */
    for (const pk of Object.keys(PRE)) {
      fire(document.querySelector("#pos"), pk);
      for (const k of Object.keys(NODES)) for (const f of fails(k)) {
        try {
          setNode(k, f);
          const v = document.querySelector("#decision .verdict");
          if (!v || !v.textContent.trim()) bad.push(pk + " " + k + ":" + f);
          n++;
        } catch (e) { bad.push(pk + " " + k + ":" + f + " " + e); }
      }
    }
    return { n, bad };
  })()`);
  gate(sweep.bad.length === 0 && sweep.n > 0, `3. presets x failures rendered: ${sweep.n}${sweep.bad.length ? " failed " + sweep.bad.slice(0, 5).join("; ") : ""}`);

  /* 3b. "What would change the answer" is RiskModel.sensitivity (guide section 5): the page's result equals the model's
     with decideAtDuration's inputs and carry (guide 5b), and the screen shows its candidates, flips, the other
     positions in their own group and the weakest assumption */
  const sens = await p.ev(`(() => {
    ${DUR}
    const bad = []; let n = 0, failed = 0;
    const fire = (el, v) => { el.value = v; el.dispatchEvent(new Event("change", { bubbles: true })); };
    const VW = ((typeof COPY !== "undefined" && COPY.sens) || {}).verdict || {};
    const check = (tag) => {
      n++;
      const before = bad.length;
      try { checkOne(tag); } catch (e) { bad.push(tag + ": " + e); }
      if (bad.length > before) failed++;
    };
    const checkOne = (tag) => {
      const m = model();
      if (!m.sv) { bad.push(tag + ": no sensitivity on the page"); return; }
      const r = durR(), want = RiskModel.sensitivity(d, S.pos, S.node, S.fail, S.sev, r.carry, durO(S.pos, r));
      if (JSON.stringify(m.sv) !== JSON.stringify(want)) bad.push(tag + ": page result differs from the model");
      const box = document.querySelector("#d-flip");
      if (!box) { bad.push(tag + ": no 'What would change the answer' block"); return; }
      const rows = [...box.querySelectorAll("table.sens tbody tr:not(.grp)")];
      /* shown in the page's order: this position's own assumptions, then the other positions as their own group */
      const order = want.candidates.filter((c) => !c.comparison).concat(want.candidates.filter((c) => c.comparison));
      if (rows.length !== order.length) bad.push(tag + ": " + rows.length + " rows vs " + order.length + " candidates");
      order.forEach((c, i) => {
        const r = rows[i]; if (!r) return;
        const t = r.children[1].textContent;
        if (!t.startsWith(VW[c.verdict] || c.verdict)) bad.push(tag + " row " + i + ": '" + t + "' vs " + c.verdict);
        if (r.classList.contains("flip") !== c.flips) bad.push(tag + " row " + i + ": flip mark " + r.classList.contains("flip") + " vs " + c.flips);
        if (r.children[0].textContent !== c.alternative) bad.push(tag + " row " + i + ": alternative text");
      });
      const grp = !!box.querySelector("table.sens tr.grp"), hasCmp = want.candidates.some((c) => c.comparison);
      if (grp !== hasCmp) bad.push(tag + ": other-positions group " + grp + " vs " + hasCmp);
      /* the weakest assumption is said once, on the card (the fold's own line repeated it) */
      const head = [...document.querySelectorAll("#decision .dbody > p.note")].map((x) => x.textContent).join(" | ");
      if (box.querySelector(".sens-head") || (want.weakest ? !head.includes(want.weakest.alternative) : !head.includes((COPY.sens || {}).robust))) bad.push(tag + ": weakest line '" + head + "'");
      if (/Position preset/.test(box.textContent)) bad.push(tag + ": the page-built 'Position preset' row is still there");
    };
    document.querySelector('[data-mode="manual"]').click();
    for (const pk of Object.keys(PRE)) {
      fire(document.querySelector("#pos"), pk);
      for (const k of Object.keys(NODES)) for (const f of fails(k))
        for (const sv of [FAIL[f].def, FAIL[f].max]) { setNode(k, f, sv); check(pk + " " + k + ":" + f + " @" + sv); }
    }
    for (const pk of Object.keys(PRE)) {
      fire(document.querySelector("#pos"), pk);
      for (const x of PAST) { fire(document.querySelector("#replay"), x.key); check(pk + " past " + x.key); }
    }
    document.querySelector('[data-mode="manual"]').click();
    return { n, bad, failed };
  })()`);
  gate(sens.n > 0 && sens.bad.length === 0, `3b. "What would change the answer" is RiskModel.sensitivity: ${sens.n - sens.failed}/${sens.n} cases (model, rows, flips, groups, weakest)`);
  sens.bad.slice(0, 5).forEach((x) => console.log("           " + x));

  /* 4. acceptance table (section 9): the model rows exactly (decideAt, carry 0, the data's range), then the screen.
     The table has no duration (the oracle switch applies, the loss stays): the page is set to 16 h on the rail,
     recovers off, and its amounts match within 0.1% (the PT valued at the end of the incident). */
  const rows = acceptanceRows();
  const atPage = rows;
  const mres = await p.ev(`(() => {
    const out = [];
    for (const r of ${JSON.stringify(atPage)}) {
      const ds = RiskModel.atSize(window.DASHBOARD, r.size), t = ds.failure_types.types[r.fail],
        x = RiskModel.decideAt(ds, r.preset, r.node, r.fail, r.sev, 0),
        be = RiskModel.breakEvenSeverity(ds, r.preset, r.node, r.fail, 0, t.min, t.max), dd = [];
      const eq = (a, b, tol, name) => { if (a === null || b === null ? a !== b : Math.abs(a - b) > tol) dd.push(name + " " + a + " vs " + b); };
      if (x.verdict !== r.verdict) dd.push("verdict " + x.verdict);
      eq(Math.round(x.sell_fraction * 100), r.sell, 0, "sell %");
      eq(Math.round(x.sale_cost_usd), r.sale, 1, "sale cost");
      eq(Math.round(x.loss_if_stay_usd), r.stay, 1, "loss if stay");
      eq(Math.round(x.loss_kept_usd), r.kept, 1, "loss kept");
      eq(+x.sellable_later.toFixed(4), r.later, 1e-4, "sellable later");
      eq(be.start === null ? null : +be.start.toFixed(3), r.beStart, 1e-3, "break-even start");
      eq(be.cap === null ? null : +be.cap.toFixed(3), r.beCap, 1e-3, "break-even cap");
      out.push({ row: r.size / 1e6 + "M " + r.preset + " " + r.node + ":" + r.fail + " @" + r.sev, d: dd });
    }
    return out;
  })()`);
  const mok = mres.filter((r) => !r.d.length).length;
  gate(mok === mres.length && mres.length > 0, `4. acceptance rows at every size, model (atSize, decideAt, carry 0): ${mok}/${mres.length} match exactly`);
  mres.filter((r) => r.d.length).forEach((r) => console.log(`           ${r.row}: ${r.d.join("; ")}`));
  const res = await p.ev(`(() => {
    const rows = ${JSON.stringify(atPage)}, out = [];
    const fire = (el, v) => { el.value = v; el.dispatchEvent(new Event("change", { bubbles: true })); };
    document.querySelector('[data-mode="manual"]').click();   /* section 9 rows are what-if tests */
    for (const r of rows) {
      /* the size through the page's own field, typed as a manager would ("7,000,000") */
      fire(document.querySelector("#pos"), "spot");
      fire(document.querySelector("#size"), r.size.toLocaleString("en-US"));
      fire(document.querySelector("#pos"), r.preset);
      setNode(r.node, r.fail, r.sev);
      S.recovers = false;
      setHours(16);
      const m = model(), x = m.sev, be = m.be, txt = document.querySelector("#decision .verdict").textContent;
      const want = r.verdict === "STAY" ? "Stay" : r.verdict === "EXIT" ? "Exit" : "Sell " + money(x.sell_usd);
      const d = [];
      const eq = (a, b, tol, name) => { if (a === null || b === null ? a !== b : Math.abs(a - b) > tol) d.push(name + " " + a + " vs " + b); };
      if (x.verdict !== r.verdict) d.push("verdict " + x.verdict + " vs " + r.verdict);
      eq(Math.round(x.sell_fraction * 100), r.sell, 0, "sell %");
      eq(Math.round(x.sale_cost_usd), r.sale, 1, "sale cost");
      eq(Math.round(x.loss_if_stay_usd), r.stay, Math.max(1, r.stay * 1e-3), "loss if stay");
      eq(Math.round(x.loss_kept_usd), r.kept, Math.max(1, r.kept * 1e-3), "loss kept");
      if (x.oracle_falls !== r.oracle) d.push("oracle " + x.oracle_falls + " vs " + r.oracle);
      eq(+x.sellable_later.toFixed(4), r.later, 1e-4, "sellable later");
      eq(be.start === null ? null : +be.start.toFixed(3), r.beStart, 1e-3, "break-even start");
      eq(be.cap === null ? null : +be.cap.toFixed(3), r.beCap, 1e-3, "break-even cap");
      if (!txt.startsWith(want)) d.push("screen '" + txt + "' vs '" + want + "'");
      if (Math.abs(d.size_usd - r.size) > 1e-6) d.push("page size " + d.size_usd);
      out.push({ row: r.size / 1e6 + "M " + r.preset + " " + r.node + ":" + r.fail + " @" + r.sev, d });
    }
    fire(document.querySelector("#pos"), "spot");
    fire(document.querySelector("#size"), "10,000,000");
    return out;
  })()`);
  const ok = res.filter((r) => !r.d.length).length;
  gate(ok === res.length && res.length > 0, `4. acceptance rows at every size, screen (size typed in the header, 16 h, recovers off): ${ok}/${res.length} match (amounts within 0.1%)`);
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
    document.querySelector('[data-mode="manual"]').click();
    for (const pk of Object.keys(PRE)) {
      fire(document.querySelector("#pos"), pk);
      for (const k of Object.keys(NODES)) for (const f of fails(k)) {
        const fl = FAIL[f];
        for (const sv of ${QUICK} ? [fl.def, fl.max] : [fl.min, fl.def, (fl.min + fl.max) / 2, fl.max]) {
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


  /* 4c. the exit chart is RiskModel.actCostCurve with the card's inputs (user report, 11 Oct: it ignored the cash
     yield and step 2): its lines are the model's rows, it moves with the cash yield, the severity and the duration,
     and the recommended dot sits on the lowest total */
  const ex4 = await p.ev(`(async () => {
    ${DUR}
    const bad = []; let n = 0;
    const fire = (el, v) => { el.value = v; el.dispatchEvent(new Event("change", { bubbles: true })); };
    const pts = () => [...document.querySelectorAll("#chart polyline")].map((x) => x.getAttribute("points")).join("|");
    document.querySelector('[data-mode="manual"]').click();
    for (const pk of Object.keys(PRE)) {
      fire(document.querySelector("#pos"), pk);
      for (const k of Object.keys(NODES)) for (const f of fails(k)) {
        setNode(k, f);
        const r = durR(), want = RiskModel.actCostCurve(d, S.pos, S.node, S.fail, S.sev, r.carry, durO(S.pos, r)), m = model();
        n++;
        if (JSON.stringify(m.ac) !== JSON.stringify(want)) { bad.push(pk + " " + k + ":" + f + ": chart data differs from actCostCurve"); continue; }
        const tag = pk + " " + k + ":" + f;
        for (const [cls, key] of [["ln-sale", "sale_cost_usd"], ["ln-kept", "loss_kept_usd"], ["ln-total", "total_usd"]]) {
          const ln = document.querySelector("#chart polyline." + cls);
          if (!ln || ln.getAttribute("points").trim().split(/\\s+/).length !== want.rows.length) bad.push(tag + ": line " + cls);
        }
        /* the lowest total is marked, and it is the card's decision */
        const dot = document.querySelector("#chart .best-dot"), best = want.rows.reduce((a, b) => (b.total_usd < a.total_usd - 1e-9 ? b : a));
        if (!dot || Math.abs(best.fraction - m.x) > 1e-9 || !document.querySelector("#chart .best-lbl").textContent.includes(money(best.total_usd))) bad.push(tag + ": lowest total mark");
        /* the caption names the card's verdict and amounts; the break-even line is the card's m.be */
        /* the severity slider's own track carries the zones, split at the break-even severities on its scale */
        const sv = document.querySelector("#sev"), zoned = m.be.start !== null || m.hasLoss;
        const pos = (v) => { const x = v === null ? 2 : isLog(m.f) ? sevPos(m.f, v) / LOGR : (v - m.f.min) / (m.f.max - m.f.min);
          return x <= 1e-9 ? -1 : x >= 1 - 1e-9 ? 2 : x; };
        if (sv.classList.contains("zoned") !== zoned || (zoned && (Math.abs(+sv.style.getPropertyValue("--za") - pos(m.be.start)) > 1e-3
            || Math.abs(+sv.style.getPropertyValue("--zb") - pos(m.be.cap)) > 1e-3))) bad.push(tag + ": severity track zones");
        /* the card is about liquidity (plan A): no verdict caption; today vs after as two bars, from the model; the
           chart, break-even and cash line in the "Cost of selling" fold */
        const bel = document.querySelector("#exit .cbe").textContent, lb = [...document.querySelectorAll("#exit .lbars .bv")].map((x) => x.textContent);
        if (document.querySelector("#exit .cverdict") || !document.querySelector("#d-cost #chart") || lb[0] !== money(r.sellable_now * m.C)) bad.push(tag + ": liquidity card '" + lb.join(" / ") + "'");
        const bv = (x) => (x === null ? COPY.exit.beNever : sevText(x));
        if (!bel.includes(bv(m.be.start)) || !bel.includes(bv(m.be.cap))) bad.push(tag + ": break-even line '" + bel + "'");
      }
    }
    /* it moves with the cash yield, the severity and the duration */
    fire(document.querySelector("#pos"), "spot");
    setNode("usde", "depeg", 10);
    const p0 = pts();
    /* the cash yield acts while typing (input events), as the explainer's slider */
    const alt = document.querySelector("#alt");
    alt.value = "1"; alt.dispatchEvent(new Event("input", { bubbles: true }));
    await new Promise((ok) => requestAnimationFrame(() => requestAnimationFrame(ok)));
    const p1 = pts(), live = S.alt === 1 && /Cash earns 1\\.00%/.test(document.querySelector("#carryLine").textContent);
    fire(alt, "1");
    setNode("usde", "depeg", 20);
    const p2 = pts();
    setHours(48);
    const p3 = pts();
    fire(document.querySelector("#alt"), (d.position.implied_apy * 100).toFixed(2));
    const moves = { alt: p1 !== p0 && live, severity: p2 !== p1, duration: p3 !== p2 };
    /* sliders show their position only: no native fill, no separate zone bar */
    if (document.querySelector("#zoneBox, .zones") || [...document.querySelectorAll("input[type=range]")].some((x) => getComputedStyle(x).appearance !== "none"))
      bad.push("a slider still draws a progress fill or a separate zone bar");
    if (!moves.alt || !moves.severity || !moves.duration) bad.push("the chart does not move with " + JSON.stringify(moves));
    return { n, bad };
  })()`);
  gate(ex4.bad.length === 0, `4c. exit chart = RiskModel.actCostCurve with the card's inputs (${ex4.n} cases: sale cost, loss kept and total lines, the lowest total marked = the card's sale, caption and break-even line from the card, the severity track's zones at the break-evens, no progress fills), moving with the cash yield (live while typing), the severity and the duration`);
  ex4.bad.slice(0, 5).forEach((x) => console.log("           " + x));

  /* 7. time rail (guide 5b and 6, to-do 7): marks, one duration control, the recovers toggle, keys, event clicks,
     the guide's two examples, Play */
  const rail = await p.ev(`(async () => {
    const out = { bad: [], marks: 0, toggles: 0 };
    const fire = (el, v) => { el.value = v; el.dispatchEvent(new Event("change", { bubbles: true })); };
    const lay = (n) => document.querySelector('#chain .lay[data-ln="' + n + '"]').dataset.state;
    document.querySelector('[data-view="list"]').click();
    document.querySelector('[data-mode="manual"]').click();
    const TLH = d.oracle.challenge_timelock_s / 3600, EXP = d.time_model.days_to_expiry * 24;
    /* a. one red mark per event at its duration, the two grey reference marks; the toggle exactly where the model
       shows it, its reason otherwise */
    for (const pk of Object.keys(PRE)) {
      fire(document.querySelector("#pos"), pk);
      for (const k of Object.keys(NODES)) for (const f of fails(k)) {
        setNode(k, f);
        const tag = pk + " " + k + ":" + f;
        const ev = RiskModel.propagationEvents(d, pk, k, f, S.sev, S.recovers, S.alt / 100);
        const marks = [...document.querySelectorAll("#rmarks .rm.ev")].map((x) => +x.dataset.h);
        if (marks.length !== ev.events.length || marks.some((h, i) => Math.abs(h - ev.events[i].hours) > 1e-6))
          out.bad.push(tag + ": marks " + marks.join() + " vs events " + ev.events.map((e) => e.hours).join());
        const refs = [...document.querySelectorAll("#rmarks .rm.ref:not(.pm)")].map((x) => +x.dataset.h);
        if (refs.length !== 2 || Math.abs(refs[0] - TLH) > 1e-9 || Math.abs(refs[1] - EXP) > 1e-9) out.bad.push(tag + ": reference marks " + refs.join());
        out.marks += marks.length;
        const rt = RiskModel.recoveryToggle(d, k, f), tg = document.querySelectorAll("#rec [data-rec]").length === 2,
          why = (document.querySelector("#rec .rwhy") || { title: "" }).title;
        if (tg !== rt.show || why !== rt.reason.replace(/ \\(grade [A-D]\\)/g, "")) out.bad.push(tag + ": toggle " + tg + " vs " + rt.show + ", reason '" + why + "'");
        out.toggles += tg;
      }
    }
    /* b. one duration control on the page: the rail's thumb; the only range input is the severity */
    /* the range inputs are step 2's two sliders (severity, cash yield): neither is a duration */
    const sliders = document.querySelectorAll("#view-pt [role=slider]").length,
      ranges = [...document.querySelectorAll("#view-pt input[type=range]")].map((x) => x.id).sort().join();
    /* the duration events are on the rail only (no list, user decision, 11 Oct): each mark says its change */
    const tips = [...document.querySelectorAll("#rmarks .rm.ev")].every((x) => /^From /.test(x.title));
    if (document.querySelector("#revents") || !tips || document.querySelector("#steps #d-tl")) out.bad.push("an events list is back, a mark has no tooltip, or the timeline chart is in the inputs");
    if (sliders !== 1 || ranges !== "alt,sev" || document.querySelector("#durNote"))
      out.bad.push("duration controls: " + sliders + " sliders, " + ranges + " range inputs");
    /* c. keys: arrows 1% of the rail, PageUp 10% */
    fire(document.querySelector("#pos"), "lev_closest_to_liquidation");
    setNode("usde", "depeg", 3);
    document.querySelector('#rec [data-rec="1"]').click();
    setHours(6);
    const th = document.querySelector("#rthumb"), key = (k) => th.dispatchEvent(new KeyboardEvent("keydown", { key: k, bubbles: true }));
    const u0 = uOf(S.hours);
    key("ArrowRight");
    if (Math.abs(uOf(S.hours) - u0 - 0.01) > 1e-9 || th.getAttribute("aria-valuetext") !== durText(S.hours)) out.bad.push("ArrowRight: u " + uOf(S.hours));
    key("PageUp");
    if (Math.abs(uOf(S.hours) - u0 - 0.11) > 1e-9) out.bad.push("PageUp: u " + uOf(S.hours));
    key("ArrowLeft"); key("PageDown");
    if (Math.abs(S.hours - 6) > 1e-6) out.bad.push("back to 6 h: " + S.hours);
    /* the duration can be typed too: hours, or h / d / w; clamped to 1 h .. 180 days; unreadable text restores it */
    const di = document.querySelector("#durIn");
    for (const [typed, want] of [["16", 16], ["16h", 16], ["3d", 72], ["2 days", 48], ["1w", 168], ["400d", 4320], ["0.2h", 1], ["abc", 1], ["6 h", 6]]) {
      fire(di, typed);
      if (Math.abs(S.hours - want) > 1e-9 || di.value !== durText(S.hours) || th.getAttribute("aria-valuetext") !== durText(S.hours))
        out.bad.push("typed duration '" + typed + "': " + S.hours + " h, field '" + di.value + "'");
    }
    if (!/^Time frame$/.test(document.querySelector("#rail .q").textContent) || !/lasted:$/.test(document.querySelector("#rail .rlt").textContent)
        || document.querySelector("#steps .q i, #view-vault .q i"))
      out.bad.push("time frame heading, label, or a step number left");
    /* d. the guide's main example (section 6): the 3% USDe depeg on the closest borrower, recovers on, cash 4%: one
       event at 16 h, layers 3 and 5 unchanged -> hit, STAY -> EXIT; a click on it moves the thumb past it, the layers
       it names change, and they flash */
    fire(document.querySelector("#alt"), "4");
    const ev = eventsOf();
    const e0 = ev.events[0];
    out.example = ev.events.map((e) => [+e.hours.toFixed(1), e.verdict_before, e.verdict_after, e.layers.map((l) => l.n + ":" + l.from + ">" + l.to).join(" ")]);
    if (ev.events.length !== 1 || Math.abs(e0.hours - 16) > 1e-3 || e0.verdict_before !== "STAY" || e0.verdict_after !== "EXIT"
        || e0.layers.map((l) => l.n).join() !== "3,5") out.bad.push("guide example 16 h: " + JSON.stringify(out.example));
    const before = e0 ? e0.layers.map((l) => lay(l.n)) : [];
    const wasVerdict = model().verdict;
    document.querySelector('#rmarks .rm.ev[data-evh="0"]').click();
    if (!e0 || Math.abs(S.hours - e0.hours * 1.0005) > 1e-9) out.bad.push("event click: thumb at " + S.hours);
    const after = e0 ? e0.layers.map((l) => lay(l.n)) : [];
    if (e0 && (before.join() !== e0.layers.map((l) => l.from).join() || after.join() !== e0.layers.map((l) => l.to).join()))
      out.bad.push("event click: layers " + before.join() + " -> " + after.join());
    if (wasVerdict !== "STAY" || model().verdict !== "EXIT") out.bad.push("event click: verdict " + wasVerdict + " -> " + model().verdict);
    const fl = [...document.querySelectorAll("#chain .lay.flash")].map((x) => x.dataset.ln).join();
    if (e0 && fl !== e0.layers.map((l) => l.n).join()) out.bad.push("flash on layers " + fl);
    if (!document.querySelector("#rmarks .rm.ev.passed")) out.bad.push("the passed event is not marked");
    /* the second example: susde:discount 0.5%, one event at 4,190.4 h, STAY -> EXIT */
    setNode("susde", "discount", 0.5);
    const ev2 = eventsOf().events;
    out.example2 = ev2.map((e) => [+e.hours.toFixed(1), e.verdict_before, e.verdict_after]);
    if (ev2.length !== 1 || Math.abs(ev2[0].hours - 4190.4) > 0.1 || ev2[0].verdict_after !== "EXIT") out.bad.push("guide example 4,190.4 h: " + JSON.stringify(out.example2));
    /* e. Play from 1 h: pauses past the event, reaches the end and stops; the label toggles (about 10 s; --quick:
       only that it starts) */
    setNode("usde", "depeg", 3);
    setHours(1);
    const play = document.querySelector("#play");
    play.click();
    const labelOn = play.textContent, t0 = performance.now();
    let paused = false;
    if (${QUICK}) {
      out.play = { quick: true, on: PLAY.on, labelOn };
      if (!PLAY.on || labelOn !== COPY.rail.pause) out.bad.push("play did not start: " + JSON.stringify(out.play));
      play.click();
    } else while (PLAY.on && performance.now() - t0 < 30000) {
      await new Promise((ok) => setTimeout(ok, 100));
      if (PLAY.hold > 0 && Math.abs(S.hours - 16 * 1.0005) < 1e-6) paused = true;
    }
    if (!${QUICK}) out.play = { ms: Math.round(performance.now() - t0), end: S.hours, labelOn, labelOff: play.textContent, paused };
    if (!${QUICK} && (PLAY.on || S.hours !== H_MAX || labelOn !== COPY.rail.pause || play.textContent !== COPY.rail.play || !paused))
      out.bad.push("play: " + JSON.stringify(out.play));
    /* a drag or a key stops Play */
    setHours(1); play.click(); key("ArrowRight");
    if (PLAY.on) out.bad.push("a key did not stop Play");
    fire(document.querySelector("#alt"), (d.position.implied_apy * 100).toFixed(2));
    return out;
  })()`);
  /* a real pointer drag on the track: press at 20% of the rail, move to 60%, release (pointer capture) */
  const tr = await p.ev(`(() => { document.querySelector('[data-mode="manual"]').click();
    document.querySelector("#rail").scrollIntoView({ block: "center" });
    const r = document.querySelector("#rtrack").getBoundingClientRect(); return { x: r.left, w: r.width, y: r.top + r.height / 2 }; })()`);
  const mouse = (type, u) => p.s("Input.dispatchMouseEvent", { type, x: tr.x + tr.w * u, y: tr.y, button: "left", buttons: type === "mouseReleased" ? 0 : 1, clickCount: 1 });
  await mouse("mousePressed", 0.2);
  const atPress = await p.ev(`uOf(S.hours)`);
  await mouse("mouseMoved", 0.6);
  await mouse("mouseReleased", 0.6);
  const dragged = await p.ev(`new Promise((ok) => requestAnimationFrame(() => requestAnimationFrame(() => ok({ u: uOf(S.hours),
    thumb: document.querySelector("#rthumb").style.left, now: +document.querySelector("#rthumb").getAttribute("aria-valuenow") }))))`);
  if (Math.abs(atPress - 0.2) > 0.01 || Math.abs(dragged.u - 0.6) > 0.01 || Math.abs(parseFloat(dragged.thumb) - 60) > 1)
    rail.bad.push(`pointer drag: pressed at u ${atPress.toFixed(3)}, released at u ${dragged.u.toFixed(3)}, thumb ${dragged.thumb}`);
  gate(rail.bad.length === 0, `7. time rail (pointer drag included): ${rail.marks} event marks and the two reference marks as the model's events (48 cases), recovers toggle on ${rail.toggles} of them, one duration control, keys, typed durations, event click (thumb, layers, verdict, flash), guide examples ${JSON.stringify(rail.example)} and ${JSON.stringify(rail.example2)}, Play ${!rail.play ? "-" : rail.play.quick ? "started and stopped (--quick: not swept)" : rail.play.ms + " ms"}`);
  rail.bad.slice(0, 8).forEach((x) => console.log("           " + x));

  /* 7b. timeline chart (guide 5b): RiskModel.timeline's points, timelineSummary's lines, one band per answer between
     the events, the rail's duration as a line; a picture, not a control */
  const tlc = await p.ev(`(() => {
    const bad = []; let n = 0;
    const fire = (el, v) => { el.value = v; el.dispatchEvent(new Event("change", { bubbles: true })); };
    document.querySelector('[data-mode="manual"]').click();
    for (const pk of Object.keys(PRE)) {
      fire(document.querySelector("#pos"), pk);
      for (const k of Object.keys(NODES)) for (const f of fails(k)) for (const rec of ${QUICK} ? [false] : [true, false]) {
        setNode(k, f); S.recovers = rec; setHours(30);
        const tag = pk + " " + k + ":" + f + " rec " + rec, T = COPY.tl;
        const rows = RiskModel.timeline(d, pk, k, f, S.sev, rec, S.alt / 100), sum = RiskModel.timelineSummary(d, pk, rows),
          ev = RiskModel.propagationEvents(d, pk, k, f, S.sev, rec, S.alt / 100);
        const pts = document.querySelector("#tl .tline").getAttribute("points").trim().split(/\\s+/);
        if (pts.length !== rows.length) bad.push(tag + ": " + pts.length + " points vs " + rows.length + " rows");
        const top = Math.max(...rows.map((r) => r.loss_if_stay_usd));
        rows.forEach((r, i) => { const [x, y] = pts[i].split(",").map(Number);
          if (Math.abs(x - uOf(r.hours) * 1000) > 0.06 || Math.abs(y - (96 - (top > 0 ? r.loss_if_stay_usd / top * 88 : 0))) > 0.006) bad.push(tag + ": point " + i); });
        const lis = [...document.querySelectorAll("#tl .tlsum li")].map((x) => x.textContent);
        if (sum.duration_matters ? lis.length !== sum.changes.length : lis.join() !== T.flat(sum.why_flat)) bad.push(tag + ": summary '" + lis.join(" / ") + "'");
        const bands = [...document.querySelectorAll("#tl rect.tb")].map((x) => x.getAttribute("class").split(" ")[1]);
        const want = [ev.start.verdict].concat(ev.events.map((e) => e.verdict_after)).map((v) => VCLASS[v]);
        if (bands.join() !== want.join()) bad.push(tag + ": bands " + bands.join() + " vs " + want.join());
        const now = +document.querySelector("#tl .tnow").getAttribute("x1");
        if (Math.abs(now - uOf(S.hours) * 1000) > 1e-6) bad.push(tag + ": duration line at " + now);
        n++;
      }
    }
    if (document.querySelector("#d-tl [role=slider], #d-tl input")) bad.push("the chart holds a control");
    return { n, bad };
  })()`);
  gate(tlc.n > 0 && tlc.bad.length === 0, `7b. timeline chart equals RiskModel.timeline / timelineSummary, bands from the events, duration line: ${tlc.n - tlc.bad.length}/${tlc.n} cases`);
  tlc.bad.slice(0, 5).forEach((x) => console.log("           " + x));

  /* 8. header inputs (guide 3b, to-do 8): position size (default, typed, read-only for real borrowers, the line
     under it), cash yield in the header with the decimal comma, no "Assumptions you can change" section, no static
     "position size" text */
  const p8 = await openPage(b);   /* a fresh page: the default size must not have been typed over */
  const hdr = await p8.ev(`(() => {
    const bad = [], fire = (el, v) => { el.value = v; el.dispatchEvent(new Event("change", { bubbles: true })); };
    const f = document.querySelector("#size"), mark = () => document.querySelector("#size-mark").textContent,
      line = () => document.querySelector("#sizeLine").textContent, hdr = document.querySelector("header");
    const altEl = document.querySelector("#alt");
    if (!hdr.contains(f) || hdr.contains(altEl) || !document.querySelector("#steps").contains(altEl) || altEl.type !== "range")
      bad.push("size in the header, the cash yield a slider in step 2: not so");
    if (document.querySelector("#d-adv, #book") || /Assumptions you can change/.test(document.body.innerText)) bad.push("the assumptions section is still there");
    if (document.querySelector("#stamp")) bad.push("the snapshot stamp is still in the header");
    /* real borrowers: on-chain size, read-only, grade A, with the hint */
    for (const k of Object.keys(PRE).filter((k) => PRE[k].sized === false)) {
      fire(document.querySelector("#pos"), k);
      if (!f.readOnly || f.title !== Math.round(PRE[k].collateral_usd).toLocaleString("en-US") || !/^\\d+(\\.\\d{1,3})?m$/.test(f.value) || !/read on chain/.test(mark()))
        bad.push(k + ": field '" + f.value + "' readOnly " + f.readOnly + " mark '" + mark() + "'");
      if (!line().includes(Math.round(PRE[k].pt_units).toLocaleString("en-US") + " PT")) bad.push(k + ": line '" + line() + "'");
    }
    /* sized presets: the default 10,000,000 is an assumption (D) until typed */
    fire(document.querySelector("#pos"), "spot");
    if (f.readOnly || f.value !== "10m" || f.title !== "10,000,000" || !/assumed/.test(mark()) || S.sizeTyped) bad.push("default: '" + f.value + "' mark '" + mark() + "'");
    /* typed in any form, shown back in k / m units (3,000 = 3k, 3,000,000 = 3m) */
    for (const [typed, want, shown] of [["1,000,000", 1e6, "1m"], ["5M", 5e6, "5m"], ["250k", 2.5e5, "250k"], ["3,000", 3e3, "3k"], ["3.5m", 3.5e6, "3.5m"], ["50 000 000", 5e7, "50m"]]) {
      fire(f, typed);
      if (S.size !== want || d.size_usd !== want || PRE.spot.collateral_usd !== want || PRE.lev_market_avg.collateral_usd !== want || f.value !== shown || mark() !== COPY.size.typed)
        bad.push("typed " + typed + ": size " + S.size + " field '" + f.value + "'");
      const want2 = RiskModel.decideAtDuration(RiskModel.atSize(window.DASHBOARD, want), "spot", S.node, S.fail, S.sev, S.hours, S.recovers, S.alt / 100);
      if (JSON.stringify(model().sev) !== JSON.stringify(want2)) bad.push("typed " + typed + ": card differs from the model at that size");
      if (!line().includes(Math.round(want / d.size_input.pt_price_usd).toLocaleString("en-US") + " PT") || !line().includes(Math.round(d.max_exit_fraction * 100) + "%"))
        bad.push("typed " + typed + ": line '" + line() + "'");
    }
    fire(f, "abc");
    if (S.size !== 5e7 || f.value !== "50m") bad.push("invalid input: size " + S.size + " field '" + f.value + "'");
    /* real borrowers keep their size whatever is typed; back to spot shows the typed size again */
    fire(document.querySelector("#pos"), "lev_closest_to_liquidation");
    const rb = PRE.lev_closest_to_liquidation.collateral_usd;
    fire(document.querySelector("#pos"), "spot");
    if (Math.abs(rb - 3249471.575060609) > 1 || f.value !== "50m" || f.readOnly) bad.push("after a real borrower: '" + f.value + "', borrower " + rb);
    fire(f, "10,000,000");
    /* the cash yield slider: live, shown next to it, and enabled for a past event (steps 1-2's incident is locked) */
    const alt0 = S.alt;
    if (S.mode !== "past" || altEl.disabled) bad.push("the cash yield slider is disabled for a past event");
    altEl.value = "4.5"; altEl.dispatchEvent(new Event("input", { bubbles: true }));
    if (S.alt !== 4.5 || document.querySelector("#altOut").textContent !== "4.50%") bad.push("cash yield slider 4.5 -> " + S.alt);
    fire(altEl, String(alt0));
    /* wallet (guide 3b, to-do 10): the list = wallets read + borrowers of this market; a borrower's address gives
       wallet_morpho = that borrower at its on-chain size (guide 9: collateral 3,249,472, debt 2,941,927), selected,
       read-only, the card equal to the model on atSize(..., wallet); an unread address says to rerun --wallet; a
       non-address says so; clearing removes the presets */
    const W = document.querySelector("#wallet"), msg = document.querySelector("#walletMsg"), D0 = window.DASHBOARD;
    /* the optional wallet field sits behind "+ Wallet" until asked for (plan C) */
    if (!document.querySelector("#walletBox").hidden || document.querySelector("#walletAdd").hidden) bad.push("the wallet field is open before it is asked for");
    document.querySelector("#walletAdd").click();
    if (document.querySelector("#walletBox").hidden || document.activeElement !== W) bad.push("+ Wallet does not open the field");
    const listed = [...document.querySelectorAll("#walletList option")].map((o) => o.value);
    const wantList = (D0.borrowers.wallets || []).map((w) => w.address).concat(D0.borrowers.list.map((x) => x.address));
    if (listed.join() !== wantList.join()) bad.push("wallet list " + listed.length + " vs " + wantList.length);
    const A = "0x5c430FF6f374da12218b380d2040299ae5b6d40e";
    fire(W, A);
    const wm = PRE.wallet_morpho, ref = RiskModel.atSize(D0, S.size, A).position_presets.wallet_morpho;
    if (!wm || S.pos !== "wallet_morpho" || document.querySelector("#pos").value !== "wallet_morpho") bad.push("wallet: preset not selected (" + S.pos + ")");
    else {
      if (Math.round(wm.collateral_usd) !== 3249472 || Math.round(wm.debt_usd) !== 2941927 || JSON.stringify(wm) !== JSON.stringify(ref)) bad.push("wallet_morpho numbers");
      if (!f.readOnly || f.value !== "3.249m" || f.title !== "3,249,472" || msg.hidden || msg.dataset.state !== "found") bad.push("wallet: field '" + f.value + "' message " + msg.dataset.state);
      const want = RiskModel.decideAtDuration(RiskModel.atSize(D0, S.size, A), "wallet_morpho", S.node, S.fail, S.sev, S.hours, S.recovers, S.alt / 100);
      if (JSON.stringify(model().sev) !== JSON.stringify(want)) bad.push("wallet: card differs from the model");
      if (/not your position/.test(document.querySelector("#decision").textContent)) bad.push("wallet: the card calls it someone else's position");
    }
    fire(W, "0x0000000000000000000000000000000000000001");
    if (msg.dataset.state !== "unread" || !/onchain_positions\.py --wallet 0x0+1/.test(msg.textContent) || PRE.wallet_morpho || PRE.wallet || S.pos === "wallet_morpho")
      bad.push("unread wallet: " + msg.dataset.state + " '" + msg.textContent + "' pos " + S.pos);
    fire(W, "abc");
    if (msg.dataset.state !== "bad" || S.wallet !== "") bad.push("not an address: " + msg.dataset.state);
    fire(W, "");
    if (!msg.hidden || PRE.wallet_morpho || S.wallet !== "") bad.push("cleared wallet: message shown or presets left");
    return bad;
  })()`);
  if (p8.errors.length) hdr.push("console errors: " + p8.errors.slice(0, 2).join(" | "));
  /* back to the main page in the foreground: a background tab throttles timers and animation frames */
  await b.send("Target.closeTarget", { targetId: p8.targetId });
  await b.send("Target.activateTarget", { targetId: p.targetId });
  gate(hdr.length === 0, `8. header: size field (default assumed D, typed 1M / 5M / 250k / 50M, invalid restored, read-only on-chain size for real borrowers, PT units line), the cash yield a slider in step 2 (enabled for a past event), no assumptions section; wallet (list, borrower read at its on-chain size and selected, unread / invalid / cleared)${hdr.length ? ": " + hdr.slice(0, 4).join("; ") : ""}`);

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
      && document.querySelector("#v-amt").value === "10m" && VV.last().r.amount < 1e7;
    /* the amount field reads and shows k / m like the PT size field */
    fire(document.querySelector("#v-amt"), "3k");
    out.msgs.units = VV.state.amount === 3e3 && document.querySelector("#v-amt").value === "3k";
    fire(document.querySelector("#v-amt"), "2.5M");
    out.msgs.units = out.msgs.units && VV.state.amount === 2.5e6 && document.querySelector("#v-amt").value === "2.5m";
    /* 6f. both displays from the backend's lists (guide 3): one node per chain item, exactly dependency_edges drawn
       (dashed when grade D), the path = inc.chain_items in Layers and Graph, the hot edges = those with both ends on
       it; the card does not change with the display */
    out.graph = { bad: [], vaults: 0, incidents: 0 };
    for (const e of VAULTS.report.vaults.filter((x) => x.coverage === "full")) {
      VV.set({ addr: e.vault_address, amount: 1e6, display: "list" });
      const v = VAULTS.details[e.vault_address.toLowerCase()];
      for (const i of v.incidents.filter((i) => i.analyzed !== false)) {
        VV.set({ inc: i.key, sev: null, display: "list" });
        const want = new Set(i.chain_items || []), sameSet = (a) => a.length === want.size && a.every((x) => want.has(x));
        const listHot = [...document.querySelectorAll("#v-chain li.on")].map((x) => x.dataset.vid), card = document.querySelector("#v-decision").innerText;
        VV.set({ display: "graph" });
        const E = v.dependency_edges,
          nodes = document.querySelectorAll("#v-graph-box [data-vg]").length,
          items = v.dependency_chain.reduce((n, L) => n + L.items.length, 0),
          lines = document.querySelectorAll("#v-edges > line, #v-edges > path").length,
          dashed = document.querySelectorAll("#v-edges > .doc").length,
          hot = [...document.querySelectorAll("#v-graph-box .node.hot")].map((x) => x.dataset.vg),
          hotE = document.querySelectorAll("#v-edges > .hot").length,
          wantE = E.filter((x) => want.has(x.from) && want.has(x.to)).length;
        const tag = e.vault_name + " " + i.key;
        if (nodes !== items) out.graph.bad.push(tag + ": nodes " + nodes + " vs items " + items);
        if (lines !== E.length || dashed !== E.filter((x) => x.grade === "D").length) out.graph.bad.push(tag + ": edges drawn " + lines + " of " + E.length + ", dashed " + dashed);
        if (!want.size || !sameSet(hot) || !sameSet(listHot)) out.graph.bad.push(tag + ": path Graph " + hot.join() + " / Layers " + listHot.join() + " vs chain_items " + [...want].join());
        if (hotE !== wantE) out.graph.bad.push(tag + ": " + hotE + " hot edges vs " + wantE);
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
    /* 6g. the rest of the vault view (to-do 9): tranches, sensitivity, loss chart, markets, duration and timeline,
       the run's share slider, layer-6 off-chain relations; all against the model with the page's inputs */
    out.g = { bad: [], n: 0, off: 0 };
    const G = out.g, eqJ = (a, b) => JSON.stringify(a) === JSON.stringify(b);
    for (const e of VAULTS.report.vaults.filter((x) => x.coverage === "full").slice(0, ${QUICK} ? 3 : 99)) {
      VV.set({ addr: e.vault_address, amount: 1e6, display: "list" });
      ["v-d-exit", "v-d-sens", "v-d-loss", "v-d-mk", "v-d-tl"].forEach((k) => (VV.state.open[k] = true));
      const v = VAULTS.details[e.vault_address.toLowerCase()], ex = v.exit, amt = Math.min(1e6, v.total_assets);
      for (const inc of v.incidents.filter((i) => i.analyzed !== false && i.type !== "liquidity_run")) {
        for (const [hours, rec] of [[null, false], [168, true]]) {
          VV.set({ inc: inc.key, sev: null, hours: hours === null ? ex.horizon_days * 24 : hours, recovers: rec });
          G.n++;
          const tag = e.vault_name + " " + inc.key + " " + (hours || "default") + "h rec " + rec, L = VV.last(), r = L.r, st = VV.state;
          const want = RiskModel.vaultDecideAt(inc, ex, amt, inc.default_severity, st.alt, null, false, st.hours, st.recovers);
          if (!eqJ(r, want)) G.bad.push(tag + ": card differs from vaultDecideAt with the duration");
          if (hours === null && !eqJ(r, RiskModel.vaultDecideAt(inc, ex, amt, null, null, null))) G.bad.push(tag + ": the default duration differs from the static decision");
          /* tranches */
          const tds = [...document.querySelectorAll("#v-decision table.vtr tbody tr")].map((x) => x.children[1].textContent);
          if (tds.join() !== [r.free_usd, r.forced_usd, r.locked_usd].map(VaultView.money).join()) G.bad.push(tag + ": tranches " + tds.join());
          /* sensitivity, with its basis note off the defaults */
          const sv = RiskModel.vaultSensitivity(inc, ex, amt, r.severity), rows = document.querySelectorAll("#v-d-sens table.sens tbody tr:not(.grp)");
          if (!eqJ(L.sens, sv) || rows.length !== sv.candidates.length) G.bad.push(tag + ": sensitivity");
          if (!!document.querySelector("#v-d-sens p.note") !== (hours !== null)) G.bad.push(tag + ": defaults note");
          /* loss chart and markets */
          const pts = document.querySelector("#v-d-loss polyline:not(.low)").getAttribute("points").trim().split(/\\s+/).length;
          if (pts !== inc.severity_grid.length) G.bad.push(tag + ": loss chart " + pts + " points");
          const mk = [...document.querySelectorAll("#v-more table.vmk tbody tr")];
          if (mk.length !== v.markets.length || mk.filter((x) => x.classList.contains("on")).length !== v.markets.filter((m) => (inc.affected_markets || []).includes(m.key)).length)
            G.bad.push(tag + ": markets table");
          /* duration rail and timeline */
          const tl = RiskModel.vaultTimeline(inc, ex, amt, r.severity, st.recovers, st.alt);
          if (!eqJ(L.timeline.rows, tl) || !eqJ(L.timeline.sum, RiskModel.vaultTimelineSummary(inc, tl))) G.bad.push(tag + ": timeline");
          if (document.querySelector("#v-tl polyline").getAttribute("points").trim().split(/\\s+/).length !== tl.length) G.bad.push(tag + ": timeline chart");
          const both = new Set((inc.duration_grids || []).map((g) => g.recovers)).size === 2;
          if (!!document.querySelector("#v-rec [data-vrec]") !== both) G.bad.push(tag + ": recovers toggle");
          if (document.querySelector("#v-rail").hidden || Math.abs(+document.querySelector("#v-dur").value - Math.log(st.hours) / Math.log(4320) * 1000) > 1) G.bad.push(tag + ": duration rail");
        }
      }
      /* the vault duration can be typed too */
      const ti = v.incidents.find((i) => i.analyzed !== false && i.type !== "liquidity_run");
      if (ti) VV.set({ inc: ti.key });
      const vdi = document.querySelector("#v-durIn");
      if (ti) for (const [typed, want] of [["7d", 168], ["36", 36], ["2w", 336], ["x", 336]]) {
        fire(vdi, typed);
        if (VV.state.hours !== want || !eqJ(VV.last().r, RiskModel.vaultDecideAt(VV.last().inc, ex, amt, VV.last().inc.default_severity, VV.state.alt, null, false, want, VV.state.recovers)))
          G.bad.push(e.vault_name + ": typed duration '" + typed + "' -> " + VV.state.hours);
      }
      VV.set({ hours: ex.horizon_days * 24, recovers: false });
      /* layer-6 off-chain relations: one source link per relation */
      for (const it of v.dependency_chain.flatMap((L) => L.items).filter((x) => x.offchain && v.offchain && v.offchain[x.offchain])) {
        const li = [...document.querySelectorAll("#v-chain li")].find((x) => x.dataset.vid === it.id), o = v.offchain[it.offchain];
        const links = li ? li.querySelectorAll("details.offc a.osrc").length : 0;
        if (links !== o.relations.filter((r) => r.evidence && r.evidence.url).length) G.bad.push(e.vault_name + " " + it.offchain + ": " + links + " source links of " + o.relations.length);
        G.off++;
      }
      /* the run's share slider: the model at that share, the drag keeps its element */
      const run = v.incidents.find((i) => i.type === "liquidity_run");
      if (run) {
        VV.set({ inc: run.key });
        const sl = document.querySelector("#v-share");
        sl.value = "30"; sl.dispatchEvent(new Event("input", { bubbles: true }));
        const worst = v.incidents.find((i) => i.key === v.worst_incident);
        const Lw = worst ? RiskModel.vaultDecideAt(worst, ex, amt, null, VV.state.alt, null, false, VV.state.hours, VV.state.recovers).L : 0;
        if (!eqJ(VV.last().runAt, RiskModel.vaultRun(ex, amt, 0.3, Lw)) || document.querySelector("#v-share") !== sl) G.bad.push(e.vault_name + ": run slider");
        VV.state.share = 0.5;
      }
    }
    /* back to the PT view: same state and text as before */
    document.querySelector('[data-page="pt"]').click();
    out.ptSame = snap() === before && !document.querySelector("#view-pt").hidden && document.querySelector("#view-vault").hidden;
    document.querySelector('[data-mode="manual"]').click();
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
  gate(vault.msgs.notCovered && vault.msgs.notFound && vault.msgs.above && vault.msgs.units,
    `6e. vault messages: not analysed ${vault.msgs.notCovered}, unknown address ${vault.msgs.notFound}, amount above the vault ${vault.msgs.above}, k / m units ${vault.msgs.units}`);
  gate(vault.graph && vault.graph.bad.length === 0 && vault.graph.incidents > 0,
    `6f. vault graph: ${vault.graph ? vault.graph.vaults : 0} vaults, ${vault.graph ? vault.graph.incidents : 0} incidents: one node per item, exactly dependency_edges drawn (D dashed), the path = chain_items in both displays, same card`);
  if (vault.graph) vault.graph.bad.slice(0, 5).forEach((x) => console.log("           " + x));
  gate(vault.g && vault.g.n > 0 && vault.g.bad.length === 0,
    `6g. vault details: ${vault.g ? vault.g.n : 0} incident x duration cases (card = vaultDecideAt with the duration; default = static decision; tranches, sensitivity and its note, loss chart, markets, timeline, recovers toggle, rail, typed durations), ${vault.g ? vault.g.off : 0} off-chain items, run slider`);
  if (vault.g) vault.g.bad.slice(0, 6).forEach((x) => console.log("           " + x));
  gate(vault.ptSame, "6a. switching back restores the PT view exactly (state, text, controls)");
  vault.bad.forEach((x) => console.log("           " + x));

  /* no evidence grades on the page (user decision, 11 Oct): no badge, no Grade column or row, no "(grade X)" */
  const grades = await p.ev(`(() => {
    const hits = [];
    const look = () => { if (document.querySelector(".gr")) hits.push("badge"); const t = document.body.innerText;
      if (/\\(grade [A-D]\\)|\\bGrade\\b|evidence grade/.test(t)) hits.push((t.match(/[^\\n]{0,40}(\\(grade [A-D]\\)|\\bGrade\\b|evidence grade)[^\\n]{0,20}/) || [""])[0]); };
    document.querySelector('[data-page="pt"]').click();
    ["d-flip"].forEach((k) => { const x = document.getElementById(k); if (x) x.open = true; });
    look();
    for (const k of Object.keys(NODES)) { nodeEvidence(k); look(); }
    closeDrawer();
    document.querySelector('[data-page="vault"]').click();
    VaultView.state.open["v-d-sens"] = true; VaultView.set({});
    look();
    document.querySelector('[data-page="pt"]').click();
    return [...new Set(hits)].slice(0, 4);
  })()`);
  gate(grades.length === 0, `9. no evidence grade on the page (badges, columns, drawer rows, "(grade X)")${grades.length ? ": " + grades.join(" / ") : ""}`);

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
console.log((failures ? `\n${failures} check(s) failed` : "\nAll checks passed") + (QUICK ? " (--quick: sampled; run without it before a commit)" : ""));
process.exit(failures ? 1 : 0);
