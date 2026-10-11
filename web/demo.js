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
      const D0 = window.DASHBOARD,
        RM = window.RiskModel;
      /* d is the data at the manager's position size (RiskModel.atSize, guide 3b): set by resize() on load and on every
   size change; every model call takes this d. D0 is the backend's file as loaded. */
      let d = D0;
      if (!d || !RM) {
        $("#banner").hidden = false;
        $("#banner").innerHTML =
          "<b>Could not load the backend files.</b> This page needs ../sample_data/dashboard.sample.js and risk_model.js next to it.";
        throw new Error("backend files missing");
      }
      /* N0: the notional the Pendle quotes were taken at; the refused sizes in the evidence are shares of it. */
      const N0 = D0.position.notional_usd,
        SI = D0.size_input,
        LD = d.lending[0];
      /* Exit curve and largest sellable share of the selected position (guide section 0b): every position has its
   own curve, RiskModel.sizeCurve(d, collateral). d.exit_curve / d.max_exit_fraction describe only the size
   input's position. Set for the selected preset by useCurve() at each render. */
      let [CURVE, MAXX] = RM.sizeCurve(d, N0);
      let PRE = d.position_presets;
      const NODES = d.ui.nodes,
        LAY = d.ui.layers,
        FT = d.failure_types.types,
        GN = d.dependency_graph.nodes,
        ORC = d.oracle;
      const utc = (o) =>
        new Date(d.generated_at).toLocaleString(
          "en-GB",
          Object.assign({ timeZone: "UTC" }, o),
        );
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
      /* How long the incident lasts (guide section 5b, to-do 7): one rail on the chain, log scale from 1 h to 180 days.
   DEF_H is the duration of a manual incident and of a past event without a stated duration (the guide names none;
   the backend's explainer opens at 6 h). */
      const H_MIN = 1,
        H_MAX = 4320,
        DEF_H = 6;
      const hOf = (u) => H_MIN * Math.exp(Math.log(H_MAX / H_MIN) * u);
      const uOf = (h) => Math.log(h / H_MIN) / Math.log(H_MAX / H_MIN);
      /* Durations under 48 h read in hours, longer ones in days. */
      const durText = (h) => {
        const v = h < 48 ? h : h / 24;
        return String(v < 10 ? +v.toFixed(1) : Math.round(v)) + (h < 48 ? " h" : " days");
      };
      /* No evidence grades on the page (user decision, 11 Oct): gr() shows nothing, ng() drops "(grade X)" from the
   model's texts. The data keep their grades; grade D still draws dashed (an assumption). */
      const gr = () => "";
      const ng = (t) => String(t || "").replace(/ \(grade [A-D]\)/g, "");
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
      /* Edges come from the data only, including the two to the position (pt -> holding, lending -> liquidation for
   the presets in applies_to). The data names the position "position"; the page draws it as "pos". */
      const EDGES = d.ui.edges.map((e) =>
        e.to === "position" ? Object.assign({}, e, { to: "pos" }) : e,
      );

      /* Past incidents (guide sections 3c and 5b): real events that preset the controls, the duration and the recovers
   toggle included; their opts are not used (one mechanism, the duration). There is no detector and no invented
   incident. S.past = the selected key, null for a what-if test; moving the dependency, failure or severity drops
   it; changing the position, the duration or the recovers toggle keeps it. */
      const PAST = d.past_incidents || [];
      const pastOf = () => PAST.find((x) => x.key === S.past) || null;
      /* First screen (guide 3c, user decision): the PT-reUSD oracle drop on the real borrower closest to
   liquidation, so the decision card shows a liquidation and an exit. */
      const FIRST = PAST.find((x) => x.key === "pt_reusd_aug_2026") || PAST[0] || null;
      /* Real-borrower presets have a fixed on-chain size (sized: false): someone else's position. */
      const isReal = (k) => !!PRE[k] && PRE[k].sized === false;
      let CUR = { type: "none" },
        AC = null;
      const S = {
        view: "list",
        /* how the incident is set (user decision, 11 Oct): "past" = one of d.past_incidents, steps 1 and 2 read-only;
   "manual" = dependency, failure and severity by hand. One or the other, never both. */
        mode: FIRST ? "past" : "manual",
        past: FIRST ? FIRST.key : null,
        lastPast: FIRST ? FIRST.key : null,
        pos: PRE.lev_closest_to_liquidation
          ? "lev_closest_to_liquidation"
          : Object.keys(PRE)[0],
        node: FIRST ? FIRST.node : "susde",
        fail: FIRST ? FIRST.fail : "depeg",
        sev: FIRST ? FIRST.sev : 10,
        alt: d.position.implied_apy * 100,
        /* the first screen opens at the event's own duration (1 h for PT-reUSD); null-duration events: DEF_H, stays */
        hours: FIRST && FIRST.hours != null ? FIRST.hours : DEF_H,
        /* position size in USD for the presets the manager sizes (spot, lev_market_avg); assumed (D) until typed */
        size: SI.default_usd,
        sizeTyped: false,
        /* an address read on chain (guide 3b): "" = none; walletBad = the field holds something that is not one */
        wallet: "",
        walletBad: false,
        recovers: FIRST ? FIRST.hours != null && !!FIRST.recovers : true,
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
      const isLev = () => PRE[S.pos].debt_usd > 0;
      const edgeOn = (e) => !e.applies_to || e.applies_to.includes(S.pos);
      /* The inputs decideAtDuration used (guide 5b), passed to every other function so all numbers agree. */
      function durInputs(posKey, r) {
        const o = {
          hours: S.hours,
          collateral_usd: r.position_value_usd,
          collateral_oracle_usd: r.collateral_usd,
          debt_usd: r.debt_usd,
          sale_value_usd: PRE[posKey].collateral_usd,
        };
        if (S.recovers) o.permanent = 0;
        return o;
      }

      /* The decision given the incident at the chosen severity and duration, no probability (guide, sections 4 and
   5b): RiskModel.decideAtDuration for the verdict; breakEvenSeverity (the severity zones on step 2), sensitivity,
   decisionText and propagation with its inputs (o) and its carry (yield given up over the incident only, at most
   until expiry, from the annual "cash earns" input; unscaled: the model scales it per unit of equity). */
      function model(posKey = S.pos, light = false) {
        const P = PRE[posKey],
          C = P.collateral_usd,
          equity = C - P.debt_usd,
          f = FAIL[S.fail];
        const r = RM.decideAtDuration(d, posKey, S.node, S.fail, S.sev, S.hours, S.recovers, S.alt / 100),
          o = durInputs(posKey, r),
          cy = r.carry,
          x = r.sell_fraction;
        const m = {
          P,
          C,
          equity,
          f,
          sev: r,
          L: r.L_high,
          cy,
          o,
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
        /* "What would change the answer" (guide section 5): the backend's candidates, flips and weakest assumption */
        m.sv = RM.sensitivity(d, posKey, S.node, S.fail, S.sev, cy, o);
        /* The card's texts (guide section 5) and the incident's path through the five layers (section 6) */
        m.t = RM.decisionText(d, posKey, S.node, S.fail, S.sev, cy, o);
        m.pg = RM.propagation(d, posKey, S.node, S.fail, S.sev, cy, o);
        /* the exit chart's cost of acting at every share (same inputs) */
        m.ac = RM.actCostCurve(d, posKey, S.node, S.fail, S.sev, cy, o);
        return m;
      }
      const VCLASS = {
        STAY: "stay",
        REDUCE: "reduce",
        SELL_TO_CAP: "cap",
        EXIT: "cap",
      };

      /* Layers display, in the explainer's propagation form (user decision, 11 Oct): per layer "Layer n · name", its
   state badge and RiskModel.propagation's text for that layer; then the position (its step) and the result (the
   verdict and its step). The static layer heads and facts are gone. The rows stay buttons (manual mode: test an
   incident at that layer) and keep "Show dependencies and evidence". */
      const HOT = (st) => st === "origin" || st === "hit";
      const stBadge = (st) => `<span class="st" data-st="${st}">${COPY.layers.state[st] || st}</span>`;
      function renderList(m, idle) {
        const pg = m.pg,
          T = COPY.layers,
          org = idle ? 0 : pg.origin.layer,
          posStep = pg.steps.find((x) => x.node === "position"),
          res = pg.steps.find((x) => x.node === "result");
        let h = LAY.map((L) => {
          const ids = L.nodes,
            pl = pg.layers.find((x) => x.n === L.n) || { state: "unchanged", text: "" },
            hot = !idle && HOT(pl.state),
            open = !!S.more[L.n];
          const past = org === L.n && !!S.past,
            hyp = org === L.n && !S.past;
          const tags =
            (past ? `<span class="tag det">${COPY.past.tag}</span>` : "") +
            (hyp ? '<span class="tag hyp">What-if</span>' : "");
          return `<div class="lay ${hot ? "hot" : ""} ${org === L.n ? "origin" : ""} ${hyp ? "hyp" : ""}" data-state="${pl.state}" data-ln="${L.n}"><span class="ln">${L.n}</span>
      <button class="lrow" data-layer="${L.n}" aria-label="Test an incident at layer ${L.n}, ${L.name}">
        <span class="lt"><span class="lhd"><span class="lname2">${T.head(L.n, L.name)}</span>${idle ? "" : stBadge(pl.state)}${tags}</span>${idle ? "" : `<span class="eff">${pl.text}</span>`}</span></button>
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
        if (!idle && posStep)
          h += `<div class="lay pos" data-state="${posStep.state}"><span class="ln">◆</span><div class="lrow"><span class="lt"><span class="lhd"><span class="lname2">${T.position}</span>${stBadge(posStep.state)}</span><span class="eff">${posStep.text}</span></span></div></div>`;
        if (!idle && res)
          h += `<div class="lay res" data-state="result"><span class="ln">=</span><div class="lrow"><span class="lt"><span class="lhd"><span class="vb ${VCLASS[pg.verdict]}">${pg.verdict}</span></span><span class="eff">${res.text}</span></span></div></div>`;
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
      /* The red path: the nodes and d.ui.edges of propagation's steps whose state is origin or hit (data id "position"
   is the page's "pos"). An edge lights only when its source is already on the path: the position step lists both of
   its edges (holding and liquidation) even when nobody is liquidated, e.g. a USDe depeg shorter than the oracle's
   16 h switch. Steps come in causal order, so a source is lit before the edges leaving it. */
      function pathOf(pg) {
        const nodes = new Set(),
          edges = new Set(),
          id = (k) => (k === "position" ? "pos" : k);
        const hot = pg.steps.filter((x) => HOT(x.state));
        hot.forEach((x) => x.node !== "result" && nodes.add(id(x.node)));
        hot.forEach((x) => {
            (x.edges || []).forEach((e) => {
              const i = EDGES.findIndex((g) => g.from === e.from && id(g.to) === id(e.to) && g.type === e.type);
              if (i >= 0 && nodes.has(id(e.from))) {
                edges.add(i);
                nodes.add(id(e.from));
                nodes.add(id(e.to));
              }
            });
          });
        return { nodes, edges };
      }
      function renderGraph(m, idle) {
        const fl = idle ? { nodes: new Set(), edges: new Set() } : pathOf(m.pg),
          posStep = m.pg.steps.find((x) => x.node === "position"),
          P = m.P;
        FLOW = fl;
        IDLE = !!idle;
        const node = (id) => {
          const n = NODES[id],
            hot = fl.nodes.has(id),
            org = !idle && id === m.pg.origin.node,
            past = org && !!S.past,
            hyp = org && !S.past,
            g = n.evidence && n.evidence.grade;
          const tags =
            (past ? `<span class="tag det">${COPY.past.tag}</span>` : "") +
            (hyp ? '<span class="tag hyp">What-if</span>' : "");
          const sub = GSUB[id];
          return `<button class="node ${g === "D" ? "doc" : ""} ${hot ? "hot" : ""} ${org ? "origin" : ""} ${hyp ? "hyp" : ""}" data-n="${id}" data-g="${id}" style="grid-column:${GCOL[id]}"><span class="nm">${n.label}</span>${tags}<span class="sub">${sub}</span></button>`;
        };
        let h = '<svg id="edges" aria-hidden="true"></svg>';
        LAY.forEach((L) => {
          h += `<div class="band" data-ln="${L.n}"><div class="lname"><b>${L.n}</b>${L.name}</div><div class="grow">${L.nodes.map(node).join("")}</div></div>`;
        });
        const ph = fl.nodes.has("pos");
        h += `<div class="band"><div class="lname">Your position</div><div class="grow"><div class="node pos ${ph ? "hot" : ""}" data-g="pos" style="grid-column:${isLev() ? 3 : 4}"><span class="nm">${isLev() ? "PT posted as collateral" : "PT held outright"}</span><span class="sub">${isLev() ? `Collateral ${money(P.collateral_usd)}, debt ${money(P.debt_usd)}` : money(P.collateral_usd)}</span>${posStep && !idle ? `<span class="sub"><b>${posStep.text}</b></span>` : ""}</div></div></div>`;
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

      /* "What would change the answer": RiskModel.sensitivity's candidates (one assumption replaced at a time), the
   other positions in their own group, the weakest assumption that flips the verdict; then the severity break-even. */
      function sensBlock(m) {
        const T = COPY.sens,
          sv = m.sv,
          f = m.f,
          vw = (v) => T.verdict[v] || v;
        const row = (c) =>
          `<tr class="${sv.weakest && c === sv.weakest ? "best" : ""} ${c.flips ? "flip" : ""}"><td>${c.alternative}</td><td>${vw(c.verdict)}${c.flips ? ` <span class="note">(${T.flips})</span>` : ""}${c.comparison && c.loss_if_stay_usd > 0 ? `<span class="note"> · ${T.loses(money(c.loss_if_stay_usd))}</span>` : ""}</td></tr>`;
        const own = sv.candidates.filter((c) => !c.comparison),
          other = sv.candidates.filter((c) => c.comparison);
        const head = sv.weakest
          ? T.hinges(sv.weakest.alternative, sv.weakest.grade, vw(sv.weakest.verdict))
          : T.robust;
        const sevFlip =
          m.start === null
            ? T.stayAll(sevText(f.max))
            : T.stayBelow(sevText(m.start), m.start < f.min - 1e-9) +
              (m.cap === null ? T.noCap : T.cap(pc(MAXX, 0), sevText(m.cap)));
        return det(
          "d-flip",
          T.title,
          `<p class="sens-head">${head}</p>
      <div class="tw"><table class="sens"><thead><tr>${T.cols.map((h) => `<th>${h}</th>`).join("")}</tr></thead><tbody>${own.map(row).join("")}${
        other.length ? `<tr class="grp"><th colspan="2">${T.others}</th></tr>${other.map(row).join("")}` : ""
      }</tbody></table></div>
      <dl><dt>${T.severity}</dt><dd>${sevFlip}</dd><dt>${T.rule}</dt><dd>${T.ruleText}</dd></dl>`,
        );
      }
      /* Decision card (guide section 5): the badge and the bars from the decision's numbers; the title, sentence,
   reasons, break-even, hinge and rule are RiskModel.decisionText's own texts (every number checked there). */
      function renderDecision(m) {
        const s = m.sev,
          C = m.C,
          t = m.t,
          K = COPY.card,
          hasLoss = m.hasLoss,
          v = m.verdict,
          stuckUsd = s.stuck_fraction * C;
        const vw = v === "STAY" ? K.badge.STAY : v === "EXIT" ? K.badge.EXIT : K.badge.sell(money(s.sell_usd));
        const sub = !hasLoss
          ? K.noLoss
          : v === "REDUCE"
            ? K.ofPosition(pc(m.x, 0))
            : v === "SELL_TO_CAP"
              ? K.allPool + (stuckUsd > 0 ? ` · ${K.stuck(money(stuckUsd))}` : "")
              : "";
        let body = "";
        if (!hasLoss) {
          if (
            (s.type === "not_modelled" && S.fail === "halt") ||
            s.sellable_later < s.sellable_now - 1e-9
          ) {
            const now = s.sellable_now * C,
              later = S.fail === "halt" ? 0 : s.sellable_later * C;
            body += `<div class="bars">${bar(K.sellableToday, [["b-cap", now, money(now)]], money(now), now)}${bar(K.ifPlaysOut, [["b-cap", later, money(later)]], S.fail === "halt" ? K.noneFor(sevText()) : later ? money(later) : K.none, now)}</div>`;
          }
        } else {
          /* "Act" = the recommended sale; on Stay, show selling to the pool limit so the bar shows why not. */
          const xa = m.x || MAXX,
            actCost = m.x
              ? s.sale_cost_usd
              : xa * (RM.slippageAt(xa, CURVE) + m.cy) * C,
            actKept = m.x ? s.loss_kept_usd : (1 - xa) * s.loss_if_stay_usd,
            max = Math.max(s.loss_if_stay_usd, actCost + actKept);
          body += `<div class="bars">${bar(K.doNothing, [["b-loss", s.loss_if_stay_usd, K.tipLoss(money(s.loss_if_stay_usd))]], money(s.loss_if_stay_usd), max)}${bar(
            m.x ? K.act : K.sellPc(pc(xa, 0)),
            [
              ["b-cost", actCost, K.tipCost(money(actCost))],
              ["b-loss", actKept, K.tipKept(money(actKept))],
            ],
            money(actCost + actKept),
            max,
          )}</div>
      <div class="bkey"><span><i class="b-loss"></i>${K.keyLoss}</span><span><i class="b-cost"></i>${K.keyCost}</span></div>`;
          if (v === "SELL_TO_CAP" && stuckUsd > 0)
            body += `<div class="stuck">${K.stuckLine(money(stuckUsd), money(s.loss_kept_usd))}</div>`;
        }
        /* the break-even sentence (on the severity slider and under the exit chart), the propagation rule (the reasons
   say it) and the model / source note are not on the card (user decision, 11 Oct) */
        body += `<ul class="reasons">${t.reasons.map((x) => `<li>${x}</li>`).join("")}</ul>
      <p class="note">${ng(t.hinges_on)}</p>`;
        if (s.L_low !== s.L_high) body += `<p class="note">${K.range(pc(s.L_low, 1), pc(s.L_high, 1))}</p>`;
        body += sensBlock(m);
        $("#decision").innerHTML =
          `<div class="vband ${VCLASS[v]}"><span class="lbl">${S.past ? COPY.past.band(pastOf().label) : K.whatIf} · ${t.title}</span>
    <div class="verdict">${vw}${sub ? `<small>${sub}</small>` : ""}</div><p class="why">${t.headline}</p></div><div class="dbody">${isWallet(S.pos) ? `<p class="note">${COPY.position.wallet(PRE[S.pos].label, BW.block)}</p>` : isReal(S.pos) ? `<p class="note">${COPY.position.notYours(PRE[S.pos].label)}</p>` : ""}${body}</div>`;
      }
      /* "How it spreads": propagation's steps in causal order, each with its grade (null = the manager's input); the last
   one, the result, equals the decision card. */
      function renderSpread(m) {
        const T = COPY.spread,
          steps = m.pg.steps;
        $("#spreadSum").textContent = T.title(steps.length);
        $("#d-spread").open = !!S.open["d-spread"];
        $("#spread").innerHTML = steps
          .map(
            (x) =>
              `<li data-state="${x.state}" data-node="${x.node}">${x.text}</li>`,
          )
          .join("");
      }

      /* Position size (guide 3b, to-do 8): the data at the manager's size. The size field sets spot and
   lev_market_avg (sized presets); a real borrower's size is read on chain, so the field then shows it, read-only. */
      const fullUsd = (v) => Math.round(v).toLocaleString("en-US");
      /* Amount fields (size here, amount invested in the vault view) read and show k / m units (user decision,
   11 Oct): 3,000 = 3k, 3,000,000 = 3m, up to three decimals; the full number is the field's tooltip. */
      const unitAmt = (v) => {
        const a = Math.abs(v),
          t = (x) => String(+x.toFixed(3));
        return a >= 1e6 ? t(v / 1e6) + "m" : a >= 1e3 ? t(v / 1e3) + "k" : t(v);
      };
      const showAmt = (f, v) => {
        f.value = unitAmt(v);
        f.title = fullUsd(v);
      };
      function resize() {
        d = RM.atSize(D0, S.size, S.wallet || null);
        PRE = d.position_presets;
        /* the position select follows the presets: a wallet read on chain adds "wallet" / "wallet_morpho" */
        $("#pos").innerHTML = Object.keys(PRE)
          .map((k) => `<option value="${k}">${PRE[k].label}</option>`)
          .join("");
        if (!PRE[S.pos]) S.pos = "spot";
        $("#pos").value = S.pos;
      }
      const isWallet = (k) => k === "wallet" || k === "wallet_morpho";
      /* Wallet (guide 3b, to-do 10): an address typed or picked from the borrowers of this market (and the wallets the
   backend read with onchain_positions.py --wallet). Its presets come only from the chain; nothing is typed in. */
      function setWallet(text) {
        const a = String(text).trim().toLowerCase();
        S.walletBad = !!a && !/^0x[0-9a-f]{40}$/.test(a);
        S.wallet = a && !S.walletBad ? a : "";
        resize();
        const wk = ["wallet_morpho", "wallet"].find((k) => PRE[k]);
        if (wk) S.pos = wk;
        else if (isWallet(S.pos) || !PRE[S.pos]) S.pos = "spot";
        $("#pos").value = S.pos;
        closeDrawer();
        render();
      }
      function renderSize() {
        const P = PRE[S.pos],
          K = COPY.size,
          f = $("#size"),
          real = isReal(S.pos);
        if (real) showAmt(f, P.collateral_usd);
        else if (f.readOnly) showAmt(f, S.size);
        f.readOnly = real;
        $("#size-mark").innerHTML = real
          ? K.onChain(gr("A"))
          : S.sizeTyped
            ? K.typed
            : K.assumed(gr("D"), ((SI.evidence || {}).default_usd || {}).source || "");
        $("#sizeLine").innerHTML =
          K.line(fullUsd(P.pt_units), "$" + SI.pt_price_usd.toFixed(4), pc(MAXX, 0), money(SI.capacity_usd)) +
          (real ? " " + (isWallet(S.pos) ? K.editHintWallet : K.editHint) : "");
        /* the wallet's state: not an address / not read on chain / read, no PT / read, its presets */
        const W = COPY.wallet,
          wm = $("#walletMsg"),
          found = ["wallet", "wallet_morpho"].filter((k) => PRE[k]);
        wm.innerHTML = S.walletBad
          ? W.invalid
          : !S.wallet
            ? ""
            : d.wallet_read === false
              ? W.notRead(S.wallet)
              : !d.wallet_found
                ? W.noPT(BW.block)
                : W.found(found.map((k) => PRE[k].label).join("; "), BW.block, gr("A"));
        wm.hidden = !wm.innerHTML;
        /* the optional wallet field stays behind "+ Wallet" until asked for or used */
        $("#walletBox").hidden = !(S.walletOpen || S.wallet || S.walletBad);
        $("#walletAdd").hidden = !$("#walletBox").hidden;
        wm.dataset.state = S.walletBad ? "bad" : !S.wallet ? "" : d.wallet_read === false ? "unread" : d.wallet_found ? "found" : "empty";
      }

      /* Time rail (guide 5b and 6, to-do 7): the duration control sits on the chain it drives. Events
   (RiskModel.propagationEvents, about 300 model runs) are cached by position, incident, severity, recovers and cash
   APY, never recomputed on drag. The track and its thumb are static markup: only the marks, labels and list are
   rebuilt, so a drag keeps its pointer capture and the thumb keeps focus. */
      let EVK = null,
        EV = null,
        TLR = null;
      const eventsOf = () => {
        const k = [S.pos, S.size, S.wallet, S.node, S.fail, S.sev, S.recovers, S.alt].join("|");
        if (k !== EVK) {
          EVK = k;
          EV = RM.propagationEvents(d, S.pos, S.node, S.fail, S.sev, S.recovers, S.alt / 100);
          TLR = RM.timeline(d, S.pos, S.node, S.fail, S.sev, S.recovers, S.alt / 100);
        }
        return EV;
      };
      const at = (h) => (uOf(Math.min(H_MAX, Math.max(H_MIN, h))) * 100).toFixed(3) + "%";
      function renderRail(m) {
        const T = COPY.rail,
          ev = eventsOf(),
          rt = RM.recoveryToggle(d, S.node, S.fail),
          p = pastOf(),
          vb = (v) => `<span class="vb ${VCLASS[v]}">${COPY.sens.verdict[v] || v}</span>`;
        document.querySelectorAll("#rail .rq").forEach((x) => (x.textContent = T.q));
        document.querySelectorAll("#rail .rlt").forEach((x) => (x.textContent = T.lasted));
        const di = $("#durIn");
        di.title = di.placeholder = T.durHint;
        /* the typed duration is rewritten only when the field is not being edited */
        if (document.activeElement !== di) di.value = durText(S.hours);
        $("#play").textContent = PLAY.on ? T.pause : T.play;
        $("#play").setAttribute("aria-pressed", PLAY.on);
        $("#rec").innerHTML =
          (rt.show
            ? `<span class="note">${T.after}</span><span class="mode sm" role="group" aria-label="${T.after}"><button data-rec="1" aria-pressed="${S.recovers}">${T.recovers}</button><button data-rec="0" aria-pressed="${!S.recovers}">${T.stays}</button></span>`
            : `<span class="note">${T.recovery}</span>`) +
          `<span class="rwhy" tabindex="0" role="note" title="${ng(rt.reason).replace(/"/g, "&quot;")}" aria-label="${ng(rt.reason).replace(/"/g, "&quot;")}">ⓘ</span>`;
        /* grey reference marks (oracle switch, expiry, the past event's own duration), one red mark per event */
        const refs = [];
        if (TL !== null) refs.push([+TL, T.oracle(durText(+TL))]);
        refs.push([d.time_model.days_to_expiry * 24, T.expiry]);
        if (p && p.hours != null) refs.push([p.hours, T.pastMark(durText(p.hours)), "pm"]);
        $("#rmarks").innerHTML =
          refs
            .map(([h, t, c]) => `<i class="rm ref ${c || ""}" style="left:${at(h)}" data-h="${h}" title="${t}"><span>${t}</span></i>`)
            .join("") +
          ev.events
            .map(
              (e, i) =>
                `<button class="rm ev ${S.hours >= e.hours ? "passed" : ""}" style="left:${at(e.hours)}" data-evh="${i}" data-h="${e.hours}" aria-label="${T.jump(durText(e.hours))}" title="${T.markTip(durText(e.hours), e.verdict_before !== e.verdict_after ? `${COPY.sens.verdict[e.verdict_before] || e.verdict_before} → ${COPY.sens.verdict[e.verdict_after] || e.verdict_after}` : "", e.layers.map((l) => T.layerShort(l.n, T.state[l.from] || l.from, T.state[l.to] || l.to)).join("; "))}"></button>`,
            )
            .join("");
        $("#raxis").innerHTML = T.ticks
          .map(([h, t]) => `<span style="left:${at(h)}">${t}</span>`)
          .join("");
        /* the duration events are on the rail only (its red marks: tooltip and click); no list (user decision, 11 Oct) */
        const th = $("#rthumb");
        th.style.left = at(S.hours);
        th.setAttribute("aria-valuenow", +S.hours.toFixed(2));
        th.setAttribute("aria-valuetext", durText(S.hours));
      }
      /* Timeline chart (guide 5b), in a fold under the rail and on its axis: loss if staying at the model's grid of
   durations (RiskModel.timeline), the background coloured by the answer between the events' exact durations, grey
   marks at the oracle switch and expiry, the rail's duration as a line. Shapes in a 0..1000 x 0..100 box stretched
   to the width; labels are HTML placed by percentage. */
      function renderTimeline() {
        const T = COPY.tl,
          ev = eventsOf(),
          rows = TLR,
          sum = RM.timelineSummary(d, S.pos, rows),
          vb = (v) => `<span class="vb ${VCLASS[v]}">${COPY.sens.verdict[v] || v}</span>`;
        $("#tlSum").textContent = T.title;
        $("#d-tl").open = !!S.open["d-tl"];
        const X = (h) => uOf(Math.min(H_MAX, Math.max(H_MIN, h))) * 1000,
          top = Math.max(...rows.map((r) => r.loss_if_stay_usd)),
          Y = (v) => 96 - (top > 0 ? (v / top) * 88 : 0);
        const cuts = [[H_MIN, ev.start.verdict]].concat(ev.events.map((e) => [e.hours, e.verdict_after]));
        const bands = cuts
          .map(([h, v], i) => {
            const x0 = X(h),
              x1 = i + 1 < cuts.length ? X(cuts[i + 1][0]) : 1000;
            return `<rect class="tb ${VCLASS[v]}" x="${x0}" y="0" width="${x1 - x0}" height="100"/>`;
          })
          .join("");
        const refs = [TL !== null ? +TL : null, d.time_model.days_to_expiry * 24]
          .filter((h) => h !== null)
          .map((h) => `<line class="tref" x1="${X(h)}" x2="${X(h)}" y1="0" y2="100"/>`)
          .join("");
        const line = rows.map((r) => `${X(r.hours).toFixed(1)},${Y(r.loss_if_stay_usd).toFixed(2)}`).join(" ");
        const lines = sum.duration_matters
          ? sum.changes.map((c) => `<li>${T.change(durText(c.to_hours), vb(c.verdict_before), vb(c.verdict_after), c.reason)}</li>`).join("")
          : `<li>${T.flat(sum.why_flat)}</li>`;
        $("#tl").innerHTML = `<ul class="tlsum">${lines}</ul>
   <div class="tlbox"><svg class="tlc" viewBox="0 0 1000 100" preserveAspectRatio="none" role="img" aria-label="${T.aria(rows.length)}">${bands}${refs}<polyline class="tline" points="${line}"/><line class="tnow" x1="${X(S.hours)}" x2="${X(S.hours)}" y1="0" y2="100"/></svg>
   <span class="tly" style="top:${Y(top)}%">${money(top)}</span><span class="tly" style="top:96%">${money(0)}</span></div>
   <div class="raxis">${COPY.rail.ticks.map(([h, t]) => `<span style="left:${at(h)}">${t}</span>`).join("")}</div>
   <p class="note">${T.assume} ${gr("D")}</p>`;
      }
      /* A typed duration: a number (hours), or with a unit: h, d, w ("16", "16h", "3 d", "2 days", "1w"). */
      const durOf = (t) => {
        const m = String(t).trim().replace(",", ".").match(/^(\d*\.?\d+)\s*(h|hr|hrs|hours?|d|days?|w|wk|weeks?)?$/i);
        if (!m) return null;
        const u = (m[2] || "h")[0].toLowerCase();
        return +m[1] * (u === "w" ? 168 : u === "d" ? 24 : 1);
      };
      function setHours(h, live) {
        S.hours = Math.min(H_MAX, Math.max(H_MIN, h));
        live ? frame() : render();
      }
      /* One render per animation frame while dragging. */
      let RAF = 0;
      function frame() {
        if (!RAF)
          RAF = requestAnimationFrame(() => {
            RAF = 0;
            render();
          });
      }
      /* Play: sweep the rail in about 9 s, pause just past each event, stop at the end. Any other input stops it. */
      const PLAY = { on: false, last: 0, hold: 0, raf: 0 },
        PLAY_MS = 9000,
        HOLD_MS = 1400;
      function play() {
        if (PLAY.on) return stopPlay();
        if (uOf(S.hours) >= 1 - 1e-6) S.hours = H_MIN;
        PLAY.on = true;
        PLAY.hold = 0;
        PLAY.last = performance.now();
        render();
        PLAY.raf = requestAnimationFrame(tick);
      }
      function tick(now) {
        if (!PLAY.on) return;
        const dt = now - PLAY.last;
        PLAY.last = now;
        if (PLAY.hold > 0) PLAY.hold -= dt;
        else {
          const u = Math.min(1, uOf(S.hours) + dt / PLAY_MS);
          let h = hOf(u);
          const e = eventsOf().events.find((x) => x.hours > S.hours && x.hours <= h);
          if (e) {
            h = e.hours * 1.0005;
            PLAY.hold = HOLD_MS;
          }
          S.hours = u >= 1 && !e ? H_MAX : Math.min(H_MAX, h);
          if (u >= 1 && !e) return stopPlay();
          render();
        }
        PLAY.raf = requestAnimationFrame(tick);
      }
      function stopPlay() {
        if (!PLAY.on) return;
        PLAY.on = false;
        cancelAnimationFrame(PLAY.raf);
        render();
      }
      /* Flash: a layer whose state a render changed pulses for about 1 s (an outline with prefers-reduced-motion).
   Only when the incident is the same as in the previous render (duration, recovers or severity moved). The rows are
   rebuilt on every render, so a running flash continues through its elapsed time (--flash-at). */
      const FLASH_MS = 1000;
      let PREV = { sig: null, st: {} },
        FLASH = {};
      function trackFlash(pg) {
        const sig = [S.pos, S.size, S.wallet, S.node, S.fail].join("|"),
          now = performance.now(),
          st = {};
        pg.layers.forEach((l) => {
          st[l.n] = l.state;
          if (sig === PREV.sig && PREV.st[l.n] !== l.state) {
            FLASH[l.n] = now;
            setTimeout(applyFlash, FLASH_MS + 20);
          }
        });
        if (sig !== PREV.sig) FLASH = {};
        PREV = { sig, st };
      }
      function applyFlash() {
        const now = performance.now();
        document.querySelectorAll("#chain .flash").forEach((el) => el.classList.remove("flash"));
        Object.keys(FLASH).forEach((n) => {
          const t = now - FLASH[n];
          if (t >= FLASH_MS) return delete FLASH[n];
          document.querySelectorAll(`#chain [data-ln="${n}"]`).forEach((el) => {
            el.classList.add("flash");
            el.style.setProperty("--flash-at", -Math.round(t) + "ms");
          });
        });
      }

      /* Exit chart: RiskModel.actCostCurve, the model's cost of acting at every share sold now (sale on today's value
   with slippage and the yield given up over the incident, loss kept on the rest; minimum = the recommended sale), so
   it moves with the cash yield, the incident and its duration. Money on the y axis. */
      const CH = { W: 392, H: 230, l: 50, r: 10, t: 10, b: 36, ymax: 1 };
      function useCurve(posKey) {
        [CURVE, MAXX] = RM.sizeCurve(d, PRE[posKey].collateral_usd);
      }
      const niceStep = (v) => {
        const e = Math.pow(10, Math.floor(Math.log10(v))),
          f = v / e;
        return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * e;
      };
      const CX = (f) => CH.l + f * (CH.W - CH.l - CH.r),
        CY = (v) => CH.H - CH.b - (Math.min(v, CH.ymax) / CH.ymax) * (CH.H - CH.t - CH.b);
      /* Ported from the explainer's "balance" chart: sale cost, loss on the rest and their total against the share
   sold now (RiskModel.actCostCurve), the lowest total marked; the part Pendle refuses today hatched. */
      function chart(m) {
        const { W, H, l, r, t, b } = CH,
          K = COPY.exit,
          rows = m.ac.rows;
        const top = Math.max(1, m.ac.loss_if_stay_usd, ...rows.map((x) => Math.max(x.sale_cost_usd, x.total_usd))),
          step = niceStep(top / 3);
        CH.ymax = Math.ceil(top / step) * step;
        const line = (k) => rows.map((x) => `${CX(x.fraction).toFixed(1)},${CY(x[k]).toFixed(1)}`).join(" ");
        const best = rows.reduce((a, x) => (x.total_usd < a.total_usd - 1e-9 ? x : a), rows[0]);
        const bx = CX(best.fraction),
          by = CY(best.total_usd),
          lx = Math.min(Math.max(bx, l + 58), W - r - 58);
        let grid = "";
        for (let v = 0; v <= CH.ymax + 1e-9; v += step)
          grid += `<line class="ax" x1="${l}" y1="${CY(v)}" x2="${W - r}" y2="${CY(v)}"/><text x="${l - 6}" y="${CY(v) + 4}" text-anchor="end">${money(v)}</text>`;
        const xt = [...new Set([0, 0.25, 0.5, 0.75, 1].filter((f) => Math.abs(f - MAXX) > 0.08).concat(MAXX < 1 - 1e-9 ? [MAXX] : []))];
        return `<svg class="chart" id="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${K.aria(pc(MAXX, 0))}">
   ${MAXX < 1 - 1e-9 ? `<rect class="no" x="${CX(MAXX)}" y="${t}" width="${CX(1) - CX(MAXX)}" height="${H - t - b}"/><text class="no-lbl" x="${CX((1 + MAXX) / 2)}" y="${t + 14}" text-anchor="middle">${K.refuses[0]}</text><text class="no-lbl" x="${CX((1 + MAXX) / 2)}" y="${t + 28}" text-anchor="middle">${K.refuses[1]}</text>` : ""}
   ${grid}
   ${xt.map((f) => `<text x="${CX(f)}" y="${H - b + 14}" text-anchor="${f === 1 ? "end" : f === 0 ? "start" : "middle"}">${pc(f, 0)}</text>`).join("")}
   <text x="${l + (W - l - r) / 2}" y="${H - 5}" text-anchor="middle">${K.xAxis}</text>
   <polyline class="ln-kept" points="${line("loss_kept_usd")}"/>
   <polyline class="ln-sale" points="${line("sale_cost_usd")}"/>
   <polyline class="ln-total" points="${line("total_usd")}"/>
   <line class="best-guide" x1="${bx}" x2="${bx}" y1="${t}" y2="${H - b}"/><circle class="best-dot" cx="${bx}" cy="${by}" r="5.5"/>
   <text class="best-lbl" x="${lx}" y="${Math.max(by - 10, t + 40)}" text-anchor="middle">${K.lowest(money(best.total_usd), pc(best.fraction, 0))}</text>
   <line class="cross" id="cross" x1="0" x2="0" y1="${t}" y2="${H - b}" visibility="hidden"/></svg>`;
      }
      /* The chart's caption (the explainer's sentence): what selling the recommended share costs against staying. */
      function exitSay(m) {
        const r = m.sev,
          K = COPY.exit,
          V = m.ac.value_usd;
        if (r.verdict === "STAY")
          return r.loss_if_stay_usd <= 0 ? K.sayNoLoss : K.sayStay(money(r.loss_if_stay_usd));
        return (
          K.saySell(pc(r.sell_fraction, 0), money(r.sell_fraction * V), money(r.sale_cost_usd), money(r.loss_kept_usd), money(r.total_if_act_usd), money(r.loss_if_stay_usd), money(r.avoided_usd)) +
          (r.verdict === "SELL_TO_CAP" ? " " + K.sayStuck(pc(1 - r.sell_fraction, 0)) : "")
        );
      }
      /* What the cash yield does here (user report, 11 Oct: typing it seemed to change nothing). The yield given up is
   the model's r.carry, over the incident's duration (at most until expiry): tiny for a short incident, so the chart
   barely moves; this line shows the amount so the input is never silent. */
      function carryLine(m) {
        const K = COPY.exit,
          apy = d.time_model.implied_apy;
        if (S.alt / 100 >= apy - 1e-12) return K.carryNone(pc(apy, 2));
        const c = m.cy,
          cs = c >= 0.001 ? pc(c, 2) : c >= 1e-5 ? pc(c, 4) : pc(c, 6);
        return K.carry(pc(S.alt / 100, 2), pc(apy, 2), durText(Math.min(S.hours, d.time_model.days_to_expiry * 24)), cs, money(c * m.ac.value_usd));
      }
      /* Break-even severities under the chart (the same m.be as step 2's zones). */
      function exitBe(m) {
        const K = COPY.exit,
          f = m.f,
          v = (x) => (x === null ? K.beNever : (x <= f.min + 1e-9 ? "≤ " : "") + sevText(x));
        return `<span>${K.be}</span><span>${K.beStart} <b>${v(m.be.start)}</b></span><span>${K.beCap} <b>${v(m.be.cap)}</b></span><span class="note">${K.beRange(sevText(f.min), sevText(f.max))}</span>`;
      }
      function renderExit(m, idle) {
        const C = m.C,
          s = m.sev,
          cap = s.sellable_now * C,
          last = RM.slippageAt(s.sellable_now, CURVE),
          isDrain = !idle && s.type === "exit_only";
        AC = m.ac;
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
        /* the model's rows (actCostCurve) every 10%, at the pool limit and at the recommended sale */
        const V = m.ac.value_usd,
          tens = m.ac.rows.filter(
            (x) =>
              Math.abs(x.fraction * 10 - Math.round(x.fraction * 10)) < 1e-9 ||
              Math.abs(x.fraction - m.ac.cap) < 1e-9 ||
              Math.abs(x.fraction - m.x) < 1e-9,
          );
        const row = (x) =>
          `<tr class="${m.hasLoss && Math.abs(x.fraction - m.x) < 1e-9 ? "best" : ""}"><td>${x.fraction ? pc(x.fraction, 0) + " · " + money(x.fraction * V) : "Stay"}</td><td>${x.fraction ? pc(x.slippage, 2) : "–"}</td><td>${money(x.sale_cost_usd)}</td><td>${money(x.loss_kept_usd)}</td><td>${money(x.total_usd)}</td></tr>`;
        /* Refused sizes are quoted as shares of the quotes' notional (N0): convert through USD and keep those
   within this position. */
        const refused = [
          ...(d.evidence.max_exit_fraction.source || "").matchAll(
            /([\d.]+) refused \((\w+)/g,
          ),
        ]
          .filter((r) => +r[1] * N0 <= C * (1 + 1e-9))
          .map(
            (r) =>
              `<tr class="ref"><td>${pc((+r[1] * N0) / C, 0)} · ${money(+r[1] * N0)}</td><td colspan="4">Refused: ${r[2]}</td></tr>`,
          )
          .join("");
        $("#exit").innerHTML =
          `<div class="phead"><h2>Can you get out?</h2><span class="note">Real Pendle quotes, ${DAY}</span></div>
   <dl><dt>Today</dt><dd>Up to ${money(cap)} (${pc(s.sellable_now, 0)}), costing ${pc(last, 2)} in slippage.</dd>${later ? `<dt>If this plays out</dt><dd>${later}</dd>` : ""}</dl>
   <div class="cverdict"><span class="vb ${VCLASS[s.verdict]}">${s.verdict}</span><span>${exitSay(m)}</span></div>
   <p class="note ccarry" id="carryLine">${carryLine(m)}</p>
   <div class="ckey"><span><i class="sw-sale"></i>${COPY.exit.keySale}</span><span><i class="sw-kept"></i>${COPY.exit.keyKept}</span><span><i class="sw-total"></i>${COPY.exit.keyTotal}</span>${MAXX < 1 - 1e-9 ? `<span><i class="sw-no"></i>${COPY.exit.keyNo}</span>` : ""}</div>
   <div class="cwrap" id="cwrap">${chart(m)}<div class="tip" id="tip" hidden></div></div>
   <p class="cbe">${exitBe(m)}</p>
   ${det(
     "d-sizes",
     "All sale sizes",
     `<div class="tw"><table><thead><tr><th>Sell</th><th>Slippage</th><th>Sale cost</th><th>Loss kept</th><th>Total</th></tr></thead><tbody>${tens.map(row).join("")}${refused}</tbody></table></div>
     <p class="note">${m.hasLoss ? "The highlighted row has the lowest total. " : ""}${COPY.exit.interp} ${COPY.rail.carryNote(pc(m.cy, 3), durText(S.hours))} Counts only the Pendle swap route: no limit orders, OTC, or holding to expiry.</p>
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
        /* the slider's own track carries the break-even zones (user decision, 11 Oct): stay / sell part / sell to the
   pool limit, split at m.be on the slider's scale; only the split points are set here (geometry), the colours are
   tokens in demo.css. No loss modelled: a plain track. */
        const sv = $("#sev");
        if (be.start !== null || m.hasLoss) {
          /* a split at or beyond an end of the scale goes past the track (-1 / 2), so the half thumb at that end does
   not keep the other zone's colour */
          const w = (v) => {
            const x = v === null ? 2 : isLog(f) ? sevPos(f, v) / LOGR : (v - f.min) / (f.max - f.min);
            return x <= 1e-9 ? -1 : x >= 1 - 1e-9 ? 2 : x;
          };
          sv.classList.add("zoned");
          sv.style.setProperty("--za", w(be.start).toFixed(4));
          sv.style.setProperty("--zb", w(be.cap).toFixed(4));
          sv.title = zt.trim();
        } else {
          sv.classList.remove("zoned");
          sv.title = "";
        }
      }
      function syncSteps() {
        const past = S.mode === "past",
          M = COPY.mode;
        $("#simLbl").textContent = M.label;
        document.querySelectorAll("#steps .smode [data-mode]").forEach((b) => {
          b.textContent = M[b.dataset.mode];
          b.setAttribute("aria-pressed", b.dataset.mode === S.mode);
        });
        $("#replay").closest(".pastwrap").hidden = !past;
        $("#incBtn").disabled = $("#sev").disabled = past;
        /* a past event fixes steps 1 and 2: shown as text, not as controls (user decision, 11 Oct) */
        $("#casc").hidden = $("#sevRow").hidden = past;
        $("#ro1").hidden = $("#ro2").hidden = !past;
        const inc = COPY.steps.inc(NODES[S.node].label, FAIL[S.fail].label);
        $("#ro1").textContent = inc;
        $("#ro2").textContent = sevText();
        $("#incTxt").textContent = inc;
        $("#steps").dataset.sim = S.mode;
        $("#q1").textContent = COPY.steps.q1;
        $("#q2").textContent = COPY.steps.q2;
        $("#pos").value = S.pos;
        closeInc();
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
        trackFlash(m.pg);
        renderSize();
        renderSteps(m);
        renderRail(m);
        renderTimeline();
        renderChain(m);
        applyFlash();
        renderSpread(m);
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
              `${FAIL[p.fail].phrase(sevText(p.sev))} at ${NODES[p.node].label}${p.hours != null ? COPY.past.lasting(durText(p.hours), !!p.recovers) : ""}`,
              src(p.evidence),
            )
          : "";
        $("#replay").value = S.past || S.lastPast || "";
      }
      /* Past: load one of the past events (the last one chosen, else the first screen's); its node, failure,
   severity, duration and recovers preset the controls, steps 1 and 2 read-only. Manual: keep the current values as
   the starting point of a what-if, every control editable. */
      function loadPast(key) {
        const p = PAST.find((x) => x.key === key);
        if (!p) return setMode("manual");
        closeDrawer();
        S.mode = "past";
        S.past = S.lastPast = p.key;
        /* the event presets the duration and the recovers toggle too (guide 5b); without a stated duration: the
   default duration, stays */
        S.hours = p.hours != null ? p.hours : DEF_H;
        S.recovers = p.hours != null && !!p.recovers;
        setNode(p.node, p.fail, p.sev);
      }
      function setMode(m) {
        if (m === "past" && PAST.length) return loadPast(S.lastPast || PAST[0].key);
        S.mode = "manual";
        S.past = null;
        apply();
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
                    `${money(SI.capacity_usd)} · ${src(SI.evidence && SI.evidence.capacity_usd)}`,
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
          ["Evidence", `<span class="mono">${e.evidence}</span>`],
        ]);
      }

      document.addEventListener("click", (ev) => {
        const t = ev.target.closest("button");
        if (!t) return;
        if (t.id !== "play" && !t.closest(".drawer")) stopPlay();
        if (t.id === "play") play();
        else if (t.dataset.evh) {
          /* an event: move the thumb just past it */
          const e = eventsOf().events[+t.dataset.evh];
          if (e) setHours(e.hours * 1.0005);
        } else if (t.dataset.rec) {
          S.recovers = t.dataset.rec === "1";
          render();
        } else if (t.dataset.drawer) nodeEvidence(t.dataset.drawer);
        else if (t.dataset.mode) setMode(t.dataset.mode);
        else if (t.id === "walletAdd") {
          S.walletOpen = true;
          render();
          $("#wallet").focus();
        }
        else if (t.dataset.layer) {
          /* a past event fixes the incident: a layer then only opens its evidence */
          const n = +t.dataset.layer,
            k = MAIN[n] || LAY[n - 1].nodes[0];
          if (S.mode === "past") nodeEvidence(k);
          else setNode(k);
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
          const id = t.dataset.n;
          if (S.mode !== "past") setNode(id);
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
        stopPlay();
        if (t.id === "alt") {
          /* the cash yield, step 2's second slider (user decision, 11 Oct): live, like the explainer's; a manager's
   assumption, so it stays enabled for a past event */
          S.alt = +t.value;
          $("#altOut").textContent = S.alt.toFixed(2) + "%";
          frame();
        }
        if (t.id === "sev" && S.mode !== "past") {
          const f = FAIL[S.fail];
          S.sev = isLog(f) ? posSev(f, +t.value) : +t.value;
          render();
        }
      });
      document.addEventListener("change", (ev) => {
        const t = ev.target,
          num = (lo, hi, dv) => {
            const v = parseFloat(String(t.value).trim().replace(",", "."));
            return isFinite(v) ? Math.min(hi, Math.max(lo, v)) : dv;
          };
        stopPlay();
        if (t.id === "pos") {
          S.pos = t.value;
          closeDrawer();
          render();
        }
        if (t.id === "replay") loadPast(t.value);
        if (t.id === "alt") {
          S.alt = +t.value;
          $("#altOut").textContent = S.alt.toFixed(2) + "%";
          render();
        }
        if (t.id === "wallet") setWallet(t.value);
        if (t.id === "durIn") {
          const h = durOf(t.value);
          if (h !== null && h > 0) setHours(h);
          t.value = durText(S.hours);
        }
        if (t.id === "size" && !t.readOnly) {
          /* "3,000,000", "3m", "3.5M", "250k" are read and shown back as k / m; anything else restores the last size */
          const m = String(t.value).trim().replace(/[\s,_]/g, "").match(/^(\d*\.?\d+)([kKmM]?)$/),
            v = m ? +m[1] * { "": 1, k: 1e3, K: 1e3, m: 1e6, M: 1e6 }[m[2]] : NaN;
          if (v > 0 && isFinite(v)) {
            S.size = v;
            S.sizeTyped = true;
            resize();
          }
          showAmt(t, S.size);
          render();
        }
      });
      document.addEventListener(
        "toggle",
        (ev) => {
          const t = ev.target;
          if (t.tagName === "DETAILS" && t.id && !t.closest("#view-vault"))
            S.open[t.id] = t.open;
        },
        true,
      );
      /* Step 1, "Select incident" (user decision, 11 Oct): one menu instead of the dependency and failure selects. The
   first level lists the dependencies by layer; a dependency with several failures opens them in a second level to
   its right (on hover, click, or the right arrow); one with a single failure is chosen directly. A choice sets both
   (setNode). Keys: up / down, right opens a second level, left goes back, Enter chooses, Escape closes. */
      function renderIncMenu() {
        const it = (k) => {
          const fs = fails(k),
            cur = k === S.node,
            sub = fs.length > 1;
          return `<div class="citem ${cur ? "cur" : ""}" role="menuitem" tabindex="-1" data-cn="${k}"${sub ? ' aria-haspopup="menu" aria-expanded="false"' : ""}><span>${NODES[k].label}</span>${sub ? '<span class="carrow">▸</span>' : ""}${
            sub
              ? `<div class="csub" role="menu">${fs
                  .map((f) => `<div class="citem ${cur && f === S.fail ? "cur" : ""}" role="menuitemradio" aria-checked="${cur && f === S.fail}" tabindex="-1" data-cn="${k}" data-cf="${f}">${FAIL[f].label}</div>`)
                  .join("")}</div>`
              : ""
          }</div>`;
        };
        $("#incMenu").innerHTML = LAY.map((L) => {
          const ks = L.nodes.filter((k) => fails(k).length);
          return ks.length ? `<div class="cgrp">${COPY.layers.head(L.n, L.name)}</div>${ks.map(it).join("")}` : "";
        }).join("");
      }
      function openInc() {
        renderIncMenu();
        $("#incMenu").hidden = false;
        $("#incBtn").setAttribute("aria-expanded", "true");
        const c = $("#incMenu .citem.cur") || $("#incMenu .citem");
        if (c) c.focus();
      }
      function closeInc() {
        const m = $("#incMenu");
        if (!m || m.hidden) return;
        m.hidden = true;
        $("#incBtn").setAttribute("aria-expanded", "false");
      }
      const openSub = (item, on) => {
        document.querySelectorAll("#incMenu > .citem.open").forEach((x) => x !== item && (x.classList.remove("open"), x.setAttribute("aria-expanded", "false")));
        if (item && item.querySelector(".csub")) {
          item.classList.toggle("open", on);
          item.setAttribute("aria-expanded", String(on));
        }
      };
      function pickInc(k, f) {
        closeInc();
        $("#incBtn").focus();
        if (S.mode !== "past") setNode(k, f);
      }
      $("#incBtn").addEventListener("click", () => ($("#incMenu").hidden ? openInc() : closeInc()));
      $("#incBtn").addEventListener("keydown", (ev) => {
        if (ev.key === "ArrowDown" || ev.key === "Enter" || ev.key === " ") {
          ev.preventDefault();
          openInc();
        }
      });
      $("#incMenu").addEventListener("mouseover", (ev) => {
        const top = ev.target.closest("#incMenu > .citem");
        if (top) openSub(top, true);
      });
      $("#incMenu").addEventListener("click", (ev) => {
        const t = ev.target.closest(".citem");
        if (!t) return;
        if (t.dataset.cf) return pickInc(t.dataset.cn, t.dataset.cf);
        if (t.querySelector(".csub")) return openSub(t, !t.classList.contains("open"));
        pickInc(t.dataset.cn, fails(t.dataset.cn)[0]);
      });
      $("#incMenu").addEventListener("keydown", (ev) => {
        const t = ev.target.closest(".citem");
        if (!t) return;
        const inSub = !!t.dataset.cf,
          list = inSub ? [...t.parentElement.children] : [...document.querySelectorAll("#incMenu > .citem")],
          i = list.indexOf(t);
        if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
          ev.preventDefault();
          const n = list[(i + (ev.key === "ArrowDown" ? 1 : list.length - 1)) % list.length];
          if (!inSub) openSub(n, false);
          n.focus();
        } else if (ev.key === "ArrowRight" && !inSub && t.querySelector(".csub")) {
          ev.preventDefault();
          openSub(t, true);
          (t.querySelector(".csub .citem.cur") || t.querySelector(".csub .citem")).focus();
        } else if (ev.key === "ArrowLeft" && inSub) {
          ev.preventDefault();
          const top = t.closest("#incMenu > .citem");
          openSub(top, false);
          top.focus();
        } else if (ev.key === "Enter" || ev.key === " ") {
          ev.preventDefault();
          ev.stopPropagation();
          t.click();
        } else if (ev.key === "Escape") {
          ev.preventDefault();
          closeInc();
          $("#incBtn").focus();
        }
      });
      document.addEventListener("pointerdown", (ev) => {
        if (!ev.target.closest("#casc")) closeInc();
      });

      /* Time rail: drag (pointer capture; a click on the track jumps there) and keys (arrows 1% of the rail,
   PageUp / PageDown 10%, Home / End). */
      const RTRACK = $("#rtrack");
      let DRAG = false;
      const dragTo = (ev) => {
        const R = RTRACK.getBoundingClientRect();
        setHours(hOf(Math.min(1, Math.max(0, (ev.clientX - R.left) / R.width))), true);
      };
      RTRACK.addEventListener("pointerdown", (ev) => {
        if (ev.target.closest(".ev")) return;
        stopPlay();
        DRAG = true;
        RTRACK.setPointerCapture(ev.pointerId);
        $("#rthumb").focus();
        dragTo(ev);
      });
      RTRACK.addEventListener("pointermove", (ev) => DRAG && dragTo(ev));
      const endDrag = () => {
        if (!DRAG) return;
        DRAG = false;
        frame();
      };
      RTRACK.addEventListener("pointerup", endDrag);
      RTRACK.addEventListener("pointercancel", endDrag);
      $("#rthumb").addEventListener("keydown", (ev) => {
        const k = ev.key,
          step = { ArrowRight: 0.01, ArrowUp: 0.01, ArrowLeft: -0.01, ArrowDown: -0.01, PageUp: 0.1, PageDown: -0.1 }[k];
        const u = k === "Home" ? 0 : k === "End" ? 1 : step != null ? uOf(S.hours) + step : null;
        if (u === null) return;
        ev.preventDefault();
        stopPlay();
        setHours(hOf(Math.min(1, Math.max(0, u))));
      });

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
        const ar = AC && AC.rows.find((x) => Math.abs(x.fraction - f) < 1e-9);
        tip.innerHTML =
          `<b>Sell ${pc(f, 0)} · ${money(f * PRE[S.pos].collateral_usd)}</b>` +
          (ar ? COPY.exit.tip(money(ar.sale_cost_usd), money(ar.loss_kept_usd), money(ar.total_usd)) + "<br>" : "") +
          `Slippage today: ${now}${lt ? "<br>If this plays out: " + lt : ""}`;
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
      $("#pos-lbl").textContent = COPY.position.holding;
      $("#wallet-lbl").textContent = COPY.wallet.label;
      $("#walletAdd").textContent = COPY.wallet.add;
      $("#wallet").placeholder = COPY.wallet.placeholder;
      $("#walletList").innerHTML = (BW.wallets || [])
        .map((w) => `<option value="${w.address}">${COPY.wallet.optWallet}</option>`)
        .concat(
          (BW.list || []).map(
            (b) => `<option value="${b.address}">${COPY.wallet.optBorrower(money(b.collateral_pt * D0.position.pt_price_usd), pc(b.ltv))}</option>`,
          ),
        )
        .join("");
      $("#replay").innerHTML = PAST.map((p) => `<option value="${p.key}">${p.label}</option>`).join("");
      $("#pastInfo").setAttribute("aria-label", COPY.past.info);
      if (!PAST.length) document.querySelector("#steps .smode").hidden = true;
      $("#size-lbl").innerHTML = COPY.size.label;
      $("#alt-lbl").innerHTML = COPY.size.altLabel(gr("D"));
      /* the slider snaps to 0.01%; S.alt starts at the PT's own implied APY (nothing given up) */
      $("#alt").value = S.alt.toFixed(2);
      $("#altOut").textContent = S.alt.toFixed(2) + "%";
      showAmt($("#size"), S.size);
      resize();
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
