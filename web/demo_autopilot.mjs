#!/usr/bin/env node
/* Autopilot for the demo: drives web/demo.html in a visible Chrome through the scenes of DEMO_SCRIPT.md while the
   presenter speaks. Nothing in the page is changed: it clicks, types and drags like a user.

   Setup once, from the repo root (package only, about 10 s; it drives the installed Google Chrome, no download):
       npm i --no-save playwright
   Run (from the repo root or from web/):
       node web/demo_autopilot.mjs [--auto 12] [--captions] [--from 3] [--headless --shots DIR]
   Advance: press → (or Space, Enter) in the browser window, outside a text field; ← repeats the current cue in the
   terminal; Esc or closing the window quits. --auto N advances by itself every N seconds (rehearsal with a timer).
   --captions shows the step's cue in a small bar at the bottom of the page (rehearsal; leave it off for the judges).
   --from N runs steps 0..N-1 at once, without waiting, then waits at step N.
   --headless --shots DIR: no window, a screenshot per step in DIR (used to check the script here; CHROME=/path
   overrides the browser). Node 18+. */

import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { mkdirSync } from "node:fs";

const HERE = dirname(fileURLToPath(import.meta.url));
const ARGS = process.argv.slice(2);
const flag = (n) => ARGS.includes(n);
const opt = (n, d) => (ARGS.includes(n) ? ARGS[ARGS.indexOf(n) + 1] : d);
const AUTO = +opt("--auto", 0) * 1000;
const CAPTIONS = flag("--captions");
const FROM = +opt("--from", 0);
const HEADLESS = flag("--headless");
const SHOTS = opt("--shots", null);
const PAGE = pathToFileURL(resolve(opt("--page", join(HERE, "demo.html")))).href;

let chromium;
try {
  ({ chromium } = await import("playwright"));
} catch {
  console.error("playwright is not installed. From the repo root: npm i --no-save playwright");
  process.exit(2);
}
const launch = { headless: HEADLESS, args: ["--window-size=1440,1000", "--no-first-run"] };
if (process.env.CHROME) launch.executablePath = process.env.CHROME;
else launch.channel = "chrome";
if (process.env.CI || process.getuid?.() === 0) launch.args.push("--no-sandbox");
const browser = await chromium.launch(launch);
const page = await browser.newPage({ viewport: HEADLESS ? { width: 1440, height: 1000 } : null });
page.on("pageerror", (e) => console.error("page error:", String(e)));
if (SHOTS) mkdirSync(SHOTS, { recursive: true });

/* ---- helpers: every action is what a user would do on the page */
const wait = (ms) => page.waitForTimeout(ms);
const typeIn = async (sel, text) => {
  await page.fill(sel, text);
  await page.press(sel, "Enter");
  await wait(150);
};
const clickText = (text, nth = 0) => page.getByText(text, { exact: true }).nth(nth).click();
const modeButton = (group, label) => page.locator(`[aria-label="${group}"] button`, { hasText: label }).click();
const recToggle = (label) => page.locator("#rec button, #rec [role=button], #rec label", { hasText: label }).first().click();
/* Set a range input to the value whose output text starts with `target` (binary search on the slider's own scale,
   then an animated glide from the current value so the audience sees it move). */
async function slideTo(sel, outSel, target, ms = 900) {
  const v = await page.evaluate(
    ([sel, outSel, target]) => {
      const s = document.querySelector(sel),
        out = document.querySelector(outSel),
        fire = (x) => {
          s.value = x;
          s.dispatchEvent(new Event("input", { bubbles: true }));
        },
        read = () => parseFloat(out.textContent.replace(/[^0-9.]/g, "")),
        start = +s.value;
      let lo = +s.min,
        hi = +s.max,
        step = +s.step || 1;
      for (let i = 0; i < 40 && hi - lo > step; i++) {
        const mid = lo + Math.round((hi - lo) / 2 / step) * step;
        fire(mid);
        if (read() < target) lo = mid;
        else hi = mid;
      }
      fire(hi);
      const end = Math.abs(read() - target) <= Math.abs((fire(lo), read()) - target) ? hi : lo;
      fire(start);
      return { start, end, step };
    },
    [sel, outSel, target],
  );
  await glide(sel, v.start, v.end, ms);
}
async function glide(sel, from, to, ms = 900) {
  const frames = Math.max(8, Math.round(ms / 16));
  for (let i = 1; i <= frames; i++) {
    const x = from + ((to - from) * i) / frames;
    await page.evaluate(
      ([sel, x]) => {
        const s = document.querySelector(sel);
        s.value = x;
        s.dispatchEvent(new Event("input", { bubbles: true }));
      },
      [sel, x],
    );
    await wait(16);
  }
}
const openFold = async (text, nth = 0) => {
  const el = page.getByText(text, { exact: false }).nth(nth);
  await el.scrollIntoViewIfNeeded();
  const open = await el.evaluate((e) => e.closest("details")?.open);
  if (!open) await el.click();
  await wait(200);
};
const top = () => page.evaluate(() => window.scrollTo({ top: 0, behavior: "smooth" }));
async function playRail() {
  await page.click("#play");
  await page.waitForFunction(() => document.querySelector("#play").getAttribute("aria-pressed") === "true", null, { timeout: 5000 }).catch(() => {});
  await page.waitForFunction(() => document.querySelector("#play").getAttribute("aria-pressed") !== "true", null, { timeout: 40000 }).catch(() => {});
}
let vSevStart = null;

/* ---- the steps: cue = what the presenter says (short form of DEMO_SCRIPT.md), run = what the page does */
const STEPS = [
  {
    cue: "Scene 0 · First screen. Every number is read on chain or from a live quote. A real borrower 0.99% from liquidation, the PT-reUSD oracle pattern (back-tested 9/9): doing nothing loses $165k, selling costs $5.7k. EXIT.",
    run: async () => {},
  },
  {
    cue: "Scene 1 · A 3% USDe depeg, like the daily low of 1 Feb. Six hours in: layer 2 origin, layer 4 affected, layer 3 unchanged (the meta-oracle switches only after 0.75% for 16 h), layer 5 unchanged. STAY: visible everywhere, not yet in this book.",
    run: async () => {
      await modeButton("How to set the incident", "Manual");
      await page.click("#incBtn");
      await wait(500);
      const usde = page.locator("#incMenu").getByText("USDe", { exact: true }).first();
      await usde.hover();
      await wait(600);
      await usde.click();
      const loses = page.locator("#incMenu").getByText("Loses value", { exact: true }).first();
      if (await loses.count()) await loses.click();
      await wait(300);
      await slideTo("#sev", "#sevOut", 3);
      await recToggle("Recovers");
      await typeIn("#durIn", "6");
    },
  },
  {
    cue: "Press Play: the rail sweeps 1 h to 180 days. At hour 16 layers 3 and 5 flash: the oracle's challenge timelock (57,600 s, read from MetaOracleDeviationTimelock) expires, it switches to the USDe/USD backup, Morpho liquidates. EXIT: $172,215 against $5,743.",
    run: async () => {
      await playRail();
      await typeIn("#durIn", "16");
    },
  },
  {
    cue: "Graph display: USDe → sUSDe → PT → Morpho market → position, along the crawled edges. 'How it spreads, step by step': the same path with its evidence grades.",
    run: async () => {
      await page.locator('#view-pt [aria-label="Graph"]').click();
      await wait(800);
      await openFold("How it spreads, step by step");
    },
  },
  {
    cue: "Layer 3's evidence: MetaOracleDeviationTimelock, threshold 0.75%, timelock 16 h, primary = linear discount (no market input), backup = Chainlink USDe/USD. Discovery is ABI-driven: 82 contracts, 96 links, 35 quoted off-chain relations for Ethena.",
    run: async () => {
      await page.locator('#view-pt [aria-label="Layers"]').click();
      await top();
      await wait(400);
      await page.getByText("Show 2 dependencies and evidence").nth(0).click();
    },
  },
  {
    cue: "'Stays': if USDe does not come back, it is EXIT at any duration, $97k at 6 h. Whether it recovers is decided off-chain, so it is your assumption; we show both.",
    run: async () => {
      const hide = page.getByText("Hide 2 dependencies and evidence");
      if (await hide.count()) await hide.first().click();
      else await page.mouse.click(5, 5);
      await typeIn("#durIn", "6");
      await recToggle("Stays");
    },
  },
  {
    cue: "'What would change the answer': the weakest assumption is the duration (8 h, under the 16 h timelock: STAY). The timeline: STAY band to 16 h, EXIT after. You have until the timelock, not a minute longer.",
    run: async () => {
      await recToggle("Recovers");
      await typeIn("#durIn", "16");
      await openFold("What would change the answer");
      await openFold("Loss if staying, by how long the incident lasts");
    },
  },
  {
    cue: "Scene 2 · Same incident, PT held outright at $10M, recovers: STAY at every duration. Layer 3 still switches at 16 h, but there is nothing to liquidate.",
    run: async () => {
      await top();
      await page.selectOption("#pos", { label: "PT held outright" });
      await wait(300);
    },
  },
  {
    cue: "'Stays': SELL $4.5M, the pool limit. Staying loses $300k, acting $187k. Pendle takes at most $4.5M today; the chart is the cost of acting at every share sold. Same incident, three holders, three answers.",
    run: async () => {
      await recToggle("Stays");
      await openFold("Cost of selling, by share sold");
      await glide("#alt", 5.01, 1, 700);
      await wait(400);
      await glide("#alt", 1, 5.01, 700);
    },
  },
  {
    cue: "Scene 3 · Belem RWA EURCV, a deposit the size of the vault. mGLOeuro issuer default at 84.14%: EXIT 1.03M, staying loses about 2.9M EUR, exiting costs 492 EUR, about 3.67M cannot be withdrawn: lent against the token that just failed.",
    run: async () => {
      await modeButton("Page view", "Vaults");
      await wait(500);
      await typeIn("#v-amt", "4.7m");
      vSevStart = await page.evaluate(() => +document.querySelector("#v-sev").value);
    },
  },
  {
    cue: "At 1M the whole deposit leaves: 362k free, the rest through forceDeallocate, nothing locked; 477 EUR against a 616k loss. A small depositor gets out, a large one is stuck: the amount is part of the answer.",
    run: async () => typeIn("#v-amt", "1m"),
  },
  {
    cue: "Back to the vault's size, severity down: below 20.09% the badge turns STAY. That break-even is the desk's number: leave once you believe mGLOeuro loses more than a fifth.",
    run: async () => {
      await typeIn("#v-amt", "4.7m");
      await slideTo("#v-sev", "#v-sevOut", 15, 1400);
    },
  },
  {
    cue: "Graph: chain → vault → Morpho Blue → six markets → collateral and oracles → issuers; the mGLOeuro path lit, 12 links from the backend, dashed = assumption.",
    run: async () => {
      if (vSevStart != null) await glide("#v-sev", await page.evaluate(() => +document.querySelector("#v-sev").value), vSevStart, 900);
      await page.locator('#view-vault [aria-label="Graph"]').click();
      await wait(500);
      await page.locator("#v-chain").scrollIntoViewIfNeeded();
    },
  },
  {
    cue: "Layer 6, mGLOeuro's documents: 17 relations with sources; the NAV feed is 'submitted manually by feed admins', monthly. The hidden dependency is not a contract. 'Exit, tranche by tranche': free, forced (penalty read on chain), locked; a run leaves 7.68% without penalty.",
    run: async () => {
      await page.locator('#view-vault [aria-label="Layers"]').click();
      await wait(400);
      await openFold("Exit, tranche by tranche");
      const off = page.locator("#view-vault").getByText("Off-chain (issuer documents)", { exact: false });
      const n = await off.count();
      if (n) await openFold("Off-chain (issuer documents)", n - 1);
    },
  },
  {
    cue: "Close · 33 vaults in, 12 with full numbers; break-evens Tori 7.9%, YIELD 10.1%, Huma 11.8%, Belem 20.1%, NUVA 21.4%. One pipeline, 28 model gates, 50 browser gates, no probabilities, no invented incidents. How much to leave, when, and why.",
    run: async () => {
      await top();
    },
  },
];

/* ---- advancing: a key in the page, or a timer */
await page.goto(PAGE);
await wait(1200);
await page.evaluate(() => {
  window.__adv = null;
  addEventListener("keydown", (e) => {
    const t = e.target,
      typing = t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable);
    if (typing && e.key !== "Escape") return;
    if (e.key === "ArrowRight" || e.key === " " || e.key === "Enter") (window.__adv = "next"), e.preventDefault();
    else if (e.key === "ArrowLeft") (window.__adv = "back"), e.preventDefault();
    else if (e.key === "Escape") window.__adv = "quit";
  });
});
async function caption(i) {
  if (!CAPTIONS) return;
  await page.evaluate(
    ([i, n, text]) => {
      let el = document.getElementById("__cue");
      if (!el) {
        el = document.createElement("div");
        el.id = "__cue";
        el.style.cssText =
          "position:fixed;left:0;right:0;bottom:0;z-index:99999;padding:8px 16px;font:13px/1.4 system-ui,sans-serif;" +
          "background:rgba(20,24,32,.92);color:#fff;border-top:1px solid #555";
        document.body.appendChild(el);
      }
      el.textContent = `${i + 1}/${n} · ${text}`;
    },
    [i, STEPS.length, STEPS[i].cue],
  );
}
async function next(i) {
  const deadline = AUTO ? Date.now() + AUTO : Infinity;
  for (;;) {
    if (page.isClosed()) return "quit";
    const a = await page.evaluate(() => {
      const a = window.__adv;
      window.__adv = null;
      return a;
    }).catch(() => "quit");
    if (a) return a;
    if (Date.now() > deadline) return "next";
    await wait(100);
  }
}

console.log(`${STEPS.length} steps. In the browser: → next, ← repeat the cue, Esc quit.${AUTO ? ` Auto-advance every ${AUTO / 1000} s.` : ""}\n`);
let i = 0;
for (; i < STEPS.length; i++) {
  console.log(`\n[${i + 1}/${STEPS.length}] ${STEPS[i].cue}`);
  try {
    await STEPS[i].run();
  } catch (e) {
    console.error(`  step ${i + 1} failed: ${String(e).split("\n")[0]}`);
  }
  await caption(i);
  if (SHOTS) {
    await wait(500);
    await page.screenshot({ path: join(SHOTS, `${String(i + 1).padStart(2, "0")}.png`) });
  }
  if (i < FROM) continue;
  if (i === STEPS.length - 1 && HEADLESS) break;
  let a = await next(i);
  while (a === "back") {
    console.log(`\n[${i + 1}/${STEPS.length}] ${STEPS[i].cue}`);
    a = await next(i);
  }
  if (a === "quit") break;
}
console.log("\nDone.");
await browser.close().catch(() => {});
