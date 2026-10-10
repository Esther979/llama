/* Risk model for the dashboard: a line-by-line port of the Python backend, so sliders can move freely
   and still give the backend's numbers. Checked against Python by check_js_port.py (run it after any change).

   Ports:
     lif, positionLoss          loss_model.py  (lif, _one_branch, position_loss)
     oracleFalls                oracle_types.py (oracle_falls; meta-oracle threshold + timelock)
     slippageAt, decide         decision_core.py
     breakEven                  incidents.py (exact break-even from the exit curve, no p grid)

   Shapes (same field names as the Python dataclasses):
     scenario = {layer: 2|3, shock: 0..1, permanent: 0..1, hours: number|null}
     position = {collateral_usd, debt_usd, lltv, can_hold, oracle_tracks_underlying, oracle_tracks_market}
                (oracle flags: true / false / null = unknown -> both branches)
     curve    = [[fraction_sold, avg_slippage], ...]   (dashboard.json exit_curve as pairs)
   Load in a page with <script src="risk_model.js"></script> (global RiskModel) or require() in node. */
(function (root) {
  const LIQUIDATION_CURSOR = 0.3, MAX_LIF = 1.15;

  function lif(lltv) {
    return Math.min(MAX_LIF, 1 / (1 - LIQUIDATION_CURSOR * (1 - lltv)));
  }

  function oneBranch(s, p, oracleFalls) {
    const C = p.collateral_usd, D = p.debt_usd, equity = C - D;
    const oracleDrop = oracleFalls ? s.shock : 0;
    const endValue = 1 - s.shock * s.permanent;   // value at the end, relative to now
    const soldValue = 1 - s.shock;                // value if forced to sell at the worst point
    const out = {oracle_falls: oracleFalls, liquidated: false, bad_debt_usd: 0, liquidation_drop_threshold: null};
    if (D <= 0) {                                 // unlevered
      const v = p.can_hold ? endValue : soldValue, loss = C * (1 - v);
      return Object.assign(out, {loss_usd: loss, loss_of_equity: C ? loss / C : 0});
    }
    const threshold = 1 - D / (C * p.lltv);       // oracle drop that makes the position unhealthy
    out.liquidation_drop_threshold = threshold;
    let loss;
    if (oracleDrop > threshold) {
      const f = lif(p.lltv);
      const seized = oracleDrop < 1 ? D * f / (C * (1 - oracleDrop)) : Infinity;
      out.liquidated = true;
      out.lif = f;
      if (seized >= 1) {                          // collateral exhausted: all equity lost, rest is bad debt
        out.bad_debt_usd = D - C * (1 - oracleDrop) / f;
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
    for (let i = 0; i <= steps; i++) {
      const x = i / steps;
      if (x > maxX + 1e-12) break;
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

  /* Fault injection on one of the Risk Desk's 9 nodes (port of frontend_contract.inject).
     d = dashboard.json, presetKey in d.position_presets, node/fail = key of d.ui.injections ("usde:depeg"),
     sev in the failure's unit (% or h). Returns the loss (fraction of equity, USD) and the exit effect. */
  function inject(d, presetKey, node, fail, sev) {
    const m = d.ui.injections[node + ':' + fail], p = d.position_presets[presetKey];
    const C = p.collateral_usd, D = p.debt_usd, equity = C - D;
    const curve = d.exit_curve.map(x => [x.fraction, x.loss]), cap = d.max_exit_fraction;
    const out = {type: m.type, note: m.note, L_low: 0, L_high: 0, loss_usd: 0, oracle_falls: null, liquidated: null,
                 sellable_now: cap, sellable_later: cap, avg_cost_later: slippageAt(cap, curve)};
    const later = drop => {
      const rows = (d.borrowers && d.borrowers.exit_later) || [];
      if (!rows.length) return;
      let r = rows[0];
      for (const x of rows) if (Math.abs(x.oracle_drop - drop) < Math.abs(r.oracle_drop - drop)) r = x;
      Object.assign(out, {sellable_later: r.sellable_later, avg_cost_later: r.avg_cost_later, exit_row_drop: r.oracle_drop});
    };
    if (m.type === 'loss_model') {
      const shock = sev / 100, L2 = m.scenario_layer === 2;
      const flag = m.oracle === 'rule' ? oracleFalls(d.oracle, m.scenario_layer, shock, m.hours, m.token || null) : m.oracle;
      const r = positionLoss({layer: m.scenario_layer, shock, permanent: m.permanent, hours: m.hours},
        {collateral_usd: C, debt_usd: D, lltv: p.lltv || 0.915, can_hold: p.can_hold,
         oracle_tracks_underlying: L2 ? flag : null, oracle_tracks_market: L2 ? null : flag});
      Object.assign(out, {L_low: r.L_low, L_high: r.L_high, loss_usd: r.L_high * equity, oracle_falls: flag,
                          liquidated: r.branches.map(b => b.liquidated)});
      if (flag === true) later(shock);
    } else if (m.type === 'exit_later') later(sev / 100);
    else if (m.type === 'exit_only') Object.assign(out, {sellable_later: cap * (1 - sev / 100), avg_cost_later: slippageAt(cap, curve)});
    return out;
  }

  /* Decision without a probability (port of frontend_contract.decide_at): given the incident at severity sev,
     sell x minimising x*(slippage+carry) + (1-x)*L(sev); costs per unit of equity (x collateral / equity). */
  function decideAt(d, presetKey, node, fail, sev, carry = 0) {
    const r = inject(d, presetKey, node, fail, sev), p = d.position_presets[presetKey];
    const C = p.collateral_usd, E = C - p.debt_usd, scale = C / E, L = r.L_high;
    const raw = d.exit_curve.map(x => [x.fraction, x.loss]);
    const dec = decide(1, L, raw.map(([x, s]) => [x, s * scale]), carry * scale), x = dec.exitFraction;
    const sale = x * ((x > 0 ? slippageAt(x, raw) : 0) + carry) * C, kept = (1 - x) * L * E;
    const verdict = x <= 0 ? 'STAY' : dec.stuckFraction > 0 ? 'SELL_TO_CAP' : x >= 1 - 1e-12 ? 'EXIT' : 'REDUCE';
    return Object.assign({}, r, {verdict, sell_fraction: x, sell_usd: x * C, sale_cost_usd: sale, loss_if_stay_usd: L * E,
      loss_kept_usd: kept, total_if_act_usd: sale + kept, avoided_usd: L * E - sale - kept, stuck_fraction: dec.stuckFraction});
  }

  /* Smallest severity at which selling starts / reaches the cap (port of frontend_contract.break_even_severity). */
  function breakEvenSeverity(d, presetKey, node, fail, carry = 0, lo = null, hi = null, steps = 400) {
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
    const sells = s => decideAt(d, presetKey, node, fail, s, carry).sell_fraction > 0;
    const full = s => ['SELL_TO_CAP', 'EXIT'].includes(decideAt(d, presetKey, node, fail, s, carry).verdict);
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
  function vaultDecideAt(inc, ex, amount, sev = null, altApy = null, horizonDays = null) {
    sev = sev === null ? inc.default_severity : sev;
    const alt = altApy === null ? ex.alt_apy : altApy, h = horizonDays === null ? ex.horizon_days : horizonDays;
    const carry = Math.max(0, (ex.vault_apy || 0) - alt) * h / 365, pen = ex.force_deallocate_penalty;
    const L = vaultLossAt(inc.severity_grid, sev);
    const freeAmt = Math.min(amount, ex.free_usd), forcedAmt = Math.min(amount - freeAmt, ex.forced_usd);
    const locked = amount - freeAmt - forcedAmt;
    const out = {amount, severity: sev, L, loss_if_stay_usd: L * amount, carry_cost: carry, penalty: pen,
                 free_usd: freeAmt, forced_usd: forcedAmt, locked_usd: locked,
                 severity_break_even_free: severityCrossing(inc.severity_grid, carry),
                 severity_break_even_forced: severityCrossing(inc.severity_grid, carry + pen)};
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

  const api = {lif, positionLoss, oracleFalls, slippageAt, decide, breakEven, inject, decideAt, breakEvenSeverity,
               vaultDecide, vaultRun, vaultLossAt, vaultDecideAt};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.RiskModel = api;
})(typeof window !== 'undefined' ? window : this);
