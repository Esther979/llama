      const $ = (s) => document.querySelector(s);
      const money = (v) => {
        const a = Math.abs(v);
        return a >= 999500
          ? "$" + (v / 1e6).toFixed(2) + "M"
          : a >= 1e4
            ? "$" + Math.round(v / 1e3) + "k"
            : a >= 1e3
              ? "$" + (v / 1e3).toFixed(1) + "k"
              : "$" + Math.round(v);
      };
      const pc = (v, d = 1) => (v * 100).toFixed(d) + "%";
      const short = (a) =>
        a.length > 14 ? a.slice(0, 6) + "…" + a.slice(-4) : a;
      const trim = (x) => String(+(+x).toFixed(2));
      const cap1 = (t) => t.charAt(0).toUpperCase() + t.slice(1);
      /* Lower-case the first letter of a label, except acronyms ("NAV falls"). */
      const lc = (t) =>
        /^[A-Z][a-z]/.test(t) ? t.charAt(0).toLowerCase() + t.slice(1) : t;

      /* Data and model come from the backend (FRONTEND_GUIDE.md): dashboard.sample.js sets window.DASHBOARD,
   risk_model.js sets window.RiskModel. The page holds no snapshot numbers and no loss formulas. */
      const d = window.DASHBOARD,
        RM = window.RiskModel;
      if (!d || !RM) {
        $("#banner").hidden = false;
        $("#banner").innerHTML =
          "<b>Could not load the backend files.</b> This page needs ../sample_data/dashboard.sample.js and risk_model.js next to it.";
        throw new Error("backend files missing");
      }
      const N = d.position.notional_usd,
        LD = d.lending[0];
      /* Exit curve and largest sellable share of the selected position (guide section 0b): every position has its
   own curve, RiskModel.sizeCurve(d, collateral). d.exit_curve / d.max_exit_fraction describe only the size
   input's position. Set for the selected preset by useCurve() at each render. */
      let [CURVE, MAXX] = RM.sizeCurve(d, N);
      const NODES = d.ui.nodes,
        LAY = d.ui.layers,
        PRE = d.position_presets,
        FT = d.failure_types.types,
        GN = d.dependency_graph.nodes,
        ORC = d.oracle;
      const utc = (o) =>
        new Date(d.generated_at).toLocaleString(
          "en-GB",
          Object.assign({ timeZone: "UTC" }, o),
        );
      const STAMP =
        utc({ hour: "2-digit", minute: "2-digit" }) +
        " UTC, " +
        utc({ day: "numeric", month: "short", year: "numeric" });
      const DAY = utc({ day: "numeric", month: "short" });
      const EXPIRY = new Date(d.position.expiry + "T00:00:00Z").toLocaleString(
        "en-GB",
        { timeZone: "UTC", day: "numeric", month: "short", year: "numeric" },
      );
      const DAYS = Math.round(
        (Date.parse(d.position.expiry) -
          Date.parse(d.generated_at.slice(0, 10))) /
          864e5,
      );
      const TL =
        ORC && ORC.challenge_timelock_s != null
          ? trim(ORC.challenge_timelock_s / 3600)
          : null;
      const gr = (g) =>
        g
          ? `<span class="gr ${g}" title="${d.evidence.grades[g] || ""}">${g}</span>`
          : "";
      const src = (e) => (e ? `${gr(e.grade)} ${e.source}` : "");
      /* The page's own table, kept as the guide asks: label, unit, range and starting value. No loss functions and
   no probabilities here: the decision assumes the incident has happened (guide, rule 5). */
      const FAIL = {
        shortfall: {
          label: "Issuer cannot back the asset",
          sev: "Reserves missing",
          unit: "%",
          min: 1,
          max: 100,
          def: 50,
          phrase: (s) => `a ${s} reserve shortfall`,
        },
        depeg: {
          label: "Loses value",
          sev: "Value drop",
          unit: "%",
          min: 1,
          max: 60,
          def: 10,
          phrase: (s) => `a ${s} fall in value`,
        },
        oracleLow: {
          label: "Reports a price that is too low",
          sev: "Price understated by",
          unit: "%",
          min: 1,
          max: 40,
          def: 15,
          phrase: (s) => `a price understated by ${s}`,
        },
        stale: {
          label: "Stops updating",
          sev: "Hours without an update",
          unit: "h",
          min: 1,
          max: 48,
          def: 6,
          phrase: (s) => `${s} without a price update`,
        },
        cascade: {
          label: "Other borrowers are liquidated into the pool",
          sev: "Oracle drop that liquidates them",
          unit: "%",
          min: 1,
          max: 40,
          def: 8,
          phrase: (s) => `a ${s} oracle drop that liquidates other borrowers`,
        },
        drain: {
          label: "Liquidity leaves the pool",
          sev: "Liquidity removed",
          unit: "%",
          min: 10,
          max: 90,
          def: 50,
          phrase: (s) => `${s} of liquidity leaving`,
        },
        halt: {
          label: "Chain halts",
          sev: "Hours halted",
          unit: "h",
          min: 1,
          max: 48,
          def: 6,
          phrase: (s) => `a ${s} halt`,
        },
      };
      /* Failure keys this table does not know are read from the backend (failure_types.types), so a new failure type
   shows up as one more option instead of breaking the page. */
      Object.keys(FT).forEach((k) => {
        if (FAIL[k]) return;
        const t = FT[k],
          lab = t.label || k;
        FAIL[k] = {
          label: lab,
          sev: t.unit === "h" ? "Hours" : lab,
          unit: t.unit || "%",
          min: t.min ?? 1,
          max: t.max ?? 100,
          def: t.default_severity ?? t.min ?? 1,
          phrase: (s) => `${lc(lab)} (${s})`,
        };
      });
      /* Display names follow the backend, so a rename there shows up here without a page change. */
      Object.keys(FAIL).forEach((k) => {
        if (FT[k] && FT[k].label) FAIL[k].label = FT[k].label;
      });
      /* A node's usable failures: known to the table above and with an injection rule in the data. */
      const fails = (k) =>
        ((NODES[k] || {}).failures || []).filter(
          (f) => FAIL[f] && d.ui.injections[k + ":" + f],
        );
      const BW = d.borrowers || {};
      const LFACT = {
        1: { head: NODES.eth.label, fact: "Every contract below settles here" },
        2: {
          head: "sUSDe, backed by USDe and Ethena",
          fact: "The PT redeems to sUSDe at expiry",
        },
        3: {
          head: NODES.oracle.contract_name || NODES.oracle.label,
          fact: NODES.oracle.note || "",
        },
        4: {
          head: NODES.market.label,
          get fact() {
            const C = PRE[S.pos].collateral_usd;
            return `You can sell ${money(MAXX * C)} of ${money(C)} today`;
          },
        },
        5: {
          head: NODES.lending.label,
          fact: BW.distribution
            ? `${BW.distribution.n_borrowers} borrowers; Morpho liquidations would exceed the pool from a ${pc(BW.first_drop_seized_exceeds_capacity)} oracle drop`
            : "",
        },
      };
      /* Edges come from the data only, including the two to the position (pt -> holding, lending -> liquidation for
   the presets in applies_to). The data names the position "position"; the page draws it as "pos". */
      const EDGES = d.ui.edges.map((e) =>
        e.to === "position" ? Object.assign({}, e, { to: "pos" }) : e,
      );

      /* Past incidents (guide section 3c): real events as ready-made inputs, each with the opts the model needs
   (duration, recovery). There is no detector and no invented incident. S.past = the selected key, null for a
   what-if test; moving the dependency, failure or severity drops it, changing the position keeps it. */
      const PAST = d.past_incidents || [];
      const pastOf = () => PAST.find((x) => x.key === S.past) || null;
      const pastOpts = () => (pastOf() ? pastOf().opts : null);
      /* First screen (guide 3c, user decision): the PT-reUSD oracle drop on the real borrower closest to
   liquidation, so the decision card shows a liquidation and an exit. */
      const FIRST = PAST.find((x) => x.key === "pt_reusd_aug_2026") || PAST[0] || null;
      /* Real-borrower presets have a fixed on-chain size (sized: false): someone else's position. */
      const isReal = (k) => !!PRE[k] && PRE[k].sized === false;
      let CUR = { type: "none" };
      const S = {
        view: "list",
        past: FIRST ? FIRST.key : null,
        pos: PRE.lev_closest_to_liquidation
          ? "lev_closest_to_liquidation"
          : Object.keys(PRE)[0],
        node: FIRST ? FIRST.node : "susde",
        fail: FIRST ? FIRST.fail : "depeg",
        sev: FIRST ? FIRST.sev : 10,
        alt: d.position.implied_apy * 100,
        book: 10,
        open: {},
        more: {},
      };
      const isPct = () => FAIL[S.fail].unit === "%";
      const sevText = (v = S.sev) =>
        (v < 0.1 ? String(+(+v).toFixed(3)) : trim(v)) + (isPct() ? "%" : " h");
      /* Wide % ranges (max at least 20x min, e.g. 0.5-100%) use a log scale on the slider and on the zone bar, so
   small severities such as a 2% break-even get room. Positions run 0..LOGR. */
      const LOGR = 1000;
      const isLog = (f) => f.unit === "%" && f.max / f.min >= 20;
      const sevPos = (f, v) =>
        (Math.log(v / f.min) / Math.log(f.max / f.min)) * LOGR;
      const posSev = (f, p) => {
        const v = f.min * Math.pow(f.max / f.min, p / LOGR),
          k = v < 10 ? 100 : 10;
        return Math.min(f.max, Math.max(f.min, Math.round(v * k) / k));
      };
      /* Yield given up until expiry per unit sold, from the annual "cash earns" input (guide section 4). Unscaled:
   the model scales it per unit of equity for levered presets. */
      const carry = () => RM.carryOf(d, S.alt / 100);
      const isLev = () => PRE[S.pos].debt_usd > 0;
      const edgeOn = (e) => !e.applies_to || e.applies_to.includes(S.pos);

      /* The decision given the incident at the chosen severity, no probability (guide, section 4):
   RiskModel.decideAt for the verdict, RiskModel.breakEvenSeverity for the severity zones on step 2. */
      function model(posKey = S.pos, light = false) {
        const P = PRE[posKey],
          C = P.collateral_usd,
          equity = C - P.debt_usd,
          f = FAIL[S.fail],
          cy = carry();
        const o = pastOpts(),
          r = RM.decideAt(d, posKey, S.node, S.fail, S.sev, cy, o),
          x = r.sell_fraction;
        const m = {
          P,
          C,
          equity,
          f,
          sev: r,
          L: r.L_high,
          cy,
          x,
          slip: x ? RM.slippageAt(x, RM.sizeCurve(d, C)[0]) : 0,
          hasLoss: r.L_high > 0,
          verdict: r.verdict,
        };
        if (light) return m;
        m.be = RM.breakEvenSeverity(d, posKey, S.node, S.fail, cy, f.min, f.max, 400, o);
        /* be is floored at the slider's minimum; below it, search [0, min] for the real values to print. */
        const low =
          m.be.start !== null && m.be.start <= f.min + 1e-9
            ? RM.breakEvenSeverity(d, posKey, S.node, S.fail, cy, 0, f.min, 400, o)
            : null;
        m.start = low && low.start !== null ? low.start : m.be.start;
        m.cap =
          low && m.be.cap !== null && m.be.cap <= f.min + 1e-9 && low.cap !== null
            ? low.cap
            : m.be.cap;
        m.others = Object.keys(PRE)
          .filter((k) => k !== posKey)
          .map((k) => ({ k, m: model(k, true) }));
        return m;
      }
      const VCLASS = {
        STAY: "stay",
        REDUCE: "reduce",
        SELL_TO_CAP: "cap",
        EXIT: "cap",
      };
      const word = (m) =>
        m.verdict === "STAY"
          ? "Stay"
          : m.verdict === "EXIT"
            ? "Exit"
            : `${m.verdict === "SELL_TO_CAP" ? "Sell to the pool limit" : "Reduce"}, sell ${money(m.sev.sell_usd)}`;

      /* What the incident does at each step of the path, read from the inject result (guide, section 6). */
      function story(m) {
        const s = m.sev,
          f = S.fail,
          sv = sevText(),
          C = m.C,
          lev = m.P.debt_usd > 0,
          nlab = NODES[S.node].label;
        const origin =
          {
            depeg: `${nlab} down ${sv}`,
            shortfall: `Reserves short by ${sv}`,
            oracleLow: `Price understated by ${sv}`,
            stale: `No update for ${sv}`,
            drain: `${sv} of liquidity gone`,
            cascade: `Other borrowers liquidated at a ${sv} oracle drop`,
            halt: `Halted for ${sv}`,
          }[f] || `${FAIL[f].label}: ${sv}`;
        const orc =
          s.oracle_falls === true
            ? f === "oracleLow"
              ? "Oracle reports the low price"
              : `Oracle follows${TL ? ` (after the ${TL} h switch)` : ""}`
            : s.oracle_falls === false
              ? "Oracle does not move (linear discount, no market input)"
              : s.type === "loss_model"
                ? "Oracle behaviour unknown: both cases counted"
                : null;
        const shrinks = s.sellable_later < s.sellable_now - 1e-9;
        const exit = shrinks
          ? `Sellable falls from ${money(s.sellable_now * C)} to ${money(s.sellable_later * C)}`
          : null;
        const L = s.liquidated || [];
        const liq = L.includes(true)
          ? L.includes(false)
            ? "Liquidated if the oracle follows"
            : "Your position is liquidated"
          : lev && L.length
            ? "Not liquidated"
            : null;
        const pos =
          s.loss_usd > 0
            ? `Lose ${money(s.loss_usd)}`
            : s.type === "not_modelled"
              ? f === "halt"
                ? "No exit while halted"
                : "No direct loss modelled"
              : shrinks
                ? "No direct loss, but the exit shrinks"
                : "No direct loss";
        return {
          origin,
          orc,
          exit,
          liq,
          pos,
          shrinks,
          forced: shrinks && s.type !== "exit_only",
          follows: s.oracle_falls === true && S.node !== "oracle",
        };
      }

      /* Layer list: one row per layer. */
      function effects(m) {
        const st = story(m),
          fl = flow(st),
          o = {},
          note = {},
          lay = NODES[S.node].layer;
        LAY.forEach((L) => {
          if (L.nodes.some((k) => fl.nodes.has(k))) o[L.n] = "";
        }); /* layers the incident reaches */
        o[lay] = st.origin;
        if (S.fail !== "halt") {
          if (st.orc && lay !== 3) {
            if (m.sev.oracle_falls === false) note[3] = st.orc;
            else o[3] = st.orc;
          }
          if (st.exit && lay !== 4) o[4] = st.exit;
          if (st.liq && lay !== 5) {
            if (st.liq === "Not liquidated") note[5] = st.liq;
            else o[5] = st.liq;
          }
        }
        o[6] = lay === 4 && st.exit && !(m.sev.loss_usd > 0) ? st.exit : st.pos;
        return { o, note };
      }
      function renderList(m, idle) {
        const efr = idle ? { o: {}, note: {} } : effects(m),
          ef = efr.o,
          org = idle ? 0 : NODES[S.node].layer,
          P = m.P;
        let h = LAY.map((L) => {
          const ids = L.nodes,
            hot = ef[L.n] !== undefined,
            open = !!S.more[L.n],
            lf = LFACT[L.n];
          const past = org === L.n && !!S.past,
            hyp = org === L.n && !S.past;
          const tags =
            (past ? `<span class="tag det">${COPY.past.tag}</span>` : "") +
            (hyp ? '<span class="tag hyp">What-if</span>' : "");
          const fact = lf.fact;
          return `<div class="lay ${hot ? "hot" : ""} ${org === L.n ? "origin" : ""} ${hyp ? "hyp" : ""}"><span class="ln">${L.n}</span>
      <button class="lrow" data-layer="${L.n}" aria-label="Test an incident at layer ${L.n}, ${L.name}">
        <span class="lt"><span class="lbl">${L.name}</span><b>${lf.head}${tags}</b><span class="fact">${fact}</span></span>
        ${hot && ef[L.n] ? `<span class="eff">${ef[L.n]}</span>` : efr.note[L.n] ? `<span class="eff n">${efr.note[L.n]}</span>` : ""}</button>
      <button class="more" data-more="${L.n}" aria-expanded="${open}">${open ? "Hide" : "Show"} ${ids.length} ${ids.length > 1 ? "dependencies" : "dependency"} and evidence</button>
      ${
        open
          ? `<div class="chips">${ids
              .map((id) => {
                const n = NODES[id],
                  g = n.evidence && n.evidence.grade;
                return `<button class="chip ${g === "D" ? "doc" : ""} ${id === S.node && !idle ? "sel" : ""}" data-n="${id}"><span>${n.label} ${gr(g)}</span><span class="ad">${n.contract_name || (n.address ? short(n.address) : n.kind)}</span></button>`;
              })
              .join("")}</div>`
          : ""
      }
    </div>`;
        }).join("");
        h += `<div class="lay pos ${idle ? "" : "hot"}"><span class="ln">◆</span><div class="lrow"><span class="lt"><span class="lbl">Your position</span><b>${isLev() ? "PT posted as collateral" : "PT held outright"}</b><span class="fact">${isLev() ? `Collateral ${money(P.collateral_usd)}, debt ${money(P.debt_usd)}` : money(P.collateral_usd)}</span></span>${ef[6] ? `<span class="eff">${ef[6]}</span>` : ""}</div></div>`;
        $("#chain").innerHTML = h;
      }

      /* Causal graph: which nodes and edges this incident reaches. lending → market (forced selling) fires only when
   the backend's exit numbers show liquidators selling into the pool. */
      const GCOL = {
        eth: "1 / -1",
        ethena: 2,
        usde: 3,
        susde: 4,
        feeds: 1,
        oracle: 2,
        market: 3,
        pt: 4,
        lending: 3,
      };
      const GSUB = {
        eth: "Every contract below settles here",
        ethena:
          d.offchain && d.offchain.USDe
            ? COPY.offchain.card(d.offchain.USDe.counts.relations)
            : NODES.ethena.note || "",
        usde: "Backs sUSDe",
        susde: "The PT redeems to this",
        feeds: "Feeds the oracle reads",
        oracle: NODES.oracle.contract_name || "Prices the collateral",
        market: money(d.position.pool_liquidity_usd) + " liquidity",
        pt: "Expires " + EXPIRY,
        lending: `Loan-to-value ${pc(LD.aggregate_ltv)} / limit ${pc(LD.lltv)}`,
      };
      const ET = { "pt>lending": 0.6 };
      const nl = (id) => (id === "pos" ? "Your position" : NODES[id].label);
      let FLOW = { nodes: new Set(), edges: new Set() },
        IDLE = false;
      function flow(st) {
        if (S.fail === "halt")
          return {
            nodes: new Set([...Object.keys(NODES), "pos"]),
            edges: new Set(),
          };
        const nodes = new Set([S.node]),
          edges = new Set(),
          q = [S.node];
        if (st.follows) {
          nodes.add("oracle");
          q.push("oracle");
        } /* the oracle follows, so liquidations run through it */
        while (q.length) {
          const n = q.shift();
          EDGES.forEach((e, i) => {
            if (e.from !== n || !edgeOn(e)) return;
            if (e.from === "lending" && e.to === "market" && !st.forced) return;
            edges.add(i);
            if (!nodes.has(e.to)) {
              nodes.add(e.to);
              q.push(e.to);
            }
          });
        }
        return { nodes, edges };
      }
      function nodeFx(m, st, fl) {
        const f = S.fail,
          sv = sevText(),
          o = {},
          note = {};
        if (f === "halt") {
          o.eth = st.origin;
          o.pos = st.pos;
          return { o, note };
        }
        if (f === "depeg" || f === "shortfall")
          ["usde", "susde", "pt"].forEach((k) => {
            if (fl.nodes.has(k)) o[k] = `Down ${sv}`;
          });
        o[S.node] = f === "depeg" ? `Down ${sv}` : st.origin;
        if (st.orc && S.node !== "oracle") {
          if (m.sev.oracle_falls === false) note.oracle = st.orc;
          else {
            o.oracle = st.orc;
            if (m.sev.oracle_falls === true) fl.nodes.add("oracle");
          }
        }
        if (st.exit && S.node !== "market") o.market = st.exit;
        if (st.liq && S.node !== "lending") {
          if (st.liq === "Not liquidated") note.lending = st.liq;
          else o.lending = st.liq;
        }
        o.pos =
          S.node === "market" && st.exit && !(m.sev.loss_usd > 0)
            ? st.exit
            : st.pos;
        return { o, note };
      }
      function renderGraph(m, idle) {
        const st = idle ? null : story(m),
          fl = idle ? { nodes: new Set(), edges: new Set() } : flow(st),
          fxr = idle ? { o: {}, note: {} } : nodeFx(m, st, fl),
          fx = fxr.o,
          P = m.P;
        FLOW = fl;
        IDLE = !!idle;
        const node = (id) => {
          const n = NODES[id],
            hot = fl.nodes.has(id),
            org = !idle && id === S.node,
            past = org && !!S.past,
            hyp = org && !S.past,
            g = n.evidence && n.evidence.grade;
          const tags =
            (past ? `<span class="tag det">${COPY.past.tag}</span>` : "") +
            (hyp ? '<span class="tag hyp">What-if</span>' : "");
          const sub = fx[id]
            ? `<b>${fx[id]}</b>`
            : fxr.note[id]
              ? fxr.note[id]
              : GSUB[id];
          return `<button class="node ${g === "D" ? "doc" : ""} ${hot ? "hot" : ""} ${org ? "origin" : ""} ${hyp ? "hyp" : ""}" data-n="${id}" data-g="${id}" style="grid-column:${GCOL[id]}"><span class="nm">${n.label}</span>${tags}<span class="sub">${sub}</span></button>`;
        };
        let h = '<svg id="edges" aria-hidden="true"></svg>';
        LAY.forEach((L) => {
          h += `<div class="band"><div class="lname"><b>${L.n}</b>${L.name}</div><div class="grow">${L.nodes.map(node).join("")}</div></div>`;
        });
        const ph = fl.nodes.has("pos");
        h += `<div class="band"><div class="lname">Your position</div><div class="grow"><div class="node pos ${ph ? "hot" : ""}" data-g="pos" style="grid-column:${isLev() ? 3 : 4}"><span class="nm">${isLev() ? "PT posted as collateral" : "PT held outright"}</span><span class="sub">${isLev() ? `Collateral ${money(P.collateral_usd)}, debt ${money(P.debt_usd)}` : money(P.collateral_usd)}</span>${fx.pos ? `<span class="sub"><b>${fx.pos}</b></span>` : ""}${!idle && !ph ? '<span class="sub">The incident does not reach your position.</span>' : ""}</div></div></div>`;
        $("#chain").innerHTML =
          `<div class="gscroll"><div class="graph" id="graph">${h}<div id="elabels"></div></div></div>`;
        paint();
      }
      function paint() {
        const g = $("#graph"),
          svg = $("#edges");
        if (!g || !svg) return;
        const R = g.getBoundingClientRect();
        const box = (id) => {
          const el = g.querySelector(`[data-g="${id}"]`);
          if (!el) return null;
          const r = el.getBoundingClientRect();
          return {
            x: r.left - R.left + r.width / 2,
            y: r.top - R.top + r.height / 2,
            w: r.width,
            h: r.height,
          };
        };
        const clip = (a, b, pad) => {
          const dx = b.x - a.x,
            dy = b.y - a.y,
            s = Math.min(
              dx ? (a.w / 2 + pad) / Math.abs(dx) : 1e9,
              dy ? (a.h / 2 + pad) / Math.abs(dy) : 1e9,
            );
          return [a.x + dx * s, a.y + dy * s];
        };
        let cold = "",
          hotL = "",
          labs = "";
        EDGES.forEach((e, i) => {
          if (!edgeOn(e)) return;
          const a = box(e.from),
            b = box(e.to);
          if (!a || !b) return;
          const hot = FLOW.edges.has(i),
            t = ET[e.from + ">" + e.to] || 0.5,
            cls = `class="e ${e.grade === "D" ? "doc" : ""} ${hot ? "hot" : ""}" marker-end="url(#${hot ? "ah" : "an"})"`;
          let x1, y1, x2, y2, ln;
          if (e.from === "oracle" && e.to === "lending") {
            /* elbow: straight down the oracle's column, then into the lending market's side */
            x1 = x2 = a.x;
            y1 = a.y + a.h / 2 + 1;
            y2 = b.y;
            ln = `<path d="M${x1} ${y1}V${y2}H${b.x - b.w / 2 - 6}" ${cls}/>`;
          } else {
            [x1, y1] = clip(a, b, 1);
            [x2, y2] = clip(b, a, 6);
            ln = `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" ${cls}/>`;
          }
          if (hot) hotL += ln;
          else cold += ln;
          if (hot || IDLE)
            labs += `<button class="elab ${hot ? "hot" : ""}" data-e="${i}" style="left:${x1 + (x2 - x1) * t}px;top:${y1 + (y2 - y1) * t}px" aria-label="Evidence for ${nl(e.from)} to ${nl(e.to)}">${e.type}</button>`;
        });
        const mk = (id, v) =>
          `<marker id="${id}" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L10 5L0 10z" style="fill:var(${v})"/></marker>`;
        svg.innerHTML =
          "<defs>" +
          mk("an", "--line-strong") +
          mk("ah", "--crit") +
          "</defs>" +
          cold +
          hotL;
        $("#elabels").innerHTML = labs;
      }
      function renderChain(m, idle) {
        const g = S.view === "graph";
        $("#v-graph").setAttribute("aria-pressed", g);
        $("#v-list").setAttribute("aria-pressed", !g);
        g ? renderGraph(m, idle) : renderList(m, idle);
      }

      function bar(name, segs, val, max) {
        return `<span class="bn">${name}</span><span class="track">${segs
          .filter((s) => s[1] > 0)
          .map(
            (s) =>
              `<i class="${s[0]}" style="width:${Math.max(0.5, (s[1] / max) * 100)}%" title="${s[2]}"></i>`,
          )
          .join("")}</span><span class="bv">${val}</span>`;
      }
      const det = (id, title, body) =>
        `<details id="${id}" ${S.open[id] ? "open" : ""}><summary>${title}</summary><div>${body}</div></details>`;
      const yn = (v) => (v === true ? "yes" : v === false ? "no" : "unknown");

      function renderDecision(m) {
        const s = m.sev,
          C = m.C,
          f = m.f,
          be = m.be,
          where = NODES[S.node].label,
          hasLoss = m.hasLoss,
          v = m.verdict,
          stuckUsd = s.stuck_fraction * C;
        const vw =
          v === "STAY" ? "Stay" : v === "EXIT" ? "Exit" : `Sell ${money(s.sell_usd)}`;
        const sub = !hasLoss
          ? "no direct loss"
          : v === "REDUCE"
            ? `${pc(m.x, 0)} of the position`
            : v === "SELL_TO_CAP"
              ? `all the pool will take${stuckUsd > 0 ? ` · ${money(stuckUsd)} stuck` : ""}`
              : "";
        const L = s.liquidated || [];
        const facts =
          s.type === "loss_model"
            ? ` Oracle follows: ${yn(s.oracle_falls)}.${m.P.debt_usd > 0 ? ` Liquidated: ${L.includes(true) ? (L.includes(false) ? "only if the oracle follows" : "yes") : "no"}.` : ""}`
            : "";
        const rule = `<p class="note">${cap1(s.note)}.${facts}</p>`;
        const ifTxt = `If ${where} ${lc(f.label)} by ${sevText()}`;
        const beTxt =
          m.start === null
            ? "Selling does not pay at any severity on this slider."
            : `Selling starts to pay once the severity exceeds <b>${sevText(m.start)}</b>${m.cap !== null && m.cap > m.start + 1e-9 ? ` and reaches the pool limit from <b>${sevText(m.cap)}</b>` : ""}.`;
        let why,
          body = "";
        if (!hasLoss) {
          why = "No loss is modelled for this position in this case.";
          body += rule;
          if (
            (s.type === "not_modelled" && S.fail === "halt") ||
            s.sellable_later < s.sellable_now - 1e-9
          ) {
            const now = s.sellable_now * C,
              later = S.fail === "halt" ? 0 : s.sellable_later * C;
            body += `<div class="bars">${bar("Sellable today", [["b-cap", now, money(now)]], money(now), now)}${bar("If this plays out", [["b-cap", later, money(later)]], S.fail === "halt" ? `None for ${sevText()}` : later ? money(later) : "None", now)}</div>`;
          }
        } else {
          why =
            v === "STAY"
              ? `${ifTxt}, doing nothing loses <b>${money(s.loss_if_stay_usd)}</b>; selling would cost more than it saves. ${beTxt}`
              : `${ifTxt}, doing nothing loses <b>${money(s.loss_if_stay_usd)}</b>. Selling <b>${money(s.sell_usd)}</b> now costs ${money(s.sale_cost_usd)} and leaves ${money(s.loss_kept_usd)} at risk on the rest. ${beTxt}`;
          /* "Act" = the recommended sale; on Stay, show selling to the pool limit so the bar shows why not. */
          const xa = m.x || MAXX,
            actCost = m.x
              ? s.sale_cost_usd
              : xa * (RM.slippageAt(xa, CURVE) + m.cy) * C,
            actKept = m.x ? s.loss_kept_usd : (1 - xa) * s.loss_if_stay_usd,
            max = Math.max(s.loss_if_stay_usd, actCost + actKept);
          body += `<div class="bars">${bar("Do nothing", [["b-loss", s.loss_if_stay_usd, "Loss if you do nothing " + money(s.loss_if_stay_usd)]], money(s.loss_if_stay_usd), max)}${bar(
            m.x ? "Act" : `Sell ${pc(xa, 0)}`,
            [
              ["b-cost", actCost, "Cost of selling " + money(actCost)],
              ["b-loss", actKept, "Loss on the part you keep " + money(actKept)],
            ],
            money(actCost + actKept),
            max,
          )}</div>
      <div class="bkey"><span><i class="b-loss"></i>Loss</span><span><i class="b-cost"></i>Cost of selling</span></div>`;
          if (v === "SELL_TO_CAP" && stuckUsd > 0)
            body += `<div class="stuck"><b>${money(stuckUsd)} cannot be sold through Pendle now.</b> With the rest you keep, ${money(s.loss_kept_usd)} stays at risk.</div>`;
          body += `<p class="note">At this severity, doing nothing loses <b>${money(s.loss_usd)}</b>: ${pc(s.L_high, 1)} of your ${m.P.debt_usd > 0 ? "equity" : "position"}, ${pc((s.L_high * S.book) / 100, 1)} of the book.${s.L_low !== s.L_high ? ` Loss is between ${pc(s.L_low, 1)} and ${pc(s.L_high, 1)} depending on the oracle; the decision uses the high end.` : ""}</p>`;
          body += rule;
          body += `<p class="note">Losses and the decision come from the backend model (RiskModel.decideAt). ${src(d.evidence.mechanism)}</p>`;
          const sevFlip =
            m.start === null
              ? `Stay at every severity up to ${sevText(f.max)}.`
              : `Stay below ${sevText(m.start)}${m.start < f.min - 1e-9 ? " (below this slider)" : ""}. ` +
                (m.cap === null
                  ? "The pool limit is not reached on this slider."
                  : `Sell up to the ${pc(MAXX, 0)} pool limit from ${sevText(m.cap)}.`);
          body += det(
            "d-flip",
            "What would change the answer",
            `<dl>
      <dt>Severity</dt><dd>${sevFlip}</dd>
      <dt>Position preset</dt><dd>${m.others.map((o) => `${o.m.P.label}: <b>${word(o.m)}</b>${o.m.hasLoss ? ` (doing nothing loses ${money(o.m.sev.loss_if_stay_usd)})` : ""}`).join("<br>")}</dd>
      <dt>Cash earns</dt><dd>You assume cash earns <span class="asm">${trim(S.alt)}%</span> a year after selling; the PT yields ${pc(d.position.implied_apy, 2)}. Each sale gives up ${pc(m.cy, 2)} of the amount sold until ${EXPIRY}. Change it under Assumptions.</dd>
      <dt>Rule</dt><dd>Assume the incident has happened at this severity. Pick the share x that minimises x × (slippage + yield given up) + (1 − x) × loss. Never beyond the largest size Pendle quoted.</dd></dl>`,
          );
        }
        $("#decision").innerHTML =
          `<div class="vband ${VCLASS[v]}"><span class="lbl">${S.past ? COPY.past.band(pastOf().label) : "What-if"} · ${FAIL[S.fail].phrase(sevText())} at ${where}</span>
    <div class="verdict">${vw}${sub ? `<small>${sub}</small>` : ""}</div><p class="why">${why}</p></div><div class="dbody">${isReal(S.pos) ? `<p class="note">${COPY.position.notYours(PRE[S.pos].label)}</p>` : ""}${body}</div>`;
      }

      const ymaxOf = (c) =>
        (Math.ceil((Math.max(...c.map((p) => p[1])) * 1000) / 3) * 3) / 1000;
      const CH = { W: 392, H: 190, l: 42, r: 10, t: 10, b: 48, ymax: ymaxOf(CURVE) };
      function useCurve(posKey) {
        [CURVE, MAXX] = RM.sizeCurve(d, PRE[posKey].collateral_usd);
        CH.ymax = ymaxOf(CURVE);
      }
      const CX = (f) => CH.l + f * (CH.W - CH.l - CH.r),
        CY = (v) =>
          CH.H - CH.b - (Math.min(v, CH.ymax) / CH.ymax) * (CH.H - CH.t - CH.b);
      const stressCurve = (k) => CURVE.map(([x, s]) => [x * (1 - k), s]);
      function chart(m, sc) {
        const { W, H, l, r, t, b } = CH;
        const line = (c) =>
          c
            .map(([f, s]) => `${CX(f).toFixed(1)},${CY(s).toFixed(1)}`)
            .join(" ");
        let rec = "";
        if (m.x > 0) {
          const rx = CX(m.x),
            ry = CY(m.slip);
          rec = `<line class="rec" x1="${rx}" y1="${CY(0)}" x2="${rx}" y2="${ry}"/><circle class="recd" cx="${rx}" cy="${ry}" r="5"/><text class="rt" x="${rx}" y="${H - b + 27}" text-anchor="middle">Sell ${pc(m.x, 0)}</text>`;
        }
        const xt = [
          ...new Set([0, Math.round(MAXX * 10) / 20, MAXX, 1]),
        ];
        return `<svg class="chart" id="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Cost of selling against the share of the position sold. Today Pendle quotes up to ${pc(MAXX, 0)}.">
   ${MAXX < 1 - 1e-9 ? `<rect class="no" x="${CX(MAXX)}" y="${t}" width="${CX(1) - CX(MAXX)}" height="${H - t - b}"/>` : ""}
   ${[0, 1, 2, 3]
     .map((i) => (CH.ymax * i) / 3)
     .map(
       (v) =>
         `<line class="ax" x1="${l}" y1="${CY(v)}" x2="${W - r}" y2="${CY(v)}"/><text x="${l - 6}" y="${CY(v) + 4}" text-anchor="end">${pc(v, 1)}</text>`,
     )
     .join("")}
   ${xt.map((f) => `<text x="${CX(f)}" y="${H - b + 14}" text-anchor="${f === 1 ? "end" : f === 0 ? "start" : "middle"}">${pc(f, 0)}</text>`).join("")}
   <text x="${l}" y="${H - 5}">Share of the position sold</text>
   ${MAXX < 1 - 1e-9 ? `<line class="cliff" x1="${CX(MAXX)}" y1="${t}" x2="${CX(MAXX)}" y2="${H - b}"/>
   <text x="${CX((1 + MAXX) / 2)}" y="${t + 58}" text-anchor="middle">Pendle refuses</text><text x="${CX((1 + MAXX) / 2)}" y="${t + 72}" text-anchor="middle">sales this large</text>` : ""}
   ${sc ? `<polyline class="sv" points="${line(sc)}"/>` : ""}
   <polyline class="cv" points="${line(CURVE)}"/>${CURVE.map(([f, s]) => `<circle class="pt" cx="${CX(f)}" cy="${CY(s)}" r="2.6"/>`).join("")}${rec}
   <line class="cross" id="cross" x1="0" x2="0" y1="${t}" y2="${H - b}" visibility="hidden"/></svg>`;
      }
      function renderExit(m, idle) {
        const C = m.C,
          s = m.sev,
          cap = s.sellable_now * C,
          last = RM.slippageAt(s.sellable_now, CURVE),
          isDrain = !idle && s.type === "exit_only";
        let later = null;
        CUR = { type: "idle" };
        if (!idle) {
          const sl = s.sellable_later,
            changed =
              sl < s.sellable_now - 1e-9 ||
              Math.abs((s.avg_cost_later ?? 0) - last) > 1e-7;
          CUR = {
            type: isDrain ? "drain" : s.type,
            k: S.sev / 100,
            later: sl,
            halt: S.fail === "halt",
          };
          if (S.fail === "halt") later = `No exit for ${sevText()}: ${s.note}.`;
          else if (s.avg_cost_later == null || sl <= 0)
            later = `No room left. Liquidators' PT fills the pool first${s.exit_row_drop != null ? ` (Morpho liquidation curve at a ${pc(s.exit_row_drop)} oracle drop)` : ""}.`;
          else if (isDrain)
            later = `Up to ${money(sl * C)} (${pc(sl, 0)}). <span class="asm">${pc(S.sev / 100, 0)} of pool liquidity leaves</span>, so each sale costs what a sale ${trim(1 / (1 - S.sev / 100))}× its size costs today.`;
          else if (changed)
            later = `Up to ${money(sl * C)} (${pc(sl, 0)}) at an average cost of ${pc(s.avg_cost_later, 2)}, after liquidators sell first${s.exit_row_drop != null ? ` (Morpho liquidation curve at a ${pc(s.exit_row_drop)} oracle drop)` : ""}.`;
          else later = "Exit capacity is not affected in this model.";
        }
        const fr = [0].concat(CURVE.map((c) => c[0]).filter((f) => f >= 0.1));
        if (m.x > 0 && !fr.some((f) => Math.abs(f - m.x) < 1e-9)) fr.push(m.x);
        fr.sort((a, b) => a - b);
        const isQ = (f) => !f || CURVE.some((k) => Math.abs(k[0] - f) < 1e-9);
        const row = (f) => {
          const sl = f ? RM.slippageAt(f, CURVE) : 0,
            cost = f * (sl + m.cy) * C,
            kept = (1 - f) * m.L * m.equity;
          return `<tr class="${m.hasLoss && Math.abs(f - m.x) < 1e-9 ? "best" : ""}"><td>${f ? pc(f, 0) + " · " + money(f * C) : "Stay"}${isQ(f) ? "" : " *"}</td><td>${f ? pc(sl, 2) : "–"}</td><td>${money(cost)}</td><td>${money(kept)}</td><td>${money(cost + kept)}</td></tr>`;
        };
        /* Refused sizes are quoted as shares of the size input's position (N): convert through USD and keep those
   within this position. */
        const refused = [
          ...(d.evidence.max_exit_fraction.source || "").matchAll(
            /([\d.]+) refused \((\w+)/g,
          ),
        ]
          .filter((r) => +r[1] * N <= C * (1 + 1e-9))
          .map(
            (r) =>
              `<tr class="ref"><td>${pc((+r[1] * N) / C, 0)} · ${money(+r[1] * N)}</td><td colspan="4">Refused: ${r[2]}</td></tr>`,
          )
          .join("");
        $("#exit").innerHTML =
          `<div class="phead"><h2>Can you get out?</h2><span class="note">Real Pendle quotes, ${DAY}</span></div>
   <dl><dt>Today</dt><dd>Up to ${money(cap)} (${pc(s.sellable_now, 0)}), costing ${pc(last, 2)} in slippage.</dd>${later ? `<dt>If this plays out</dt><dd>${later}</dd>` : ""}</dl>
   <div class="ckey"><span><svg width="22" height="6" aria-hidden="true"><line x1="0" y1="3" x2="22" y2="3" style="stroke:var(--ink);stroke-width:2"/></svg>Today's quotes</span>${isDrain ? '<span><svg width="22" height="6" aria-hidden="true"><line x1="0" y1="3" x2="22" y2="3" style="stroke:var(--muted);stroke-width:2;stroke-dasharray:5 4"/></svg>If this plays out</span>' : ""}${m.x > 0 ? '<span><svg width="10" height="10" aria-hidden="true"><circle cx="5" cy="5" r="4" style="fill:var(--accent)"/></svg>Recommended sale</span>' : ""}</div>
   <div class="cwrap" id="cwrap">${chart(m, isDrain ? stressCurve(S.sev / 100) : null)}<div class="tip" id="tip" hidden></div></div>
   ${det(
     "d-sizes",
     "All sale sizes",
     `<div class="tw"><table><thead><tr><th>Sell</th><th>Slippage</th><th>Sale cost</th><th>Loss kept</th><th>Total</th></tr></thead><tbody>${fr.map(row).join("")}${refused}</tbody></table></div>
     <p class="note">${m.hasLoss ? "The highlighted row has the lowest total. " : ""}${fr.some((f) => !isQ(f)) ? "* Interpolated between two quotes. " : ""}Sale cost includes yield given up (${pc(m.cy, 2)} of the amount sold). Counts only the Pendle swap route: no limit orders, OTC, or holding to expiry.</p>
     <p class="note">Quotes: ${src(d.evidence.exit_curve)}</p>`,
   )}`;
      }

      function renderSteps(m) {
        const be = m.be,
          f = m.f,
          S0 = m.start === null ? null : sevText(m.start),
          K0 = m.cap === null ? null : sevText(m.cap);
        $("#sevOut").textContent = sevText();
        const zt =
          m.start === null
            ? m.hasLoss
              ? " Stay at every severity on this slider."
              : ""
            : m.start < f.min - 1e-9
              ? ` Selling starts at ${S0}, below this slider; ${m.cap === null ? "the pool limit is not reached on it" : `sell to the pool limit from ${K0}`}.`
              : ` Stay below ${S0}; ` +
                (m.cap === null
                  ? "sell part above it."
                  : m.cap > m.start + 1e-9
                    ? `sell part from ${S0}, to the pool limit from ${K0}.`
                    : `sell to the pool limit from ${S0}.`);
        $("#sevNote").textContent =
          (S.past
            ? COPY.past.sevNote(sevText(pastOf().sev))
            : `${f.sev}: ${sevText()}.`) + zt;
        let h = "";
        if (be.start !== null || m.hasLoss) {
          const w = (v) =>
              v === null
                ? 100
                : isLog(f)
                  ? (sevPos(f, v) / LOGR) * 100
                  : ((v - f.min) / (f.max - f.min)) * 100,
            a = w(be.start),
            b = w(be.cap);
          h = `<div class="zones" role="img" aria-label="Severity ranges for stay, partial sale and selling to the pool limit"><i class="zs" style="width:${a}%"></i><i class="zp" style="width:${b - a}%"></i><i class="zc" style="width:${100 - b}%"></i></div>`;
        }
        $("#zoneBox").innerHTML = h;
      }
      function syncSteps() {
        $("#q1").textContent = "Test a failure at…";
        $("#n1").textContent = COPY.steps.hint;
        $("#node").innerHTML = LAY.map(
              (L) =>
                `<optgroup label="What-if · ${L.n} · ${L.name}">${L.nodes
                  .filter((k) => fails(k).length)
                  .map((k) => `<option value="${k}">${NODES[k].label}</option>`)
                  .join("")}</optgroup>`,
            )
            .join("");
        $("#node").value = S.node;
        $("#pos").value = S.pos;
        $("#fail").innerHTML = fails(S.node)
          .map((k) => `<option value="${k}">${FAIL[k].label}</option>`)
          .join("");
        $("#fail").value = S.fail;
        const f = FAIL[S.fail],
          sv = $("#sev");
        if (isLog(f)) {
          sv.step = 1;
          sv.min = 0;
          sv.max = LOGR;
          sv.value = sevPos(f, S.sev);
        } else {
          sv.step = f.unit === "%" ? 0.1 : 1;
          sv.min = f.min;
          sv.max = f.max;
          sv.value = S.sev;
        }
      }
      function render() {
        useCurve(S.pos);
        const m = model();
        renderSteps(m);
        renderChain(m);
        renderDecision(m);
        renderExit(m);
      }
      function apply() {
        syncSteps();
        renderBanner();
        render();
      }
      function setNode(id, fail, sev) {
        const f = fail && fails(id).includes(fail) ? fail : fails(id)[0];
        if (!f) return;
        S.node = id;
        setFail(f, sev);
      }
      function setFail(k, sev) {
        S.fail = k;
        S.sev = sev != null ? sev : FAIL[k].def;
        apply();
      }
      const MAIN = { 2: "susde", 3: "oracle", 4: "market" };
      /* The past event's banner (its own element: #banner is kept for the load error). */
      function renderBanner() {
        const b = $("#pastBanner"),
          p = pastOf();
        b.hidden = !p;
        b.innerHTML = p
          ? COPY.past.banner(
              p.label,
              `${FAIL[p.fail].phrase(sevText(p.sev))} at ${NODES[p.node].label}`,
              src(p.evidence),
            )
          : "";
        $("#replay").value = S.past || "";
      }

      function openDrawer(title, rows) {
        $("#drawerIn").innerHTML =
          `<div class="top"><div><span class="lbl">Evidence</span><h3>${title}</h3></div><button class="btn" id="closeDrawer">Close</button></div>
   <dl>${rows
     .filter(Boolean)
     .map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`)
     .join("")}</dl>`;
        $("#drawer").hidden = false;
        document.body.classList.add("drawer-open");
      }
      function closeDrawer() {
        $("#drawer").hidden = true;
        document.body.classList.remove("drawer-open");
      }
      const addrLink = (a) =>
        /^0x[0-9a-f]{40}$/i.test(a || "")
          ? `<span class="mono">${a}</span> · <a href="https://etherscan.io/address/${a}" target="_blank" rel="noopener">Etherscan</a>`
          : null;
      function oraclePart(name, o) {
        if (!o) return null;
        const parts = Object.entries(o.parts || {})
          .map(
            ([k, p]) =>
              `${k}: ${p.contract_name}${p.description ? " (" + p.description + ")" : ""} ${gr(p.evidence && p.evidence.grade)}`,
          )
          .join("; ");
        return [
          name,
          `${o.contract_name} ${gr(o.evidence && o.evidence.grade)} <span class="mono">${short(o.address)}</span>. Follows the underlying: ${yn(o.tracks_underlying)}; follows the PT market: ${yn(o.tracks_market)}.${parts ? " " + parts + "." : ""}`,
        ];
      }
      function nodeEvidence(id) {
        const n = NODES[id],
          dt = pastOf() && pastOf().node === id ? pastOf() : null;
        const addr = n.address
          ? `<span class="mono" id="addrTxt">${n.address}</span> <button class="link" id="copy" data-a="${n.address}">Copy</button> · <a href="https://etherscan.io/address/${n.address}" target="_blank" rel="noopener">Open on Etherscan</a>`
          : n.market_id
            ? `Morpho market <span class="mono">${n.market_id}</span>`
            : "No single contract";
        const pe = d.position.evidence || {},
          le = LD.evidence || {};
        const extra =
          id === "lending"
            ? [
                [
                  "Collateral / borrowed",
                  `${money(LD.collateral_usd)} / ${money(LD.borrow_usd)} · ${src(le.collateral_usd)}`,
                ],
                [
                  "Loan-to-value / limit",
                  `${pc(LD.aggregate_ltv)} / ${pc(LD.lltv)} · ${src(le.aggregate_ltv)}`,
                ],
                [
                  "Lenders can withdraw now",
                  `${money(LD.liquidity_usd)} · ${src(le.liquidity_usd)}`,
                ],
                BW.distribution && [
                  "Borrowers",
                  `${BW.distribution.n_borrowers}, loan-to-value from ${pc(BW.distribution.ltv_min)} to ${pc(BW.distribution.ltv_max)} · ${src(BW.evidence && BW.evidence.distribution)}`,
                ],
              ]
            : id === "market"
              ? [
                  [
                    "Pool liquidity",
                    `${money(d.position.pool_liquidity_usd)} · ${src(pe.pool_liquidity_usd)}`,
                  ],
                  [
                    "Implied yield",
                    `${pc(d.position.implied_apy, 2)} APY · ${src(pe.implied_apy)}`,
                  ],
                  ["Expiry", `${EXPIRY} (${DAYS} days) · ${src(pe.expiry)}`],
                  [
                    "Largest sale quoted",
                    `${money(d.max_exit_fraction * N)} · ${src(d.evidence.max_exit_fraction)}`,
                  ],
                ]
              : id === "oracle" && ORC
                ? [
                    ["Oracle now", `${ORC.current} · ${src(ORC.evidence)}`],
                    oraclePart("Primary", ORC.primary),
                    oraclePart("Backup", ORC.backup),
                    [
                      "Switch rule",
                      `Deviation above ${pc(ORC.deviation_threshold, 2)} lasting ${TL} h; deviation now ${pc(ORC.deviation_now, 3)}. ${ORC.rule}.`,
                    ],
                  ]
                : [];
        /* Off-chain entities are shown grouped and sourced in their own row (offchainRow), not as members. */
        const members = (n.members || [])
          .filter((k) => !k.startsWith("offchain:"))
          .map((k) => {
            const g = GN[k];
            if (!g) return `<span class="mono">${short(k)}</span>`;
            return `${g.label}${g.contract_name && g.contract_name !== g.label ? " · " + g.contract_name : ""} ${gr(g.evidence && g.evidence.grade)}${/^0x[0-9a-f]{40}$/i.test(g.address || "") ? ` <a class="mono" href="https://etherscan.io/address/${g.address}" target="_blank" rel="noopener">${short(g.address)}</a>` : ""}`;
          })
          .join("<br>");
        const links = EDGES.filter(
          (e) => (e.from === id || e.to === id) && edgeOn(e),
        )
          .map(
            (e) =>
              `${nl(e.from)} → ${nl(e.to)} (${e.type}) ${gr(e.grade)}<br><span class="mono">${e.evidence}</span>`,
          )
          .join("<br>");
        openDrawer(n.label, [
          dt && [COPY.past.drawerRow, `${dt.label} · ${src(dt.evidence)}`],
          ["Type", n.kind],
          ["Layer", n.layer + " · " + LAY[n.layer - 1].name],
          ["Contract", (n.contract_name ? n.contract_name + " · " : "") + addr],
          ["Source", src(n.evidence)],
          n.note && ["Note", cap1(n.note)],
          ...extra,
          members && ["Contracts behind it", members],
          offchainRow(id),
          links && ["Links", links],
        ]);
      }
      /* Off-chain dependencies from the issuer's documents (guide section 8): ethena -> d.offchain.USDe, susde ->
   d.offchain.sUSDe, usde -> a pointer to the ethena drawer (the same 31 relations twice would be noise).
   Collapsed: issuer, summary and the count per kind; the relations open on demand. Grade D, drawn dashed. */
      const OFFKEY = { ethena: "USDe", usde: "USDe", susde: "sUSDe" };
      function offchainRow(id) {
        const o = d.offchain && d.offchain[OFFKEY[id]],
          C = COPY.offchain;
        if (!o || !o.relations) return null;
        if (id === "usde")
          return [
            C.title,
            `${o.summary} ${C.seeEthena} <button class="link" data-drawer="ethena">${C.openEthena}</button>`,
          ];
        const groups = {};
        o.relations.forEach((r) => (groups[r.kind] = groups[r.kind] || []).push(r));
        const kind = (k) => C.kinds[k] || k;
        const day = (t) =>
          t
            ? new Date(t).toLocaleString("en-GB", { timeZone: "UTC", day: "numeric", month: "short" })
            : "";
        const rel = (r) => {
          const e = r.evidence || {};
          /* quote_found: true = re-checked on the page; null = the page refused the checker (not re-checked, still
   shown as the issuer's words); false = not on the page, so not shown as a quote. */
          const quote = !e.quote
            ? ""
            : e.quote_found === false
              ? `<span class="note">${C.notFound}</span>`
              : `<q class="oq">${e.quote}</q><span class="note">${e.quote_found === true ? C.rechecked(day(e.checked_at)) : C.notRechecked}</span>`;
          return `<li><b>${r.entity}</b>: ${r.relation} ${gr(e.grade)}${e.official === false ? ` <span class="tp">${C.thirdParty}</span>` : ""}${e.url ? ` · <a class="osrc" href="${e.url}" target="_blank" rel="noopener">${C.source}</a>` : ""}${quote}</li>`;
        };
        const did = "d-off-" + id;
        return [
          C.title,
          `${C.issuer}: <b>${o.issuer}</b>. ${o.summary}
   <details class="offc" id="${did}" ${S.open[did] ? "open" : ""}><summary>${Object.keys(groups)
     .map((k) => `${kind(k)} ${groups[k].length}`)
     .join(" · ")}</summary><div>${Object.keys(groups)
     .map((k) => `<h4>${kind(k)}</h4><ul>${groups[k].map(rel).join("")}</ul>`)
     .join("")}</div></details>`,
        ];
      }
      function edgeEvidence(i) {
        const e = EDGES[i];
        openDrawer(`${nl(e.from)} → ${nl(e.to)}`, [
          ["Dependency type", e.type],
          ["Grade", `${gr(e.grade)} ${d.evidence.grades[e.grade] || ""}`],
          ["Evidence", `<span class="mono">${e.evidence}</span>`],
        ]);
      }

      document.addEventListener("click", (ev) => {
        const t = ev.target.closest("button");
        if (!t) return;
        if (t.dataset.drawer) nodeEvidence(t.dataset.drawer);
        else if (t.dataset.layer) {
          S.past = null;
          const n = +t.dataset.layer;
          setNode(MAIN[n] || LAY[n - 1].nodes[0]);
        } else if (t.dataset.e) edgeEvidence(+t.dataset.e);
        else if (t.dataset.view) {
          S.view = t.dataset.view;
          try {
            localStorage.setItem("rd-view2", S.view);
          } catch (e) {}
          render();
        } else if (t.dataset.more) {
          const k = t.dataset.more;
          S.more[k] = !S.more[k];
          render();
        } else if (t.dataset.n) {
          S.past = null;
          const id = t.dataset.n;
          setNode(id);
          nodeEvidence(id);
        } else if (t.id === "closeDrawer") closeDrawer();
        else if (t.id === "copy") {
          const a = t.dataset.a;
          const sel = () => {
            const r = document.createRange();
            r.selectNodeContents($("#addrTxt"));
            const s = getSelection();
            s.removeAllRanges();
            s.addRange(r);
          };
          try {
            navigator.clipboard.writeText(a).then(() => {
              t.textContent = "Copied";
            }, sel);
          } catch (e) {
            sel();
          }
        }
      });
      document.addEventListener("input", (ev) => {
        const t = ev.target;
        if (t.id === "sev") {
          const f = FAIL[S.fail];
          S.sev = isLog(f) ? posSev(f, +t.value) : +t.value;
          if (S.past) {
            S.past = null;
            renderBanner();
          }
          render();
        }
      });
      document.addEventListener("change", (ev) => {
        const t = ev.target,
          num = (lo, hi, dv) => {
            const v = parseFloat(String(t.value).trim().replace(",", "."));
            return isFinite(v) ? Math.min(hi, Math.max(lo, v)) : dv;
          };
        if (t.id === "pos") {
          S.pos = t.value;
          closeDrawer();
          render();
        }
        if (t.id === "node") {
          S.past = null;
          setNode(t.value);
        }
        if (t.id === "fail") {
          S.past = null;
          setFail(t.value);
        }
        if (t.id === "replay") {
          closeDrawer();
          const p = PAST.find((x) => x.key === t.value);
          S.past = p ? p.key : null;
          if (p) setNode(p.node, p.fail, p.sev);
          else apply();
        }
        if (t.id === "alt") {
          S.alt = num(0, 50, 0);
          render();
        }
        if (t.id === "book") {
          S.book = num(1, 100, 10);
          render();
        }
      });
      document.addEventListener(
        "toggle",
        (ev) => {
          const t = ev.target;
          if (t.tagName === "DETAILS" && t.id && t.id !== "d-adv")
            S.open[t.id] = t.open;
        },
        true,
      );
      /* Chart hover: read both states at the pointer. */
      document.addEventListener("pointermove", (ev) => {
        const w = $("#cwrap"),
          svg = $("#chart"),
          tip = $("#tip"),
          cross = $("#cross");
        if (!w || !svg) return;
        if (!w.contains(ev.target)) {
          tip.hidden = true;
          cross.setAttribute("visibility", "hidden");
          return;
        }
        const R = svg.getBoundingClientRect(),
          vx = ((ev.clientX - R.left) / R.width) * CH.W,
          f = Math.round(((vx - CH.l) / (CH.W - CH.l - CH.r)) * 100) / 100;
        if (f < 0 || f > 1) {
          tip.hidden = true;
          cross.setAttribute("visibility", "hidden");
          return;
        }
        const now =
          f > MAXX + 1e-9
            ? "refused"
            : f
              ? pc(RM.slippageAt(f, CURVE), 2)
              : "–";
        let lt = "";
        if (CUR.halt) lt = "halted";
        else if (CUR.type === "drain")
          lt =
            f > CUR.later + 1e-9
              ? "no room"
              : f
                ? pc(RM.slippageAt(f / (1 - CUR.k), CURVE), 2)
                : "–";
        else if (CUR.type !== "idle" && CUR.later < MAXX - 1e-9)
          lt = f > CUR.later + 1e-9 ? "no room" : "can still be sold";
        tip.innerHTML = `<b>Sell ${pc(f, 0)} · ${money(f * PRE[S.pos].collateral_usd)}</b>Today: ${now}${lt ? "<br>If this plays out: " + lt : ""}`;
        tip.hidden = false;
        cross.setAttribute("x1", CX(f));
        cross.setAttribute("x2", CX(f));
        cross.setAttribute("visibility", "visible");
        const wr = w.getBoundingClientRect(),
          x = ev.clientX - wr.left;
        tip.style.top = "4px";
        tip.style.left = x > wr.width / 2 ? "" : x + 12 + "px";
        tip.style.right = x > wr.width / 2 ? wr.width - x + 12 + "px" : "";
      });

      /* Static parts filled from the data. */
      $("#pos").innerHTML = Object.keys(PRE)
        .map((k) => `<option value="${k}">${PRE[k].label}</option>`)
        .join("");
      $("#replay").innerHTML =
        '<option value="">Load a past incident pattern…</option>' +
        PAST.map((p) => `<option value="${p.key}">${p.label}</option>`).join("");
      $("#stamp").innerHTML =
        `Snapshot ${STAMP}${BW.block ? " · block " + BW.block.toLocaleString("en-US") : ""} · position size <span class="asm">${money(N)}</span>`;
      $("#advNote").innerHTML =
        `Position size: ${src(d.position.evidence && d.position.evidence.notional_usd)}. Every loss and decision comes from the backend model.`;
      ["alt", "book"].forEach((k) => {
        $("#" + k).value = k === "alt" ? S.alt.toFixed(2) : S[k];
      });
      try {
        const v = localStorage.getItem("rd-view2");
        if (v === "graph" || v === "list") S.view = v;
      } catch (e) {}
      if (!fails(S.node).includes(S.fail)) {
        const k = Object.keys(NODES).find((n) => fails(n).length);
        S.node = k;
        S.fail = fails(k)[0];
        S.sev = FAIL[S.fail].def;
      }
      apply();
      new ResizeObserver(() => paint()).observe($("#chain"));
      if (document.fonts && document.fonts.ready)
        document.fonts.ready.then(paint);
