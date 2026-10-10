/* Risk model for the dashboard: a line-by-line port of the Python backend, so sliders can move freely
   and still give the backend's numbers. Checked against Python by check_js_port.py (run it after any change).

   Ports:
     lif, positionLoss          loss_model.py  (lif, _one_branch, position_loss)
     oracleFalls                oracle_types.py (oracle_falls; meta-oracle threshold + timelock)
     slippageAt, decide         decision_core.py
     breakEven                  incidents.py (exact break-even from the exit curve, no p grid)
     sizeCurve, exitLaterAt, borrowerPreset, walletPresets, atSize, decisionText, propagation   frontend_contract.py (position size: the manager's input)

   Shapes (same field names as the Python dataclasses):
     scenario = {layer: 2|3, shock: 0..1, permanent: 0..1, hours: number|null}
     position = {collateral_usd, debt_usd, lltv, can_hold, oracle_tracks_underlying, oracle_tracks_market,
                 collateral_oracle_usd}
                (oracle flags: true / false / null = unknown -> both branches; collateral_usd = market value,
                 collateral_oracle_usd = value at the lending oracle's price, liquidation check only, default = market)
     curve    = [[fraction_sold, avg_slippage], ...]   (dashboard.json exit_curve as pairs)
   Load in a page with <script src="risk_model.js"></script> (global RiskModel) or require() in node. */
(function (root) {
  const LIQUIDATION_CURSOR = 0.3, MAX_LIF = 1.15;

  function lif(lltv) {
    return Math.min(MAX_LIF, 1 / (1 - LIQUIDATION_CURSOR * (1 - lltv)));
  }

  function oneBranch(s, p, oracleFalls) {
    const C = p.collateral_usd, D = p.debt_usd, equity = C - D;   // C = market value: what the PT is worth and sells for
    const Co = p.collateral_oracle_usd === null || p.collateral_oracle_usd === undefined ? C : p.collateral_oracle_usd;
    const oracleDrop = oracleFalls ? s.shock : 0;
    const endValue = 1 - s.shock * s.permanent;   // value at the end, relative to now
    const soldValue = 1 - s.shock;                // value if forced to sell at the worst point
    const out = {oracle_falls: oracleFalls, liquidated: false, bad_debt_usd: 0, liquidation_drop_threshold: null};
    if (D <= 0) {                                 // unlevered
      const v = p.can_hold ? endValue : soldValue, loss = C * (1 - v);
      return Object.assign(out, {loss_usd: loss, loss_of_equity: C ? loss / C : 0});
    }
    const threshold = 1 - D / (Co * p.lltv);      // oracle drop that makes the position unhealthy
    out.liquidation_drop_threshold = threshold;
    let loss;
    if (oracleDrop > threshold) {
      const f = lif(p.lltv);
      const seized = oracleDrop < 1 ? D * f / (Co * (1 - oracleDrop)) : Infinity;
      out.liquidated = true;
      out.lif = f;
      if (seized >= 1) {                          // collateral exhausted: all equity lost, rest is bad debt
        out.bad_debt_usd = D - Co * (1 - oracleDrop) / f;
        loss = equity;
      } else {
        loss = equity - C * (1 - seized) * endValue;
      }
    } else {
      const v = p.can_hold ? endValue : soldValue;
      loss = Math.min(equity, C * (1 - v));       // limited liability
      if (C * v < D) out.bad_debt_usd = D - C * v;
    }
    return Object.assign(out, {loss_usd: loss, loss_of_equity: equity ? loss / equity : 0});
  }

  /* Loss of the position's equity. Unknown oracle behaviour (null) -> both branches, as a range. */
  function positionLoss(s, p) {
    const flag = s.layer === 2 ? p.oracle_tracks_underlying : p.oracle_tracks_market;
    let branches;
    if (p.debt_usd <= 0) branches = [oneBranch(s, p, false)];
    else if (flag === null || flag === undefined) branches = [oneBranch(s, p, true), oneBranch(s, p, false)];
    else branches = [oneBranch(s, p, flag)];
    const L = branches.map(b => b.loss_of_equity);
    return {L_low: Math.min(...L), L_high: Math.max(...L),
            oracle_known: (flag !== null && flag !== undefined) || p.debt_usd <= 0, branches};
  }

  /* Does the market's oracle fall with this shock? cls = dashboard.json "oracle" (oracle_types.classify). */
  function oracleFalls(cls, layer, shock, hours, token = null) {
    const key = layer === 2 ? 'tracks_underlying' : 'tracks_market';
    const sees = suffix => { const a = cls['underlying_assets' + suffix];
      return !(token && a && a.length && !a.includes(token.toLowerCase())); };
    let now = cls[key];
    if (layer === 2 && now === true && !sees('')) now = false;
    if (cls.kind !== 'meta_oracle_timelock' || now === true) return now;
    let after = cls[key + '_after_switch'];
    if (layer === 2 && after === true && !sees('_after_switch')) after = false;
    const lasts = hours === null || hours === undefined ||
      (cls.challenge_timelock_s != null && hours * 3600 >= cls.challenge_timelock_s);
    const big = cls.deviation_threshold != null && shock > cls.deviation_threshold;
    if (after === true && lasts && big) return true;
    if (after === null || after === undefined) return null;
    return now;
  }

  function slippageAt(x, curve) {
    if (x <= curve[0][0]) return curve[0][1];
    for (let i = 1; i < curve.length; i++) {
      const [x0, s0] = curve[i - 1], [x1, s1] = curve[i];
      if (x <= x1) return s0 + (s1 - s0) * (x - x0) / (x1 - x0);
    }
    return curve[curve.length - 1][1];
  }

  /* Exit fraction x minimising x*(slippage(x)+carry) + (1-x)*p*L, never beyond the largest quote. */
  function decide(p, L, curve, carry = 0, steps = 100) {
    const el = p * L, maxX = Math.max(...curve.map(c => c[0]));
    let bestX = 0, bestCost = el;
    const xs = [];
    for (let i = 0; i <= steps && i / steps <= maxX + 1e-12; i++) xs.push(i / steps);
    if (Math.abs(xs[xs.length - 1] - maxX) > 1e-12) xs.push(maxX);   // the cap itself, when it is not on the grid
    for (const x of xs) {
      const cost = (x > 0 ? x * (slippageAt(x, curve) + carry) : 0) + (1 - x) * el;
      if (cost < bestCost - 1e-12) { bestX = x; bestCost = cost; }
    }
    const capped = maxX < 1 - 1e-12, atCap = capped && bestX >= maxX - 1e-12;
    return {exitFraction: bestX, expectedCost: bestCost, stayCost: el, stuckFraction: atCap ? 1 - bestX : 0, atCap};
  }

  /* Exact break-even probabilities (incidents.break_even without gas): scale = collateral / equity. */
  function breakEven(curve, L, scale = 1, carry = 0) {
    const pts = curve.slice().sort((a, b) => a[0] - b[0]);
    const [x1, s1] = pts[0], [cap, sCap] = pts[pts.length - 1];
    const [xp, sp] = pts.length > 1 ? pts[pts.length - 2] : [0, 0];
    const slope = cap > xp ? (sCap - sp) / (cap - xp) : 0;
    const f = c => (L > 0 ? (c + carry) * scale / L : null);
    return {p_start: f(s1), p_exit_sellable: f(sCap), p_sell_to_cap: f(sCap + cap * slope), sellable_fraction: cap};
  }

  /* ---- position size: the manager's input (ports of frontend_contract.size_curve / exit_later_at /
     borrower_preset / at_size). Quotes by USD size: d.exit_curve_usd = [{usd, loss, gas_usd}]. */
  function sizeCurve(d, valueUsd) {
    if (!d.exit_curve_usd || !d.exit_curve_usd.length)
      return [d.exit_curve.map(x => [x.fraction, x.loss]), d.max_exit_fraction];
    const pts = d.exit_curve_usd.map(x => [x.usd, x.loss]);
    const out = valueUsd <= pts[pts.length - 1][0]
      ? pts.filter(([u]) => u < valueUsd).map(([u, s]) => [u / valueUsd, s]).concat([[1, slippageAt(valueUsd, pts)]])
      : pts.map(([u, s]) => [u / valueUsd, s]);
    return [out, out[out.length - 1][0]];
  }
  function gasAt(d, usd) {
    const g = (d.exit_curve_usd || []).filter(x => x.gas_usd !== null && x.gas_usd !== undefined).map(x => [x.usd, x.gas_usd]);
    return g.length ? slippageAt(usd, g) : 0;
  }
  /* Exit now vs after liquidators sold the PT seized at oracle drop `drop`, for a position worth valueUsd. */
  function exitLaterAt(d, valueUsd, drop) {
    const rows = (d.borrowers && d.borrowers.liquidation_curve) || [];
    if (!rows.length || !d.exit_curve_usd || !d.exit_curve_usd.length) return null;
    let r = rows[0];
    for (const x of rows) if (Math.abs(x.oracle_drop - drop) < Math.abs(r.oracle_drop - drop)) r = x;
    const pts = d.exit_curve_usd.map(x => [x.usd, x.loss]), cap = pts[pts.length - 1][0];
    const cum = u => (u > 0 ? u * slippageAt(u, pts) : 0);
    const y = r.pt_seized * d.position.pt_price_usd, now = Math.min(valueUsd, cap);
    const out = {oracle_drop: r.oracle_drop, pt_seized: r.pt_seized, seized_usd: y, seized_in_position_units: y / valueUsd,
                 sellable_now: now / valueUsd, avg_cost_now: (cum(now) + gasAt(d, now)) / now};
    if (y >= cap) return Object.assign(out, {sellable_later: 0, avg_cost_later: null, market_impact_of_liquidations: null,
                                             note: "liquidations alone use up the pool's quoted capacity"});
    const z = Math.min(valueUsd, cap - y), h = Math.min(0.005 * valueUsd, cap - y);
    return Object.assign(out, {sellable_later: z / valueUsd, avg_cost_later: (cum(y + z) - cum(y) + gasAt(d, z)) / z,
                               market_impact_of_liquidations: y > 0 ? (cum(y + h) - cum(y)) / h : 0, note: null});
  }
  function sizedPreset(p, sizeUsd, si) {
    const units = sizeUsd / si.pt_price_usd, co = units * (si.oracle_price_usd || si.pt_price_usd);
    return Object.assign({}, p, {collateral_usd: sizeUsd, pt_units: units, collateral_oracle_usd: co, debt_usd: p.ltv * co});
  }
  /* A real Morpho borrower of this market (d.borrowers.list) at its real size; null if not found. */
  function borrowerPreset(d, address, label = null) {
    const b = ((d.borrowers && d.borrowers.list) || []).find(x => x.address === String(address).toLowerCase());
    if (!b) return null;
    const px = d.position.pt_price_usd;
    return {label: label || `Morpho borrower ${b.address.slice(0, 10)}... (real position)`, can_hold: true, sized: false,
            address: b.address, pt_units: b.collateral_pt, collateral_usd: b.collateral_pt * px,
            collateral_oracle_usd: b.collateral_usdc, debt_usd: b.borrow_usdc, ltv: b.ltv, lltv: d.borrowers.lltv,
            evidence: {grade: 'A', source: `eth_call @ block ${d.borrowers.block}: collateral (PT) and debt; value = PT units x Pendle PT price ${px.toFixed(5)}`}};
  }
  /* Presets of a wallet read on chain: "wallet" = PT held in the wallet, "wallet_morpho" = its position in this Morpho
     market; from d.borrowers.wallets (onchain_positions.py --wallet), else d.borrowers.list. Returns [read, presets]. */
  function walletPresets(d, address) {
    const b = d.borrowers || {}, a = String(address).toLowerCase();
    const w = (b.wallets || []).find(x => x.address === a), out = {};
    if (!w) { const m = borrowerPreset(d, a); return [m !== null, m ? {wallet_morpho: m} : {}]; }
    const px = d.position.pt_price_usd, opx = b.oracle_price;
    const src = `eth_call @ block ${b.block} (onchain_positions.py --wallet)`;
    if (w.pt_in_wallet > 0)
      out.wallet = {label: `Wallet ${a.slice(0, 10)}...: PT held (real position)`, can_hold: true, sized: false,
                    address: a, pt_units: w.pt_in_wallet, collateral_usd: w.pt_in_wallet * px,
                    collateral_oracle_usd: w.pt_in_wallet * opx, debt_usd: 0, ltv: 0, lltv: b.lltv,
                    evidence: {grade: 'A', source: `PT balanceOf: ${src}; value = PT units x Pendle PT price ${px.toFixed(5)}`}};
    if (w.collateral_pt > 0 || w.borrow_usdc > 0)
      out.wallet_morpho = Object.assign({}, borrowerPreset(d, a) || {
        can_hold: true, sized: false, address: a, pt_units: w.collateral_pt, collateral_usd: w.collateral_pt * px,
        collateral_oracle_usd: w.collateral_usdc, debt_usd: w.borrow_usdc, ltv: w.ltv, lltv: b.lltv,
        evidence: {grade: 'A', source: `Morpho position: ${src}; value = PT units x Pendle PT price ${px.toFixed(5)}`}},
        {label: `Wallet ${a.slice(0, 10)}...: PT on Morpho (real position)`});
    return [true, out];
  }
  /* The dashboard for a position worth sizeUsd today: call once when the size (or wallet) input changes,
     then pass the result as d to every other function. */
  function atSize(d, sizeUsd, wallet = null) {
    const si = d.size_input, out = Object.assign({}, d), presets = {};
    for (const [k, p] of Object.entries(d.position_presets)) presets[k] = p.sized ? sizedPreset(p, sizeUsd, si) : p;
    out.position_presets = presets;
    if (wallet) {
      const [read, ws] = walletPresets(d, wallet);
      out.wallet_read = read; out.wallet_found = Object.keys(ws).length > 0;
      Object.assign(presets, ws);
    }
    const [curve, cap] = sizeCurve(d, sizeUsd);
    out.exit_curve = curve.map(([x, s]) => ({fraction: x, usd: x * sizeUsd, loss: s, gas_usd: gasAt(d, x * sizeUsd)}));
    out.max_exit_fraction = cap;
    out.position = Object.assign({}, d.position, {notional_usd: sizeUsd});
    if (d.borrowers && d.borrowers.liquidation_curve && d.exit_curve_usd && d.exit_curve_usd.length)
      out.borrowers = Object.assign({}, d.borrowers,
        {exit_later: d.borrowers.liquidation_curve.map(r => exitLaterAt(d, sizeUsd, r.oracle_drop))});
    out.size_usd = sizeUsd;
    return out;
  }

  /* Fault injection on one of the Risk Desk's 9 nodes (port of frontend_contract.inject).
     d = dashboard.json, presetKey in d.position_presets, node/fail = key of d.ui.injections ("usde:depeg"),
     sev in the failure's unit (% or h). Returns the loss (fraction of equity, USD) and the exit effect. */
  function inject(d, presetKey, node, fail, sev, opts = null) {
    opts = opts || {};
    const m = d.ui.injections[node + ':' + fail], p = d.position_presets[presetKey];
    const C = 'collateral_usd' in opts ? opts.collateral_usd : p.collateral_usd;
    const Co = 'collateral_oracle_usd' in opts ? opts.collateral_oracle_usd
      : C * ('collateral_oracle_usd' in p ? p.collateral_oracle_usd : p.collateral_usd) / p.collateral_usd;
    const V = 'sale_value_usd' in opts ? opts.sale_value_usd : p.collateral_usd;
    const D = 'debt_usd' in opts ? opts.debt_usd : p.debt_usd, equity = C - D;
    const canHold = 'can_hold' in opts ? opts.can_hold : p.can_hold;
    const [curve, cap] = sizeCurve(d, V);
    const out = {type: m.type, note: m.note, L_low: 0, L_high: 0, loss_usd: 0, oracle_falls: null, liquidated: null,
                 sellable_now: cap, sellable_later: cap, avg_cost_later: slippageAt(cap, curve)};
    const later = drop => {
      let r = exitLaterAt(d, V, drop);
      if (r === null) {                                   // older dashboards
        const rows = (d.borrowers && d.borrowers.exit_later) || [];
        if (!rows.length) return;
        r = rows[0];
        for (const x of rows) if (Math.abs(x.oracle_drop - drop) < Math.abs(r.oracle_drop - drop)) r = x;
      }
      Object.assign(out, {sellable_later: r.sellable_later, avg_cost_later: r.avg_cost_later, exit_row_drop: r.oracle_drop});
    };
    if (m.type === 'loss_model') {
      const shock = sev / 100, L2 = m.scenario_layer === 2, hours = 'hours' in opts ? opts.hours : m.hours;
      let flag = m.oracle === 'rule' ? oracleFalls(d.oracle, m.scenario_layer, shock, hours, m.token || null) : m.oracle;
      if ('oracle_falls' in opts) flag = opts.oracle_falls;
      const r = positionLoss({layer: m.scenario_layer, shock, permanent: 'permanent' in opts ? opts.permanent : m.permanent, hours},
        {collateral_usd: C, debt_usd: D, lltv: p.lltv || 0.915, can_hold: canHold,
         oracle_tracks_underlying: L2 ? flag : null, oracle_tracks_market: L2 ? null : flag, collateral_oracle_usd: Co});
      Object.assign(out, {L_low: r.L_low, L_high: r.L_high, loss_usd: r.L_high * equity, oracle_falls: flag,
                          liquidated: r.branches.map(b => b.liquidated)});
      if (flag === true) later(shock);
    } else if (m.type === 'exit_later') later(sev / 100);
    else if (m.type === 'exit_only') Object.assign(out, {sellable_later: cap * (1 - sev / 100), avg_cost_later: slippageAt(cap, curve)});
    return out;
  }

  /* Decision without a probability (port of frontend_contract.decide_at): given the incident at severity sev,
     sell x minimising x*(slippage+carry) + (1-x)*L(sev). The sale is sized and costed on today's value V; the loss is
     on the equity E at the end of the incident; costs per unit of equity: (slippage + carry) x V / E. */
  function decideAt(d, presetKey, node, fail, sev, carry = 0, opts = null) {
    const r = inject(d, presetKey, node, fail, sev, opts), p = d.position_presets[presetKey], o = opts || {};
    const C = 'collateral_usd' in o ? o.collateral_usd : p.collateral_usd;
    const V = 'sale_value_usd' in o ? o.sale_value_usd : p.collateral_usd;
    const E = C - ('debt_usd' in o ? o.debt_usd : p.debt_usd), scale = V / E, L = r.L_high;
    const raw = sizeCurve(d, V)[0];
    const dec = decide(1, L, raw.map(([x, s]) => [x, s * scale]), carry * scale), x = dec.exitFraction;
    const sale = x * ((x > 0 ? slippageAt(x, raw) : 0) + carry) * V, kept = (1 - x) * L * E;
    const verdict = x <= 0 ? 'STAY' : dec.stuckFraction > 0 ? 'SELL_TO_CAP' : x >= 1 - 1e-12 ? 'EXIT' : 'REDUCE';
    return Object.assign({}, r, {verdict, sell_fraction: x, sell_usd: x * V, sale_cost_usd: sale, loss_if_stay_usd: L * E,
      loss_kept_usd: kept, total_if_act_usd: sale + kept, avoided_usd: L * E - sale - kept, stuck_fraction: dec.stuckFraction});
  }

  /* Smallest severity at which selling starts / reaches the cap (port of frontend_contract.break_even_severity). */
  function breakEvenSeverity(d, presetKey, node, fail, carry = 0, lo = null, hi = null, steps = 400, opts = null) {
    const ft = d.failure_types.types[fail];
    lo = lo === null ? ft.min : lo; hi = hi === null ? ft.max : hi;
    if (d.ui.injections[node + ':' + fail].type !== 'loss_model') return {start: null, cap: null, lo, hi};
    const first = pred => {
      if (pred(lo)) return lo;
      let prev = lo;
      for (let i = 1; i <= steps; i++) {
        const s = lo + (hi - lo) * i / steps;
        if (pred(s)) { let a = prev, b = s;
          for (let k = 0; k < 40; k++) { const m = (a + b) / 2; if (pred(m)) b = m; else a = m; }
          return b; }
        prev = s;
      }
      return null;
    };
    const sells = s => decideAt(d, presetKey, node, fail, s, carry, opts).sell_fraction > 0;
    const full = s => ['SELL_TO_CAP', 'EXIT'].includes(decideAt(d, presetKey, node, fail, s, carry, opts).verdict);
    return {start: first(sells), cap: first(full), lo, hi};
  }

  /* ---- second view: vaults (port of vault_pipeline.vault_decide / liquidity_run). v = a vault detail
     (window.VAULTS.details[address]); inc = one of v.incidents; amount in the vault asset (~USD / EUR). */
  function vaultDecide(inc, ex, amount, pWorst = null, altApy = null, horizonDays = null) {
    const alt = altApy === null ? ex.alt_apy : altApy, h = horizonDays === null ? ex.horizon_days : horizonDays;
    const carry = Math.max(0, (ex.vault_apy || 0) - alt) * h / 365, pen = ex.force_deallocate_penalty;
    const o = {}; for (const x of inc.outcomes) o[x.outcome] = x;
    const w = inc.worst_outcome, Lw = o[w].L_high || 0, pw0 = o[w].probability || 0;
    const pw = pWorst === null ? pw0 : pWorst;
    const other = w === 'severe' ? 'partial' : null;
    const ratio = other && pw0 && o[other].L_high !== null ? o[other].probability / pw0 : 0;
    const Lo = other && o[other].L_high !== null ? o[other].L_high : 0;
    const po = Math.min(ratio * pw, 1 - pw), el = pw * Lw + po * Lo;
    const freeAmt = Math.min(amount, ex.free_usd), forcedAmt = Math.min(amount - freeAmt, ex.forced_usd);
    const lockedAmt = amount - freeAmt - forcedAmt;
    const out = {amount, p_worst: pw, p_other: po, worst_outcome: w, L_worst: Lw, L_other: Lo, expected_loss: el,
                 stay_loss_usd: el * amount, carry_cost: carry, penalty: pen, free_usd: freeAmt, forced_usd: forcedAmt,
                 locked_usd: lockedAmt,
                 p_break_even: (Lw + ratio * Lo) > 0 ? carry / (Lw + ratio * Lo) : null,
                 p_break_even_worst_alone: Lw > 0 ? carry / Lw : null};
    if (inc.type === 'asset_issuer')
      return Object.assign(out, {verdict: 'REVIEW', exit_usd: 0, exit_cost_usd: 0, loss_if_exit_usd: el * amount});
    const takeFree = el > carry, takeForced = el > carry + pen;
    const exitAmt = freeAmt * takeFree + forcedAmt * takeForced;
    const cost = freeAmt * carry * takeFree + forcedAmt * (carry + pen) * takeForced;
    const verdict = exitAmt <= 0 ? 'STAY' : exitAmt >= amount - 1e-9 ? 'EXIT' : 'EXIT_PARTIAL';
    return Object.assign(out, {verdict, exit_usd: exitAmt, exit_cost_usd: cost,
                               loss_if_exit_usd: el * (amount - exitAmt) + cost});
  }

  /* Morpho liquidity incident: other depositors take `share` (0..1) of the free liquidity first. */
  function vaultRun(ex, amount, share, worstExpectedLoss) {
    const freeAmt = Math.min(amount, ex.free_usd * (1 - share));
    const forcedAmt = Math.min(amount - freeAmt, ex.forced_usd * (1 - share));
    const locked = amount - freeAmt - forcedAmt;
    return {others_take: share, free_usd: freeAmt, forced_usd: forcedAmt, locked_usd: locked,
            expected_loss_on_locked_usd: locked * worstExpectedLoss};
  }

  /* Vault decision without a probability (port of vault_pipeline.vault_decide_at): given the incident at severity
     sev, withdraw each tranche whose unit cost is below L(sev); L from inc.severity_grid (linear, 0 at 0). */
  function vaultLossAt(grid, sev) {
    const pts = [[0, 0]].concat(grid.map(g => [g.severity, g.L_high]));
    if (sev >= pts[pts.length - 1][0]) return pts[pts.length - 1][1];
    for (let i = 1; i < pts.length; i++) {
      const [s0, l0] = pts[i - 1], [s1, l1] = pts[i];
      if (sev <= s1) return l0 + (l1 - l0) * (sev - s0) / (s1 - s0);
    }
    return pts[pts.length - 1][1];
  }
  function severityCrossing(grid, c) {
    const pts = [[0, 0]].concat(grid.map(g => [g.severity, g.L_high]));
    for (let i = 1; i < pts.length; i++) {
      const [s0, l0] = pts[i - 1], [s1, l1] = pts[i];
      if (l1 > c) return l0 > c ? s0 : s0 + (c - l0) * (s1 - s0) / (l1 - l0);
    }
    return null;
  }
  function durationGrid(inc, hours, recovers) {
    if (hours === null || hours === undefined || !inc.duration_grids) return inc.severity_grid;
    let best = null;
    for (const g of inc.duration_grids)
      if (g.recovers === !!recovers && g.from_hours <= hours && (best === null || g.from_hours > best.from_hours)) best = g;
    return best ? best.grid : inc.severity_grid;
  }
  function vaultDecideAt(inc, ex, amount, sev = null, altApy = null, horizonDays = null, lowBranch = false,
                         hours = null, recovers = false) {
    sev = sev === null ? inc.default_severity : sev;
    const baseGrid = durationGrid(inc, hours, recovers);
    const grid = lowBranch ? baseGrid.map(g => ({severity: g.severity, L_high: g.L_low})) : baseGrid;
    const alt = altApy === null ? ex.alt_apy : altApy;
    const h = horizonDays === null ? (hours !== null && hours !== undefined ? hours / 24 : ex.horizon_days) : horizonDays;
    const carry = Math.max(0, (ex.vault_apy || 0) - alt) * h / 365, pen = ex.force_deallocate_penalty;
    const L = vaultLossAt(grid, sev);
    const freeAmt = Math.min(amount, ex.free_usd), forcedAmt = Math.min(amount - freeAmt, ex.forced_usd);
    const locked = amount - freeAmt - forcedAmt;
    const out = {amount, severity: sev, L, loss_if_stay_usd: L * amount, carry_cost: carry, penalty: pen,
                 free_usd: freeAmt, forced_usd: forcedAmt, locked_usd: locked,
                 severity_break_even_free: severityCrossing(grid, carry),
                 severity_break_even_forced: severityCrossing(grid, carry + pen)};
    if (inc.type === 'asset_issuer')
      return Object.assign(out, {verdict: 'REVIEW', exit_usd: 0, exit_cost_usd: 0, loss_kept_usd: L * amount,
                                 total_if_act_usd: L * amount, avoided_usd: 0});
    const takeFree = L > carry, takeForced = L > carry + pen;
    const exitAmt = freeAmt * takeFree + forcedAmt * takeForced;
    const cost = freeAmt * carry * takeFree + forcedAmt * (carry + pen) * takeForced, kept = L * (amount - exitAmt);
    return Object.assign(out, {verdict: exitAmt <= 0 ? 'STAY' : exitAmt >= amount - 1e-9 ? 'EXIT' : 'EXIT_PARTIAL',
      exit_usd: exitAmt, exit_cost_usd: cost, loss_kept_usd: kept, total_if_act_usd: cost + kept,
      avoided_usd: L * amount - cost - kept});
  }

  /* ---- timeline: how long the incident lasts (port of frontend_contract.decide_at_duration / timeline_pt) */
  const DURATIONS_H = [1, 6, 12, 16, 24, 48, 72, 168, 336, 720, 1440, 2160, 4320];
  function ptPrices(tm, days) {
    const left = Math.max(0, tm.days_to_expiry - days);
    const mk = tm.implied_apy !== null ? 1 / Math.pow(1 + tm.implied_apy, left / 365) : null;
    const orc = tm.oracle_discount_per_year !== null ? 1 - left / 365 * tm.oracle_discount_per_year : null;
    return [mk, orc];
  }
  /* Yield given up by selling now, fraction of the value sold (port of frontend_contract.carry_of): (implied APY -
     altApy) over `days`, at most until expiry (days null = until expiry); altApy null = nothing given up. Pass the
     result as `carry` to decideAt / breakEvenSeverity / sensitivity, never the annual difference. */
  function carryOf(d, altApy = null, days = null) {
    const tm = d.time_model, alt = altApy === null || altApy === undefined ? tm.implied_apy : altApy;
    const left = Math.max(0, tm.days_to_expiry);
    return Math.max(0, tm.implied_apy - alt) * (days === null || days === undefined ? left : Math.min(days, left)) / 365;
  }
  function decideAtDuration(d, presetKey, node, fail, sev, hours, recovers = true, altApy = null) {
    const tm = d.time_model, m = d.ui.injections[node + ':' + fail], p = d.position_presets[presetKey];
    const days = hours / 24, [mk0, orc0] = ptPrices(tm, 0), [mkT, orcT] = ptPrices(tm, days);
    const carry = carryOf(d, altApy, days);
    const V0 = p.collateral_usd, D0 = p.debt_usd;
    const Co0 = 'collateral_oracle_usd' in p ? p.collateral_oracle_usd : V0;
    const VT = V0 * (mk0 && mkT ? mkT / mk0 : 1);
    const C = Co0 * (orc0 && orcT ? orcT / orc0 : 1);
    const D = D0 > 0 ? D0 * Math.exp((tm.borrow_apr || 0) * days / 365) : 0;
    const opts = {hours, collateral_usd: VT, collateral_oracle_usd: C, debt_usd: D, sale_value_usd: V0};
    if (recovers && m.type === 'loss_model') opts.permanent = 0;
    const r = decideAt(d, presetKey, node, fail, sev, carry, opts);
    return Object.assign(r, {hours, days, recovers, past_expiry: days >= tm.days_to_expiry, carry,
      pt_price_market: mkT, pt_price_oracle: orcT, position_value_usd: VT,
      collateral_usd: C, debt_usd: D, ltv: C ? D / C : null});
  }
  function timeline(d, presetKey, node, fail, sev, recovers = true, altApy = null, durations = null) {
    const tm = d.time_model;
    const hs = Array.from(new Set((durations || DURATIONS_H).concat([Math.round(tm.days_to_expiry * 24 * 1e6) / 1e6])))
      .sort((a, b) => a - b).filter(h => h > 0);
    return hs.map(h => decideAtDuration(d, presetKey, node, fail, sev, h, recovers, altApy));
  }

  /* Does the duration change the verdict? (port of frontend_contract.timeline_summary) */
  function timelineSummary(d, presetKey, rows) {
    const levered = d.position_presets[presetKey].debt_usd > 0, changes = [];
    const anyTrue = x => !!(x && x.some(Boolean));
    for (let i = 1; i < rows.length; i++) {
      const a = rows[i - 1], b = rows[i];
      if (a.verdict === b.verdict) continue;
      const why = [];
      if (b.oracle_falls === true && a.oracle_falls !== true) why.push('the meta-oracle switches (challenge timelock reached)');
      if (b.past_expiry && !a.past_expiry) why.push('the PT reaches expiry');
      if (anyTrue(b.liquidated) && !anyTrue(a.liquidated))
        why.push(levered && a.past_expiry ? 'the debt keeps growing after expiry until the LTV crosses the liquidation line'
                                          : 'the position is liquidated');
      if (!why.length) why.push(levered && a.past_expiry ? 'the debt keeps growing after expiry'
                                                         : 'the loss or the yield given up changes with the duration');
      changes.push({from_hours: a.hours, to_hours: b.hours, verdict_before: a.verdict, verdict_after: b.verdict,
                    reason: why.join('; ')});
    }
    const flat = changes.length ? null : (!levered
      ? 'no debt: nothing in this position changes with time (no oracle timer, no interest), so the verdict depends only on the severity and on whether the loss recovers'
      : 'the verdict is the same at every duration on the grid');
    return {duration_matters: changes.length > 0, changes, verdict: rows.length && !changes.length ? rows[0].verdict : null,
            why_flat: flat};
  }
  /* Same for the vault view (port of vault_pipeline.vault_timeline_summary). */
  function vaultTimelineSummary(inc, rows) {
    const switches = (inc.duration_grids || []).map(g => g.from_hours).filter(h => h > 0), changes = [];
    for (let i = 1; i < rows.length; i++) {
      const a = rows[i - 1], b = rows[i];
      if (a.verdict === b.verdict) continue;
      const why = switches.some(h => a.hours < h && h <= b.hours)
        ? 'a meta-oracle of an affected market switches (challenge timelock reached)'
        : Math.abs(a.L - b.L) < 1e-12 ? 'the yield given up grows with the duration' : 'the vault loss changes with the duration';
      changes.push({from_hours: a.hours, to_hours: b.hours, verdict_before: a.verdict, verdict_after: b.verdict, reason: why});
    }
    const flat = changes.length ? null : (!switches.length
      ? 'no affected market has an oracle timer, so the duration does not change the loss; the verdict depends on the severity and on whether the loss recovers'
      : 'the verdict is the same at every duration on the grid');
    return {duration_matters: changes.length > 0, changes, verdict: rows.length && !changes.length ? rows[0].verdict : null,
            why_flat: flat};
  }

  /* ---- reasons a manager can act on (port of frontend_contract.decision_text): every number comes from the model;
     numbers are formatted by _num (round half away from zero, thousands commas), identical to the Python. */
  const NUM = /\$?\d[\d,]*(?:\.\d+)?[%x]?/g;
  function _roundInt(v, d) { const a = Math.floor(Math.abs(v) * Math.pow(10, d) + 0.5); return v < 0 ? -a : a; }
  function _num(v, d = 2) {
    let n = _roundInt(v, d); const sign = n < 0 ? '-' : ''; n = Math.abs(n);
    const p = Math.pow(10, d), ip = Math.floor(n / p), fp = n - ip * p;
    const frac = d ? String(fp).padStart(d, '0').replace(/0+$/, '') : '';
    return sign + String(ip).replace(/\B(?=(\d{3})+(?!\d))/g, ',') + (frac ? '.' + frac : '');
  }
  function decisionText(d, presetKey, node, fail, sev, carry = 0, opts = null) {
    opts = opts || {};
    const r = decideAt(d, presetKey, node, fail, sev, carry, opts);
    const be = breakEvenSeverity(d, presetKey, node, fail, carry, null, null, 400, opts);
    const sv = sensitivity(d, presetKey, node, fail, sev, carry, opts);
    const m = d.ui.injections[node + ':' + fail], p = d.position_presets[presetKey], ft = d.failure_types.types[fail];
    const o = d.oracle || {}, nl = d.ui.nodes[node].label, fl = ft.label, nums = [];
    const f = s => { nums.push(...(s.match(NUM) || [])); return s; };
    const money = v => f('$' + _num(v, 0)), pct = v => f(_num(v * 100, 2) + '%');
    const unit = v => f(_num(v, 2) + (ft.unit === '%' ? '%' : ' h'));
    const D = p.debt_usd, C = p.collateral_usd, Co = 'collateral_oracle_usd' in p ? p.collateral_oracle_usd : C;
    const title = `${fl} (${nl}), severity ${unit(sev)}`, reasons = [];
    let head;
    if (m.type === 'loss_model') {
      const loss = r.loss_if_stay_usd;
      if (loss <= 0) head = 'STAY: doing nothing loses nothing at this severity, so there is nothing to sell for.';
      else if (r.verdict === 'STAY') head = `STAY: doing nothing loses ${money(loss)}; selling would cost more than it saves.`;
      else head = `${r.verdict}: doing nothing loses ${money(loss)}. Selling ${money(r.sell_usd)} now ` +
        `(${pct(r.sell_fraction)} of the position) costs ${money(r.sale_cost_usd)}` +
        (r.loss_kept_usd > 0 ? ` and leaves ${money(r.loss_kept_usd)} at risk on the rest.` : '.') +
        (r.stuck_fraction > 0 ? ` ${pct(r.stuck_fraction)} of the position cannot be sold through the pool now.` : '');
      const of = r.oracle_falls, meta = o.kind === 'meta_oracle_timelock' && m.oracle === 'rule';
      if (of === true)
        reasons.push(meta ? `The lending oracle follows it: the deviation is above the meta-oracle's ` +
          `${pct(o.deviation_threshold)} threshold for at least ${f(_num(o.challenge_timelock_s / 3600, 2))} h, ` +
          `so it switches to its backup feed.` : 'The lending oracle reports the low price itself.');
      else if (of === false)
        reasons.push(meta ? `The lending oracle does not follow it: the meta-oracle switches only after a deviation ` +
          `above ${pct(o.deviation_threshold)} lasting ${f(_num(o.challenge_timelock_s / 3600, 2))} h.`
          : 'The lending oracle does not follow it: no feed of the oracle prices this.');
      else reasons.push(`The oracle's behaviour is unknown: the loss is the worse of both branches ` +
          `(${pct(r.L_low)} to ${pct(r.L_high)} of equity).`);
      if (D <= 0) reasons[reasons.length - 1] += ' This matters only for a levered position: this one has no debt.';
      if (D > 0) {
        const thr = 1 - D / (Co * p.lltv);
        if ((r.liquidated || []).some(Boolean))
          reasons.push(`The position is liquidated: the oracle falls ${unit(sev)} while the liquidation line is ` +
            `${pct(thr)} away; Morpho seizes collateral worth the debt plus a ${pct(lif(p.lltv) - 1)} bonus.`);
        else if (thr > 0)
          reasons.push(`Not liquidated: the oracle would have to fall ${pct(thr)} before this position can be liquidated.`);
        else reasons.push('The position is already above the liquidation line.');
      }
      const perm = 'permanent' in opts ? opts.permanent : m.permanent;
      if (m.permanent === 0 && p.can_hold)
        reasons.push('The price recovers (the PT redeems at expiry), so a holder who can wait loses nothing on the value' +
          (D > 0 ? '; liquidations during the incident stay.' : '.'));
      else if (perm === 0 && p.can_hold)
        reasons.push('The shock is over after the incident' +
          (opts.hours !== null && opts.hours !== undefined ? ` (${f(_num(opts.hours, 2))} h)` : '') +
          ', so a holder who can wait loses nothing on the value' + (D > 0 ? '; liquidations during the incident stay.' : '.'));
      else if (perm === 1) reasons.push('The loss is permanent: no recovery is assumed.');
    } else if (m.type === 'exit_later' || m.type === 'exit_only') {
      head = 'STAY: no direct loss on this position; ' + (r.sellable_later < r.sellable_now - 1e-12
        ? `the part that can be sold falls from ${pct(r.sellable_now)} to ${pct(r.sellable_later)}.`
        : `${pct(r.sellable_now)} of the position can still be sold.`);
    } else head = 'STAY: no direct loss is modelled for this failure.';
    const later = r.sellable_later < r.sellable_now - 1e-12 && m.type !== 'not_modelled';
    reasons.push(`Today the pool takes ${pct(r.sellable_now)} of this position (${money(r.sellable_now * C)})` +
      (later ? (r.sellable_later <= 0 ? '; after the failure nothing can be sold.'
                                      : `; after the failure only ${pct(r.sellable_later)}.`) : '.'));
    let brk;
    if (m.type !== 'loss_model') brk = 'No break-even severity: this failure causes no direct loss.';
    else if (be.start === null) brk = `Selling does not pay at any severity from ${unit(be.lo)} to ${unit(be.hi)}.`;
    else if (be.start <= be.lo)
      brk = `Selling pays from the lowest severity tested (${unit(be.lo)})` + (be.cap === null ? '.'
        : be.cap <= be.lo ? ' up to all the pool takes.' : `; it sells all the pool takes above ${unit(be.cap)}.`);
    else brk = `Selling starts to pay above ${unit(be.start)}` +
      (be.cap !== null ? ` and sells all the pool takes above ${unit(be.cap)}.` : '.');
    const w = sv.weakest;
    let hinge;
    if (w) { f(w.alternative); hinge = `The answer hinges on: ${w.alternative} (grade ${w.grade}): the verdict would be ${w.verdict}.`; }
    else hinge = 'No tested assumption changes the answer.';
    const text = [title, head].concat(reasons, [brk, hinge]).join(' ').split(nl).join('').split(fl).join('');
    const bad = (text.match(NUM) || []).filter(x => !nums.includes(x));
    return {verdict: r.verdict, title, headline: head, rule: m.note, reasons, break_even: brk, hinges_on: hinge,
            numbers: nums, unchecked: bad};
  }

  const RANK = 'ABCD';

  /* How the incident travels through the five layers, step by step (port of frontend_contract.propagation). */
  const PROPAGATION_ORIGIN = {
    'eth:halt': 'Ethereum stops producing blocks for {sev}: no exit and no liquidation while it lasts.',
    'ethena:shortfall': 'Ethena cannot fully back USDe (off-chain reserves, custodians and hedges): USDe falls {sev}.',
    'usde:depeg': 'USDe falls {sev} against USD.',
    'susde:navLoss': "sUSDe's NAV (USDe per sUSDe) falls {sev}.",
    'susde:discount': 'sUSDe trades {sev} below its NAV; the NAV itself is unchanged.',
    'feeds:oracleLow': 'An upstream feed of the lending oracle reports a price {sev} too low; the price recovers ' +
                       'afterwards, the PT itself is unchanged.',
    'feeds:stale': 'An upstream feed of the lending oracle stops updating for {sev}.',
    'oracle:oracleLow': 'The Morpho market oracle reports a PT price {sev} too low; the price recovers afterwards, the ' +
                        'PT itself is unchanged.',
    'oracle:stale': 'The Morpho market oracle stops updating for {sev}.',
    'market:drain': "{sev} of the Pendle pool's liquidity leaves.",
    'pt:depeg': "The PT's market price on Pendle falls {sev}; the PT still redeems at expiry, so holding to expiry " +
                'recovers it.',
    'lending:cascade': 'Other borrowers of the Morpho market are liquidated at a {sev} oracle drop and their PT is sold ' +
                       'into the Pendle pool first.'
  };
  function propagation(d, presetKey, node, fail, sev, carry = 0, opts = null) {
    opts = opts || {};
    const r = decideAt(d, presetKey, node, fail, sev, carry, opts);
    const m = d.ui.injections[node + ':' + fail], p = d.position_presets[presetKey], ft = d.failure_types.types[fail];
    const o = d.oracle || {}, nodes = d.ui.nodes, nums = [];
    const f = s => { nums.push(...(s.match(NUM) || [])); return s; };
    const money = v => f('$' + _num(v, 0)), pct = v => f(_num(v * 100, 2) + '%');
    const unit = v => f(_num(v, 2) + (ft.unit === '%' ? '%' : ' h')), hrs = v => f(_num(v, 2) + ' h');
    const edges = (...pairs) => {
      const out = [];
      for (const [a, b] of pairs) {
        const e = d.ui.edges.find(e => e.from === a && e.to === b);
        if (e) out.push({from: a, to: b, type: e.type, grade: e.grade});
      }
      return out;
    };
    const worst = gs => {
      gs = gs.filter(Boolean);
      return gs.length ? gs.reduce((a, g) => RANK.indexOf(g) > RANK.indexOf(a) ? g : a) : null;
    };
    const C = 'collateral_usd' in opts ? opts.collateral_usd : p.collateral_usd;
    const D = 'debt_usd' in opts ? opts.debt_usd : p.debt_usd;
    const Co = 'collateral_oracle_usd' in opts ? opts.collateral_oracle_usd
      : C * ('collateral_oracle_usd' in p ? p.collateral_oracle_usd : p.collateral_usd) / p.collateral_usd;
    const V = 'sale_value_usd' in opts ? opts.sale_value_usd : p.collateral_usd, E = C - D;
    const hours = 'hours' in opts ? opts.hours : (m.hours === undefined ? null : m.hours);
    const perm = 'permanent' in opts ? opts.permanent : m.permanent;
    const canHold = 'can_hold' in opts ? opts.can_hold : p.can_hold;
    const of = r.oracle_falls, liq = (r.liquidated || []).some(Boolean), lm = m.type === 'loss_model';
    const oGrade = (o.evidence || {}).grade || 'D', s = sev / 100, steps = [];
    const step = (layer, nd, state, text, grade, edg = []) => steps.push({layer, node: nd, state, text, grade, edges: edg});

    // 1. origin
    const originLayer = nodes[node].layer;
    let text = PROPAGATION_ORIGIN[node + ':' + fail].replace('{sev}', unit(sev));
    if (node === 'market')
      text += ` The pool takes ${pct(r.sellable_now)} of this position today, ` +
        (r.sellable_later <= 0 ? 'nothing after.' : `${pct(r.sellable_later)} after.`);
    step(originLayer, node, 'origin', text, null,
         node === 'ethena' ? edges(['ethena', 'usde']) : node === 'feeds' ? edges(['feeds', 'oracle']) : []);

    // 2. the PT's value (layer 4), for failures upstream of the PT
    if (lm && originLayer === 2) {
      if (fail === 'discount') {
        step(4, 'pt', 'unchanged', "The PT redeems at the NAV-based rate, not at sUSDe's market price: its " +
             'redemption value does not fall, and holding to expiry recovers the discount.', 'A', edges(['susde', 'pt']));
      } else {
        let t, e;
        if (node === 'susde') {
          t = `The SY exchange rate falls with the NAV and the PT index never decreases: the PT's value falls ${unit(sev)}`;
          e = edges(['susde', 'pt']);
        } else {
          t = `The PT redeems to sUSDe, which is staked USDe: the PT's value falls ${unit(sev)}`;
          e = edges(['usde', 'susde'], ['susde', 'pt']);
        }
        if (perm >= 1) t += '; the loss is permanent (no recovery assumed).';
        else if (perm <= 0)
          t += '; the shock is over after the incident' + (hours !== null ? ` (${hrs(hours)})` : '') +
            ', so a holder who can wait gets it back.';
        else t += `; ${pct(perm)} of it remains after the incident.`;
        if (!canHold) t += ' This position must sell at the worst point.';
        step(4, 'pt', 'hit', t, worst(e.map(x => x.grade)) || 'A', e);
      }
    }

    // 3. the lending oracle (layer 3)
    if (lm && node !== 'oracle') {
      const meta = o.kind === 'meta_oracle_timelock' && m.oracle === 'rule';
      const thr = o.deviation_threshold, tl = o.challenge_timelock_s;
      let st, t;
      if (node === 'feeds') { st = 'hit'; t = `The Morpho market oracle reads this feed: it falls ${unit(sev)} too.`; }
      else if (of === true && meta) {
        st = 'hit'; t = `The meta-oracle sees a deviation above ${pct(thr)} for at least ${hrs(tl / 3600)} and ` +
          `switches to its backup feed with USDe / USD: the lending oracle falls ${unit(sev)}.`;
      } else if (of === true) { st = 'hit'; t = `The lending oracle follows: it falls ${unit(sev)}.`; }
      else if (of === false && meta && thr !== null && thr !== undefined && s <= thr) {
        st = 'unchanged'; t = `The deviation (${unit(sev)}) is not above the meta-oracle's ${pct(thr)} threshold: ` +
          'the lending oracle does not move.';
      } else if (of === false && meta) {
        st = 'unchanged'; t = `The meta-oracle switches only after a deviation above ${pct(thr)} lasting ` +
          `${hrs(tl / 3600)}; this incident lasts ${hrs(hours)}: the lending oracle does not move.`;
      } else if (of === false) {
        st = 'unchanged'; t = 'No feed of the lending oracle prices this (the PT is priced by a linear discount, ' +
          'no market input): the lending oracle does not move.';
      } else {
        st = 'unknown'; t = "The lending oracle's behaviour is unknown: the loss is the worse of both branches " +
          `(${pct(r.L_low)} to ${pct(r.L_high)} of equity).`;
      }
      if (D <= 0) t += ' This matters only for a levered position: this one has no debt.';
      step(3, 'oracle', st, t, oGrade);
    }

    // 4. liquidation (layer 5)
    if (lm) {
      if (D <= 0) step(5, 'lending', 'not_applicable', 'This position has no debt: nothing to liquidate.', null);
      else {
        const line = 1 - D / (Co * p.lltv), bonus = pct(lif(p.lltv) - 1);
        const e = edges(['oracle', 'lending'], ['pt', 'lending']);
        let st, t;
        if (liq && line <= 0) {
          st = 'hit'; t = 'The position is already above the liquidation line: Morpho can liquidate it, the ' +
            `liquidator taking collateral worth the debt plus a ${bonus} bonus.`;
        } else if (liq && of === null) {
          st = 'hit'; t = `If the oracle follows, the position is liquidated (the liquidation line is ` +
            `${pct(line)} away); the liquidator takes collateral worth the debt plus a ${bonus} bonus.`;
        } else if (liq) {
          st = 'hit'; t = `The lending oracle falls ${unit(sev)} while the liquidation line is ${pct(line)} away: ` +
            'Morpho liquidates this position, the liquidator taking collateral worth the debt plus ' +
            `a ${bonus} bonus.`;
        } else if (of === true) {
          st = 'unchanged'; t = `The lending oracle falls ${unit(sev)} but the liquidation line is ${pct(line)} ` +
            'away: not liquidated.';
        } else {
          st = 'unchanged'; t = 'The lending oracle does not move: not liquidated (the liquidation line is ' +
            `${pct(line)} away).`;
        }
        step(5, 'lending', st, t, worst(['B'].concat(e.map(x => x.grade))), e);
      }
    }

    // 5. exit liquidity (layer 4)
    if (m.type !== 'not_modelled' && node !== 'market') {
      if (r.sellable_later < r.sellable_now - 1e-12) {
        const t = 'Liquidators sell the seized PT into the Pendle pool first: ' +
          (r.sellable_later <= 0 ? `the pool takes ${pct(r.sellable_now)} of this position today, nothing after.`
            : `the pool takes ${pct(r.sellable_now)} of this position today, only ${pct(r.sellable_later)} after.`);
        const e = edges(['lending', 'market']);
        step(4, 'market', 'hit', t, worst(['B'].concat(e.map(x => x.grade))), e);
      } else {
        step(4, 'market', 'unchanged', `The Pendle pool still takes ${pct(r.sellable_now)} of this position ` +
             `(${money(r.sellable_now * V)}).`, 'A');
      }
    }

    // 6. the position and 7. the verdict
    const hitGrades = steps.filter(x => x.state === 'hit' || x.state === 'unknown').map(x => x.grade);
    const pe = edges(['pt', 'position']).concat(D > 0 ? edges(['lending', 'position']) : []);
    const loss = r.loss_if_stay_usd;
    let t;
    if (lm) t = loss > 0 ? `Loss if staying: ${money(loss)} (${pct(r.L_high)} of the position's equity of ${money(E)}).`
      : 'No loss on this position at this severity.';
    else if (m.type === 'exit_later' || m.type === 'exit_only')
      t = 'No direct loss on this position: only how much of it can be sold changes.';
    else t = 'No loss is modelled for this failure.';
    step(null, 'position', loss > 0 ? 'hit' : 'unchanged', t, worst(hitGrades) || 'A', pe);
    let res;
    if (lm && loss > 0 && r.verdict !== 'STAY')
      res = `${r.verdict}: sell ${money(r.sell_usd)} now (${pct(r.sell_fraction)} of the position) for ` +
        `${money(r.sale_cost_usd)}; acting costs ${money(r.total_if_act_usd)} in all instead of ${money(loss)}.` +
        (r.stuck_fraction > 0 ? ` ${pct(r.stuck_fraction)} cannot be sold through the pool now.` : '');
    else if (lm && loss > 0) res = `STAY: selling would cost more than it saves (doing nothing loses ${money(loss)}).`;
    else res = 'STAY: nothing to sell for.';
    step(null, 'result', 'result', res, null);

    const rows = d.ui.layers.map(lay => {
      const mine = steps.filter(x => x.layer === lay.n);
      let st;
      if (lay.n === originLayer) st = 'origin';
      else if (mine.some(x => x.state === 'hit')) st = 'hit';
      else if (mine.some(x => x.state === 'unknown')) st = 'unknown';
      else if (mine.length && mine.every(x => x.state === 'not_applicable')) st = 'not_applicable';
      else if (mine.length) st = 'unchanged';
      else st = lay.n < originLayer && (lm || lay.n === 1) ? 'unchanged' : 'not_modelled';   // no step here
      const txt = mine.map(x => x.text).join(' ') || (st === 'unchanged' ? 'Upstream of the failure: not affected.'
                                                     : 'Not part of how this failure is modelled.');
      return {n: lay.n, name: lay.name, nodes: lay.nodes, state: st, text: txt};
    });
    const all = steps.map(x => x.text).join(' ');
    const bad = (all.match(NUM) || []).filter(x => !nums.includes(x));
    return {verdict: r.verdict, origin: {node, layer: originLayer}, steps, layers: rows, numbers: nums, unchecked: bad};
  }
  const pickWeakest = rows => {
    const flips = rows.filter(x => x.flips && !x.comparison);
    if (!flips.length) return null;
    const g = flips.reduce((a, x) => RANK.indexOf(x.grade) > RANK.indexOf(a) ? x.grade : a, 'A');
    let best = null;
    for (const x of flips) if (x.grade === g && (best === null || x.effect > best.effect)) best = x;
    return best;
  };

  /* Which assumption flips the verdict (port of frontend_contract.sensitivity). */
  function sensitivity(d, presetKey, node, fail, sev, carry = 0, opts = null) {
    opts = opts || {};
    const base = decideAt(d, presetKey, node, fail, sev, carry, opts), m = d.ui.injections[node + ':' + fail];
    const p = d.position_presets[presetKey], E = p.collateral_usd - p.debt_usd, o = d.oracle || {};
    const cands = [];
    if (m.type === 'loss_model') {
      if (m.oracle === 'rule' && o.kind === 'meta_oracle_timelock' && o.challenge_timelock_s) {
        const h = o.challenge_timelock_s / 3600 / 2;
        cands.push(['duration', `the incident lasts ${+h.toFixed(6)} h, less than the oracle's ${+(2 * h).toFixed(6)} h challenge timelock`,
                    'D', presetKey, carry, {hours: h}]);
      }
      if (p.debt_usd > 0)
        cands.push(['oracle', 'the lending oracle ' + (base.oracle_falls ? 'does not follow' : 'follows') + ' the shock',
                    (o.evidence || {}).grade || 'D', presetKey, carry, {oracle_falls: !base.oracle_falls}]);
      cands.push(['can_hold', p.can_hold ? 'the position must sell at the worst point' : 'the position can hold to expiry',
                  'D', presetKey, carry, {can_hold: !p.can_hold}]);
    }
    for (const [k, q] of Object.entries(d.position_presets))
      if (k !== presetKey) cands.push(['position', q.label, q.evidence.grade, k, carry, null]);
    const c1 = carry + 0.01 * Math.max(0, d.time_model.days_to_expiry) / 365;   // 1% a year, until expiry
    cands.push(['carry', `cash after selling earns 1% a year less than assumed (carry ${(c1 * 100).toFixed(3)}% until expiry)`,
                'D', presetKey, c1, null]);
    const rows = cands.map(([key, alternative, grade, pk, c, op]) => {
      const r = decideAt(d, pk, node, fail, sev, c, Object.assign({}, opts, op || {})), q = d.position_presets[pk],
        Ek = q.collateral_usd - q.debt_usd;
      return {key, alternative, grade, verdict: r.verdict, comparison: key === 'position',
              sell_fraction: r.sell_fraction, loss_if_stay_usd: r.loss_if_stay_usd,
              flips: r.verdict !== base.verdict,
              effect: Math.abs(r.sell_fraction - base.sell_fraction) + Math.abs(r.loss_if_stay_usd / Ek - base.loss_if_stay_usd / E)};
    });
    return {verdict: base.verdict, candidates: rows, weakest: pickWeakest(rows)};
  }

  /* Vault timeline over incident durations (port of vault_pipeline.vault_timeline). */
  function vaultTimeline(inc, ex, amount, sev = null, recovers = true, altApy = null) {
    const extra = (inc.duration_grids || []).map(g => g.from_hours).filter(h => h > 0);
    const hs = Array.from(new Set(DURATIONS_H.concat(extra))).sort((a, b) => a - b);
    return hs.map(h => Object.assign(vaultDecideAt(inc, ex, amount, sev, altApy, null, false, h, recovers),
                                     {hours: h, days: h / 24, recovers}));
  }

  /* Which assumption flips the vault verdict (port of vault_pipeline.vault_sensitivity). */
  function vaultSensitivity(inc, ex, amount, sev = null) {
    const base = vaultDecideAt(inc, ex, amount, sev);
    const gOr = (((inc.evidence || {}).L || {}).basis || {}).oracle || 'D';
    const cands = [['oracle', 'the lending oracles do not follow the shock (lower loss branch)', gOr, {low: true}],
                   ['alt_yield', 'cash earns nothing after withdrawing (alternative yield 0%)', 'D', {alt: 0}],
                   ['alt_yield', 'cash earns as much as the vault (no yield given up)', 'D', {alt: ex.vault_apy || 0}],
                   ['horizon', 'horizon 7 days', 'D', {h: 7}], ['horizon', 'horizon 90 days', 'D', {h: 90}],
                   ['amount', 'a deposit 10 times larger', 'D', {amount: amount * 10}]];
    const rows = cands.map(([key, alternative, grade, kw]) => {
      const amt = kw.amount !== undefined ? kw.amount : amount;
      const r = vaultDecideAt(inc, ex, amt, base.severity, kw.alt !== undefined ? kw.alt : null,
                              kw.h !== undefined ? kw.h : null, !!kw.low);
      const share = amt ? r.exit_usd / amt : 0, baseShare = amount ? base.exit_usd / amount : 0;
      return {key, alternative, grade, verdict: r.verdict, comparison: key === 'amount', exit_share: share, L: r.L,
              flips: r.verdict !== base.verdict,
              effect: Math.abs(share - baseShare) + Math.abs(r.L - base.L)};
    });
    return {verdict: base.verdict, candidates: rows, weakest: pickWeakest(rows)};
  }

  const api = {lif, positionLoss, oracleFalls, slippageAt, decide, breakEven, sizeCurve, exitLaterAt, borrowerPreset, walletPresets, atSize,
               inject, decideAt, breakEvenSeverity,
               sensitivity, decisionText, propagation, carryOf, decideAtDuration, timeline, timelineSummary, vaultDecide, vaultRun, vaultLossAt, vaultDecideAt,
               vaultSensitivity, vaultTimeline, vaultTimelineSummary};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.RiskModel = api;
})(typeof window !== 'undefined' ? window : this);
