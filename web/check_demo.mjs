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

  /* 3. every preset x every failure of every node, through the page's own controls */
  const sweep = await p.ev(`(() => {
    const bad = []; let n = 0;
    const fire = (el, v) => { el.value = v; el.dispatchEvent(new Event("change", { bubbles: true })); };
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
  const other = rows.length - atPage.length;
  if (other) console.log(`SKIPPED    4. ${other} acceptance rows at other sizes: the page has no position-size input yet`);

  gate(p.errors.length === 0, `1. no console errors during checks 1-4${p.errors.length ? ": " + p.errors.slice(0, 3).join(" | ") : ""}`);

  /* phone width and dark mode */
  const phone = await openPage(b, { width: 390 });
  const ph = await phone.ev(`({ sw: document.documentElement.scrollWidth, w: innerWidth })`);
  gate(ph.sw <= ph.w + 1 && phone.errors.length === 0, `5. phone width 390px: no horizontal page scroll (scrollWidth ${ph.sw}), no errors`);
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
