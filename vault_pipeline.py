#!/usr/bin/env python3
"""
Vault risk pipeline for a list of vaults in the RockawayX dashboard format
(vault_name, vault_address, token_name, chain, protocol, category, tvl_usd, apy).

  RPC_URL=https://ethereum-rpc.publicnode.com python3 vault_pipeline.py sample_data/rockawayx_vaults.csv \
      [--only 0xVAULT ...] [--deposit 1000000] [--alt-apy 0.04] [--horizon-days 30]

Routing, row by row:
  ethereum + morpho (VaultV2)  full: dependency graph, markets and allocations, every borrower, oracle types,
                               incidents per collateral / underlying, vault loss per outcome, exit tranches,
                               break-even and the manager sentence
  ethereum, other protocol     partial: dependency graph only (crawl.py), no loss numbers
  other EVM chains             not supported yet (needs an RPC for that chain), no numbers
  solana                       out of scope of the prototype, no numbers
Writes data/vaults/<address>.json, data/vaults/edges_<address[:10]>.csv and data/vaults_report.json.

Vault mechanics (VaultV2 verified source, Etherscan): exit() pays from idle assets, then deallocates from
liquidityAdapter / liquidityData; forceDeallocate(adapter, ...) frees assets from any adapter for a penalty
forceDeallocatePenalty[adapter]. Bad debt in a Morpho market is taken from all its suppliers pro rata
(Morpho.sol liquidate), so the vault's share of a market's bad debt = allocation / market total supply.
"""
import argparse
import csv
import json
import os
import re
import sys
import time


import crawl as crawl_mod
import etherscan
import incidents as inc_mod
import offchain
from loss_model import PRESETS, Position, Scenario, position_loss
from oracle_types import classify, oracle_falls
from onchain_positions import RPC, read_market, words
from reasoning import NUM, fmt

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
OUT = os.path.join(DATA, "vaults")
VOLATILE = {"weth", "eth", "wsteth", "steth", "wbtc", "cbbtc", "tbtc", "reth", "weeth", "cbeth", "lbtc"}
UNDER = re.compile(r"^(SY|yieldToken|asset|underlying|usde|assetInfo\.assetAddress)$")
GRADE = "ABCD"
worst = lambda *g: max(g, key=GRADE.index)


def parse_money(s):
    s = (s or "").strip().replace("$", "").replace(",", "")
    mult = {"k": 1e3, "m": 1e6, "b": 1e9}.get(s[-1:].lower(), 1)
    try:
        return float(s[:-1] if s[-1:].lower() in "kmb" else s) * mult
    except ValueError:
        return None


def parse_pct(s):
    s = (s or "").strip().replace("%", "")
    try:
        return float(s) / 100
    except ValueError:
        return None


def load_rows(path):
    with open(path) as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["tvl"] = parse_money(r.get("tvl_usd"))
        r["apy_f"] = parse_pct(r.get("apy"))
    return rows


def route(r):
    chain, proto = r["chain"].strip().lower(), r["protocol"].strip().lower()
    if chain == "ethereum" and proto == "morpho":
        return "full", None
    if chain == "ethereum":
        return "partial", f"protocol '{proto}' has no loss model here: dependency graph only, no numbers"
    if chain == "solana":
        return "out_of_scope", "Solana (Kamino) is outside the prototype: no reader for Solana accounts yet"
    return "not_supported", f"chain '{chain}' not wired yet (needs an RPC for it); no numbers"


def kc(hexdata):
    from Crypto.Hash import keccak      # imported here: check_js_port.py imports this module without pycryptodome
    return "0x" + keccak.new(digest_bits=256, data=bytes.fromhex(hexdata.replace("0x", ""))).hexdigest()


def _str(res):
    try:
        b = bytes.fromhex(res[2:])
        if len(b) == 32:
            return b.rstrip(b"\0").decode()
        n = int.from_bytes(b[32:64], "big")
        return b[64:64 + n].decode()
    except Exception:
        return None


def peg_types():
    p = os.path.join(DATA, "stablecoins", "stablecoins.json")
    if not os.path.exists(p):
        return {}
    with open(p) as f:
        return {(a.get("symbol") or "").lower(): a.get("pegType") for a in json.load(f)["peggedAssets"]}


def currency_of(sym):
    """USD / EUR / ETH from DeFiLlama's pegType (stablecoins.json), else a symbol rule; None if unknown."""
    s = (sym or "").lower()
    peg = peg_types().get(s)
    if peg == "peggedUSD":
        return "USD", "DeFiLlama pegType peggedUSD"
    if peg == "peggedEUR":
        return "EUR", "DeFiLlama pegType peggedEUR"
    if s in ("weth", "eth"):
        return "ETH", "symbol"
    if s.startswith("eur"):
        return "EUR", "symbol starts with EUR"
    return None, "unknown currency"


def stable_symbols():
    p = os.path.join(DATA, "stablecoins", "stablecoins.json")
    if not os.path.exists(p):
        return set()
    with open(p) as f:
        return {(a.get("symbol") or "").lower() for a in json.load(f)["peggedAssets"]}


def collateral_type(sym, cname, edge_types, stables):
    s = (sym or "").lower()
    if cname == "PendlePrincipalToken" or s.startswith("pt-"):
        return "pt"
    if s in VOLATILE:
        return "volatile"
    if s in stables:
        return "stablecoin"
    if "asset" in edge_types:
        return "yield_wrapper"
    return "rwa_or_credit"


def write_edges(path, edges):
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["src", "dst", "type", "kind", "weight_usd", "evidence"])
        w.writeheader()
        w.writerows(edges)


def path_to(edges, start, target):
    """Shortest data-edge path start -> target, as [(src, edge type, dst)]."""
    nxt = {}
    for e in edges:
        if e["kind"] == "data":
            nxt.setdefault(e["src"], []).append(e)
    prev, q, seen = {}, [start], {start}
    while q:
        a = q.pop(0)
        if a == target:
            break
        for e in nxt.get(a, []):
            if e["dst"] not in seen:
                seen.add(e["dst"])
                prev[e["dst"]] = e
                q.append(e["dst"])
    if target not in prev and target != start:
        return None
    out, x = [], target
    while x != start:
        e = prev[x]
        out.append((e["src"], e["type"], e["dst"]))
        x = e["src"]
    return list(reversed(out))


# ------------------------------------------------------------------ one vault
def analyze_vault(row, rpc, block, now, cfg, log=print):
    addr = row["vault_address"].lower()
    gates = []
    g = lambda ok, msg: gates.append({"pass": bool(ok), "check": msg}) or ok
    log(f"\n== {row['vault_name']} {addr}")
    nodes, edges = crawl_mod.crawl([addr], rpc, block, cfg["depth"], cfg["max_nodes"], log=lambda *_: None)
    os.makedirs(OUT, exist_ok=True)
    epath = os.path.join(OUT, f"edges_{addr[:10]}.csv")
    write_edges(epath, edges)
    symbols = {}
    name_of = lambda a: symbols.get(a) or (nodes.get(a) or {}).get("name") or a[:10]

    call = lambda to, sig, args="": rpc.eth_call(to, "0x" + crawl_mod.sel(sig) + args, block)
    asset = "0x" + call(addr, "asset()")[-40:]
    dec = words(call(asset, "decimals()"))[0]
    asset_sym = _str(call(asset, "symbol()"))
    total = words(call(addr, "totalAssets()"))[0] / 10 ** dec
    idle = words(call(asset, "balanceOf(address)", addr[2:].rjust(64, "0")))[0] / 10 ** dec
    liq_adapter = "0x" + call(addr, "liquidityAdapter()")[-40:]
    liq_mid = None
    if int(liq_adapter, 16):
        raw = call(addr, "liquidityData()")
        w = words(raw)
        if len(w) >= 7 and w[1] == 160:                     # bytes = abi.encode(MarketParams): 5 words
            liq_mid = kc(raw[2 + 128:2 + 128 + 320])

    # only markets held by this vault's own adapters: deeper in the graph, collateral that is itself a vault
    # (e.g. steakUSDC) brings its own adapters and markets, which are dependencies, not this vault's allocations
    own = {e["dst"] for e in edges if e["src"] == addr and re.fullmatch(r"adapters\[\d+\]", e["type"])} | {addr}
    markets, by_id = [], {}
    for e in edges:
        if e["dst"].startswith("morpho_market:") and e["weight_usd"] is not None and e["src"] in own:
            n = nodes[e["dst"]]
            if n["market_id"] in by_id:
                by_id[n["market_id"]]["allocation"] += e["weight_usd"]
                continue
            by_id[n["market_id"]] = {"key": e["dst"], "market_id": n["market_id"], "holder": e["src"],
                                     "allocation": e["weight_usd"], "lltv": n["lltv"]}
            markets.append(by_id[n["market_id"]])
    notes = []
    alloc_sum = sum(m["allocation"] for m in markets)
    g(total == 0 or abs((alloc_sum + idle) / total - 1) < 0.01,
      f"allocations {alloc_sum:,.0f} + idle {idle:,.0f} within 1% of totalAssets {total:,.0f} {asset_sym}")
    if liq_mid and not any(m["market_id"] == liq_mid for m in markets):
        notes.append(f"liquidity market {liq_mid[:10]} (from liquidityData) holds no allocation: withdrawals beyond "
                     f"idle assets need forceDeallocate")
    penalties = {}
    for m in markets:
        if m["holder"] not in penalties:
            penalties[m["holder"]] = words(call(addr, "forceDeallocatePenalty(address)", m["holder"][2:].rjust(64, "0")))[0] / 1e18
    gates_addr = {k: "0x" + call(addr, f"{k}()")[-40:] for k in ("sendSharesGate", "receiveAssetsGate")}
    restricted = {k: v for k, v in gates_addr.items() if int(v, 16)}

    stables = stable_symbols()
    cal_path = os.path.join(DATA, "depeg_calibration.json")
    cal = json.load(open(cal_path)) if os.path.exists(cal_path) else None
    presets = {s.key: s for s in PRESETS}
    if cal:
        presets["depeg_partial"] = inc_mod.depeg_partial(cal)
    types = {t["key"]: t for t in inc_mod.incident_types(cal)}
    cfg["severe_default"] = cal["median_loss_at_horizon"]["severe"] if cal else 0.5

    # ---- markets: borrowers, collateral, oracle
    for m in markets:
        if m["allocation"] < cfg["min_alloc"]:
            m["analyzed"] = False
            m["note"] = f"allocation below {cfg['min_alloc']:,.0f}: not analyzed"
            continue
        rm = read_market(rpc, block, m["market_id"], log=lambda *_: None)
        p = rm["market_params"]
        col = p["collateral_token"]
        etypes = {e["type"] for e in edges if e["src"] == col and e["kind"] == "data"}
        sym = _str(call(col, "symbol()"))
        symbols[col] = sym
        m.update(analyzed=True, read=rm, collateral=col, collateral_symbol=sym,
                 collateral_contract=(nodes.get(col) or {}).get("name"),
                 collateral_type=collateral_type(sym, (nodes.get(col) or {}).get("name"), etypes, stables),
                 oracle=classify(p["oracle"], rpc, block, now, collateral_symbol=sym),
                 supply=rm["market"]["total_supply_assets_usdc"], borrow=rm["market"]["total_borrow_assets_usdc"],
                 liquidity=rm["market"]["liquidity_usdc"],
                 share_of_market=m["allocation"] / rm["market"]["total_supply_assets_usdc"]
                 if rm["market"]["total_supply_assets_usdc"] else 0.0)
        g(rm["all_gates_pass"], f"market {m['market_id'][:10]} ({sym}): " +
          "; ".join(x["check"] for x in rm["gates"]))
        log(f"  market {m['market_id'][:10]} {sym:22s} {m['collateral_type']:13s} alloc {m['allocation']:>13,.0f} "
            f"({m['allocation'] / total:6.1%} of vault, {m['share_of_market']:6.1%} of market)  oracle "
            f"{m['oracle']['kind']}: market={m['oracle']['tracks_market']} underlying={m['oracle']['tracks_underlying']}")

    live = [m for m in markets if m.get("analyzed")]
    # ---- incidents: each collateral, plus stablecoin underlyings reached through the graph
    def underlyings(col):
        out, q, seen = [], [col], {col}
        while q:
            a = q.pop(0)
            for e in edges:
                if e["src"] == a and e["kind"] == "data" and UNDER.match(re.sub(r"\[\d+\]$", "", e["type"])) \
                        and e["dst"] not in seen:
                    seen.add(e["dst"])
                    out.append(e["dst"])
                    q.append(e["dst"])
        return out

    incidents = []
    tokens = {}
    for m in live:
        tokens.setdefault(m["collateral"], {"symbol": m["collateral_symbol"], "type": m["collateral_type"],
                                            "markets": set()})["markets"].add(m["key"])
        for u in underlyings(m["collateral"]):
            try:
                sym = _str(call(u, "symbol()"))
            except RuntimeError:
                sym = None
            if sym and sym.lower() in stables and u != asset:
                tokens.setdefault(u, {"symbol": sym, "type": "underlying_stablecoin", "markets": set()})["markets"].add(m["key"])
    for tok, t in tokens.items():
        kinds = {"stablecoin": ["depeg"], "underlying_stablecoin": ["depeg"], "rwa_or_credit": ["issuer_default"],
                 "yield_wrapper": ["issuer_default"], "pt": ["pt_market_dip", "issuer_default"],
                 "volatile": []}[t["type"]]
        if not kinds:
            incidents.append({"key": f"volatile_crypto:{t['symbol']}", "token": tok, "symbol": t["symbol"],
                              "type": "volatile_crypto", "analyzed": False, "expected_loss": None,
                              "note": "no calibrated scenario for volatile crypto collateral (D): not analyzed"})
        for kind in kinds:
            incidents.append(incident(kind, tok, t, live, presets, types, total, cfg, edges, addr, name_of))

    # ---- the vault's own asset (EURCV, USDC, ...): its issuer can fail too; withdrawing does not remove that risk
    cur, cur_src = currency_of(asset_sym)
    if asset_sym and asset_sym.lower() in stables:
        incidents.append(asset_incident(asset, asset_sym, presets, types, addr, name_of, cfg))
    else:
        incidents.append({"key": f"asset_issuer:{asset_sym}", "token": asset, "symbol": asset_sym, "type": "asset_issuer",
                          "analyzed": False, "expected_loss": None,
                          "note": "vault asset is not a stablecoin: no calibrated issuer scenario (D), not analyzed"})

    # ---- exit tranches for a depositor of size cfg["deposit"]
    liq_m = next((m for m in markets if m["market_id"] == liq_mid), None)
    free = idle + (min(liq_m["allocation"], liq_m.get("liquidity", 0.0)) if liq_m and liq_m.get("analyzed") else 0.0)
    forced = [(min(m["allocation"], m.get("liquidity", 0.0)), penalties.get(m["holder"], 0.0))
              for m in live if m is not liq_m]
    dep = min(cfg["deposit"], total) if total else 0.0
    take = lambda amt: min(dep, amt)
    f_free = take(free) / dep if dep else 0.0
    f_forced = min(1 - f_free, take(sum(a for a, _ in forced)) / dep) if dep else 0.0
    pen = max([p for a, p in forced if a > 0] + [0.0])
    alt = cfg["alt_apy_by_currency"].get(cur or "USD")
    carry = max(0.0, (row["apy_f"] or 0.0) - alt) * cfg["horizon_days"] / 365
    exit_ = {"deposit": dep, "free_usd": free, "forced_usd": sum(a for a, _ in forced),
             "free_fraction": f_free, "forced_fraction": f_forced, "currency": cur, "currency_source": cur_src,
             "vault_free_fraction": free / total if total else 0.0,
             "vault_forced_fraction": min(1 - free / total, sum(a for a, _ in forced) / total) if total else 0.0,
             "locked_fraction": max(0.0, 1 - f_free - f_forced), "force_deallocate_penalty": pen,
             "carry_cost": carry, "cost_free": carry, "cost_forced": carry + pen,
             "vault_apy": row["apy_f"], "alt_apy": alt, "horizon_days": cfg["horizon_days"],
             "restricted_gates": restricted,
             "evidence": {"tranches": {"grade": "A", "source": f"idle balance, liquidityAdapter/liquidityData, market "
                                                               f"liquidity and forceDeallocatePenalty @ block {block}"},
                          "deposit": {"grade": "user input", "source": "amount invested, entered by the manager "
                                                                       f"(default {cfg['deposit']:,.0f})"},
                          "carry_cost": {"grade": "D", "source": f"(vault APY {row.get('apy')} from the input file - "
                                                                 f"alternative {cur or 'USD'} APY {alt:.2%} assumed) x "
                                                                 f"{cfg['horizon_days']} days / 365"}}}
    for inc in incidents:
        if inc.get("analyzed", True):
            inc["decision"] = vault_decide_at(inc, exit_, dep)
            inc["sensitivity"] = vault_sensitivity(inc, exit_, dep)
            sentence(inc, exit_)
    credit = [i for i in incidents if i.get("analyzed", True) and i["type"] != "asset_issuer"]
    worst_L = max([i["decision"]["L"] for i in credit] + [0.0])
    run = liquidity_run(exit_, dep, worst_L, next((i["key"] for i in credit if i["decision"]["L"] == worst_L), None))
    incidents.append({"key": "liquidity_run:Morpho", "type": "liquidity_run", "analyzed": True, "expected_loss": 0.0,
                      "layer": 5, "run": run, "decision_text": {"text": run["text"], "numbers": [], "unchecked": []},
                      "note": "other depositors withdraw first and take the free liquidity: no direct loss, but more of "
                              "your deposit stays locked, exposed to the worst credit incident"})
    unchecked = [n for i in incidents for n in (i.get("decision_text") or {}).get("unchecked", [])]
    g(not unchecked, "every number in the decision texts comes from the computed values"
      + (f": unchecked {unchecked}" if unchecked else ""))
    # worst incident: largest vault loss at its default severity, then the smallest break-even severity
    ranked = sorted([i for i in incidents if i.get("analyzed", True) and i["type"] not in ("liquidity_run", "asset_issuer")],
                    key=lambda i: (-i["decision"]["L"], i["decision"]["severity_break_even_free"] or 9))
    top = ranked[0] if ranked else None
    summary = (top["decision_text"]["text"] if top else "No analyzable incident for this vault.")
    return {
        "vault_name": row["vault_name"], "vault_address": addr, "coverage": "full", "block": block,
        "input": {k: row[k] for k in ("token_name", "chain", "protocol", "category", "tvl_usd", "apy")},
        "asset": asset, "asset_symbol": asset_sym, "total_assets": total, "idle": idle,
        "liquidity_market": liq_mid, "dependency_graph": {"edges_file": os.path.relpath(epath, HERE), "nodes": len(nodes),
                                                          "edges": len(edges),
                                                          "by_kind": {k: sum(e["kind"] == k for e in edges)
                                                                      for k in ("data", "role", "operator", "infra")}},
        "markets": [{k: v for k, v in m.items() if k != "read"} | (
            {"n_borrowers": (m["read"]["distribution"] or {}).get("n_borrowers", 0),
             "max_ltv": (m["read"]["distribution"] or {}).get("ltv_max"),
             "debt_within_1pct_of_liquidation": sum(b["borrow_usdc"] for b in m["read"]["borrowers"]
                                                    if 0 <= b["distance_to_liquidation"] < 0.01)}
            if m.get("analyzed") else {}) for m in markets],
        "dependency_chain": dependency_chain(addr, nodes, edges, live, incidents, asset, asset_sym, name_of),
        "offchain": offchain_of(live, asset, asset_sym),
        "incidents": incidents, "exit": exit_, "worst_incident": top and top["key"], "decision_text": summary,
        "default_decision": top and top.get("decision"),
        "notes": notes,
        "gates": gates, "all_gates_pass": all(x["pass"] for x in gates),
    }


def incident(kind, tok, t, live, presets, types, total, cfg, edges, vault, name_of):
    """Three outcomes of an incident on token tok; vault loss per outcome from every borrower of every affected market."""
    if kind == "pt_market_dip":
        base, layer = types["oracle_dip"], 3
        outcomes = base["outcomes"]
        probs, pev = base["probabilities"], base["probability_evidence"]
    else:
        base, layer = types["underlying_depeg"], 2
        outcomes = dict(base["outcomes"])
        if kind == "issuer_default":
            outcomes["resolved"] = None
        probs = base["probabilities"]
        pev = dict(base["probability_evidence"])
        if kind == "issuer_default":
            pev = {"grade": pev["grade"], "source": "stablecoin depeg outcome frequencies used by analogy for an issuer "
                                                    "failure of " + (t["symbol"] or tok) + ": " + pev["source"]}
    affected = [m for m in live if m["key"] in t["markets"]]
    token = t["symbol"] if kind == "depeg" and t["type"] == "underlying_stablecoin" else None

    def vault_loss(sc):
        """(L_low, L_high, per-market rows): bad debt of every real borrower x the vault's share of each market."""
        per, lo_sum, hi_sum = [], 0.0, 0.0
        for m in affected:
            # the failing asset: for an underlying incident it is the underlying token, not the collateral
            falls = oracle_falls(m["oracle"], layer, sc.shock, sc.hours, token)
            br = {}
            for b in m["read"]["borrowers"]:
                if b["borrow_usdc"] <= 0:
                    continue
                pos = Position(b["address"], b["collateral_usdc"], b["borrow_usdc"], m["lltv"], True,
                               falls if layer == 2 else None, falls if layer == 3 else None)
                for x in position_loss(sc, pos)["branches"]:
                    br[x["oracle_falls"]] = br.get(x["oracle_falls"], 0.0) + x["bad_debt_usd"]
            bd = list(br.values()) or [0.0]
            v_lo, v_hi = min(bd) * m["share_of_market"], max(bd) * m["share_of_market"]
            lo_sum, hi_sum = lo_sum + v_lo, hi_sum + v_hi
            per.append({"market": m["key"], "collateral": m["collateral_symbol"], "oracle_falls": falls,
                        "market_bad_debt_low": min(bd), "market_bad_debt_high": max(bd),
                        "vault_share_of_market": m["share_of_market"], "vault_loss_low": v_lo, "vault_loss_high": v_hi})
        return (lo_sum / total, hi_sum / total, per) if total else (0.0, 0.0, per)

    rows, dist = [], []
    for o in ("resolved", "partial", "severe"):
        key, p = outcomes[o], probs[o]
        if key is None:
            L = 0.0 if o == "resolved" else None
            rows.append({"outcome": o, "preset": None, "probability": p, "L_low": L, "L_high": L, "per_market": []})
            if L is not None:
                dist.append((p, L))
            continue
        sc = presets[key]
        L_lo, L_hi, per = vault_loss(sc)
        rows.append({"outcome": o, "preset": key, "shock": sc.shock, "hours": sc.hours, "probability": p,
                     "L_low": L_lo, "L_high": L_hi, "per_market": per, "source": sc.source})
        dist.append((p, L_hi))
    exp = sum(p * L for p, L in dist)
    cv, var = inc_mod.tail(dist)
    paths = []
    for m in affected:
        pth = path_to(edges, vault, tok)
        if pth:
            paths.append(" -> ".join([name_of(vault)] + [f"[{t_}] {name_of(d)}" for _, t_, d in pth]))
    g_or = worst(*[m["oracle"]["evidence"]["grade"] for m in affected]) if affected else "D"
    sev = next(r for r in rows if r["outcome"] == ("severe" if outcomes["severe"] else "partial"))
    # vault loss at any severity (no probability): L(s) on a grid, from every real borrower
    perm = 0.0 if kind == "pt_market_dip" else 1.0
    grid = []
    for sv in SEVERITY_GRID:
        lo, hi, _ = vault_loss(Scenario("grid", layer, sv, perm, None, "", True))
        grid.append({"severity": sv, "L_low": lo, "L_high": hi})
    # incident duration: the loss only changes where a meta-oracle of an affected market can switch (its challenge
    # timelock), so one grid per duration segment is exact; and per "recovers after the incident" or not
    starts = [0.0] + sorted({m["oracle"]["challenge_timelock_s"] / 3600 for m in affected
                             if m["oracle"].get("kind") == "meta_oracle_timelock" and m["oracle"].get("challenge_timelock_s")})
    dgrids = []
    for h in starts:
        for rec in (False, True):
            pts = []
            for sv in SEVERITY_GRID:
                lo, hi, _ = vault_loss(Scenario("grid", layer, sv, 0.0 if rec else perm, h, "", True))
                pts.append({"severity": sv, "L_low": lo, "L_high": hi})
            dgrids.append({"from_hours": h, "recovers": rec, "grid": pts})
    return {"key": f"{kind}:{(t['symbol'] or tok)}", "type": kind, "token": tok, "symbol": t["symbol"], "layer": layer,
            "severity_grid": grid, "duration_grids": dgrids, "permanent": perm, **severity_defaults(kind, presets, cfg),
            "affected_markets": [m["key"] for m in affected],
            "affected_allocation": sum(m["allocation"] for m in affected), "propagation_paths": paths,
            "outcomes": rows, "expected_loss": exp, "tail_loss_95": cv, "var_95": var,
            "worst_outcome": sev["outcome"], "L_worst": sev["L_high"],
            "evidence": {"probabilities": pev,
                         "L": {"grade": worst("C", g_or, "A", "B", "D" if layer == 2 and outcomes["severe"] else "C"),
                               "basis": {"shock": "C", "oracle": g_or, "borrowers_and_allocations": "A",
                                         "liquidation_rules": "B", "recovery": "D"},
                               "source": "loss_model per real borrower x vault share of each affected market"}}}


SEVERITY_GRID = [0.005, 0.01, 0.02, 0.03, 0.05, 0.075, 0.1, 0.15, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.99, 1.0]


def severity_defaults(kind, presets, cfg):
    """Default severity of an incident (historical anchor) and the anchors shown on the slider."""
    if kind == "pt_market_dip":
        o = presets["oracle_dip"]
        return {"default_severity": o.shock,
                "severity_anchors": [{"severity": o.shock, "label": "PT-reUSD market dip, 25 Aug 2026", "grade": "C"}]}
    anchors = [{"severity": presets["usde_mild"].shock, "label": "USDe daily low, Feb 2026 (recovered)", "grade": "C"}]
    if "depeg_partial" in presets:
        anchors.append({"severity": presets["depeg_partial"].shock, "label": "median day-30 loss, partial depegs", "grade": "C"})
    anchors += [{"severity": presets["issuer_half"].shock, "label": "Stream xUSD, Nov 2025", "grade": "C"},
                {"severity": cfg["severe_default"], "label": "median day-30 loss, severe depegs", "grade": "C"},
                {"severity": presets["issuer_total"].shock, "label": "Elixir deUSD, Nov 2025", "grade": "C"}]
    return {"default_severity": cfg["severe_default"], "severity_anchors": anchors}


def L_at(grid, sev):
    """L_high at severity sev, linear between grid points, 0 at severity 0."""
    pts = [(0.0, 0.0)] + [(g["severity"], g["L_high"]) for g in grid]
    if sev >= pts[-1][0]:
        return pts[-1][1]
    for (s0, l0), (s1, l1) in zip(pts, pts[1:]):
        if sev <= s1:
            return l0 + (l1 - l0) * (sev - s0) / (s1 - s0)
    return pts[-1][1]


def severity_crossing(grid, c):
    """Smallest severity with L(s) > c (linear between grid points); None if never."""
    pts = [(0.0, 0.0)] + [(g["severity"], g["L_high"]) for g in grid]
    for (s0, l0), (s1, l1) in zip(pts, pts[1:]):
        if l1 > c:
            return s0 if l0 > c else s0 + (c - l0) * (s1 - s0) / (l1 - l0)
    return None


def duration_grid(inc, hours, recovers):
    """The severity grid for an incident lasting `hours` (None = lasting, i.e. the full severity_grid)."""
    if hours is None or not inc.get("duration_grids"):
        return inc["severity_grid"]
    cands = [g for g in inc["duration_grids"] if g["recovers"] == bool(recovers) and g["from_hours"] <= hours]
    return max(cands, key=lambda g: g["from_hours"])["grid"] if cands else inc["severity_grid"]


def vault_decide_at(inc, ex, amount, sev=None, alt_apy=None, horizon_days=None, low_branch=False, hours=None,
                    recovers=False):
    """Stay / exit for a depositor of `amount` given the incident at severity `sev` (no probability): withdraw
    each tranche whose unit cost (yield given up; + force-deallocation penalty) is below L(sev). Mirrored by
    RiskModel.vaultDecideAt."""
    sev = inc["default_severity"] if sev is None else sev
    alt = ex["alt_apy"] if alt_apy is None else alt_apy
    # with a duration, the yield given up is counted over the incident (you come back when it is over)
    h = (hours / 24 if hours is not None else ex["horizon_days"]) if horizon_days is None else horizon_days
    carry = max(0.0, (ex["vault_apy"] or 0.0) - alt) * h / 365
    pen = ex["force_deallocate_penalty"]
    base_grid = duration_grid(inc, hours, recovers)
    grid = [{"severity": g["severity"], "L_high": g["L_low"]} for g in base_grid] if low_branch else base_grid
    L = L_at(grid, sev)
    free_amt = min(amount, ex["free_usd"])
    forced_amt = min(amount - free_amt, ex["forced_usd"])
    locked = amount - free_amt - forced_amt
    out = {"amount": amount, "severity": sev, "L": L, "loss_if_stay_usd": L * amount, "carry_cost": carry,
           "penalty": pen, "free_usd": free_amt, "forced_usd": forced_amt, "locked_usd": locked,
           "severity_break_even_free": severity_crossing(grid, carry),
           "severity_break_even_forced": severity_crossing(grid, carry + pen)}
    if inc["type"] == "asset_issuer":
        out.update(verdict="REVIEW", exit_usd=0.0, exit_cost_usd=0.0, loss_kept_usd=L * amount,
                   total_if_act_usd=L * amount, avoided_usd=0.0)
        return out
    take_free, take_forced = L > carry, L > carry + pen
    exit_amt = free_amt * take_free + forced_amt * take_forced
    cost = free_amt * carry * take_free + forced_amt * (carry + pen) * take_forced
    kept = L * (amount - exit_amt)
    out.update(verdict="STAY" if exit_amt <= 0 else ("EXIT" if exit_amt >= amount - 1e-9 else "EXIT_PARTIAL"),
               exit_usd=exit_amt, exit_cost_usd=cost, loss_kept_usd=kept, total_if_act_usd=cost + kept,
               avoided_usd=L * amount - cost - kept)
    return out


VAULT_DURATIONS_H = [1, 6, 12, 16, 24, 48, 72, 168, 336, 720, 1440, 2160, 4320]


def vault_timeline(inc, ex, amount, sev=None, recovers=True, alt_apy=None):
    """vault_decide_at over incident durations (1 h .. 6 months, plus the meta-oracle switch points)."""
    hs = sorted(set(VAULT_DURATIONS_H + [g["from_hours"] for g in inc.get("duration_grids", []) if g["from_hours"] > 0]))
    out = []
    for h in hs:
        r = vault_decide_at(inc, ex, amount, sev, alt_apy, None, False, h, recovers)
        r.update(hours=h, days=h / 24, recovers=recovers)
        out.append(r)
    return out


def vault_timeline_summary(inc, rows):
    """Does the duration change the vault verdict? Change points with their reason, or why the timeline is flat.
    Mirrored by RiskModel.vaultTimelineSummary."""
    switches = {g["from_hours"] for g in inc.get("duration_grids", []) if g["from_hours"] > 0}
    changes = []
    for a, b in zip(rows, rows[1:]):
        if a["verdict"] == b["verdict"]:
            continue
        if any(a["hours"] < h <= b["hours"] for h in switches):
            why = "a meta-oracle of an affected market switches (challenge timelock reached)"
        elif abs(a["L"] - b["L"]) < 1e-12:
            why = "the yield given up grows with the duration"
        else:
            why = "the vault loss changes with the duration"
        changes.append({"from_hours": a["hours"], "to_hours": b["hours"], "verdict_before": a["verdict"],
                        "verdict_after": b["verdict"], "reason": why})
    flat = None
    if not changes:
        flat = ("no affected market has an oracle timer, so the duration does not change the loss; the verdict depends "
                "on the severity and on whether the loss recovers" if not switches else
                "the verdict is the same at every duration on the grid")
    return {"duration_matters": bool(changes), "changes": changes,
            "verdict": rows[0]["verdict"] if rows and not changes else None, "why_flat": flat}


def vault_sensitivity(inc, ex, amount, sev=None):
    """Which assumption flips the vault verdict at severity sev (no probability); weakest = lowest-graded flip
    (ties: larger change). The larger deposit is a comparison (the user's choice), never chosen as weakest.
    Mirrored by RiskModel.vaultSensitivity."""
    base = vault_decide_at(inc, ex, amount, sev)
    g_or = ((inc.get("evidence") or {}).get("L") or {}).get("basis", {}).get("oracle", "D")
    cands = [("oracle", "the lending oracles do not follow the shock (lower loss branch)", g_or,
              dict(low_branch=True)),
             ("alt_yield", "cash earns nothing after withdrawing (alternative yield 0%)", "D", dict(alt_apy=0.0)),
             ("alt_yield", "cash earns as much as the vault (no yield given up)", "D", dict(alt_apy=ex["vault_apy"] or 0.0)),
             ("horizon", "horizon 7 days", "D", dict(horizon_days=7)),
             ("horizon", "horizon 90 days", "D", dict(horizon_days=90)),
             ("amount", "a deposit 10 times larger", "D", dict(amount=amount * 10))]
    rows = []
    for key, alt, grade, kw in cands:
        amt = kw.pop("amount", amount)
        r = vault_decide_at(inc, ex, amt, base["severity"], **kw)
        rows.append({"key": key, "alternative": alt, "grade": grade, "verdict": r["verdict"], "comparison": key == "amount",
                     "exit_share": r["exit_usd"] / amt if amt else 0.0, "L": r["L"],
                     "flips": r["verdict"] != base["verdict"],
                     "effect": abs((r["exit_usd"] / amt if amt else 0) - (base["exit_usd"] / amount if amount else 0))
                     + abs(r["L"] - base["L"])})
    flips = [x for x in rows if x["flips"] and not x["comparison"]]
    weakest = None
    if flips:
        g = max(x["grade"] for x in flips)
        weakest = max((x for x in flips if x["grade"] == g), key=lambda x: x["effect"])
    return {"verdict": base["verdict"], "candidates": rows, "weakest": weakest}


def asset_incident(asset, sym, presets, types, vault, name_of, cfg=None):
    """The vault's own asset fails (e.g. EURCV, USDC). Every depositor loses the asset's fall: L = shock x permanent
    (the vault holds and lends that asset). Withdrawing returns the same asset, so it does not remove the risk."""
    base = types["underlying_depeg"]
    rows, dist = [], []
    for o in ("resolved", "partial", "severe"):
        key, p = base["outcomes"][o], base["probabilities"][o]
        sc = presets[key]
        L = sc.shock * sc.permanent
        rows.append({"outcome": o, "preset": key, "shock": sc.shock, "hours": sc.hours, "probability": p,
                     "L_low": L, "L_high": L, "per_market": [], "source": sc.source})
        dist.append((p, L))
    cv, var = inc_mod.tail(dist)
    return {"key": f"asset_issuer:{sym}", "type": "asset_issuer", "token": asset, "symbol": sym, "layer": 2,
            "severity_grid": [{"severity": sv, "L_low": sv, "L_high": sv} for sv in SEVERITY_GRID], "permanent": 1.0,
            "duration_grids": [{"from_hours": 0.0, "recovers": rec, "grid": [{"severity": sv, "L_low": 0.0 if rec else sv,
                                                                              "L_high": 0.0 if rec else sv}
                                                                             for sv in SEVERITY_GRID]}
                               for rec in (False, True)],
            **severity_defaults("asset_issuer", presets, cfg),
            "affected_markets": [], "affected_allocation": None,
            "propagation_paths": [f"Ethereum -> {name_of(vault)} -> [asset] {sym} -> [issued by] {sym} issuer (off-chain)"],
            "outcomes": rows, "expected_loss": sum(p * L for p, L in dist), "tail_loss_95": cv, "var_95": var,
            "worst_outcome": "severe", "L_worst": rows[-1]["L_high"],
            "note": "second-order effects on borrowers (debt in the same asset) not modelled",
            "evidence": {"probabilities": base["probability_evidence"],
                         "L": {"grade": "C", "basis": {"shock": "C", "recovery": "D"},
                               "source": "shock x permanent of the preset, applied to the whole deposit"}}}


def vault_decide(inc, ex, amount, p_worst=None, alt_apy=None, horizon_days=None):
    """Stay / exit for a depositor of `amount` (vault asset units ~ USD) given one incident. p_worst overrides the
    probability of the worst outcome; the partial outcome keeps its default ratio to it. Mirrored by
    RiskModel.vaultDecide in web/risk_model.js (check_js_port.py)."""
    alt = ex["alt_apy"] if alt_apy is None else alt_apy
    h = ex["horizon_days"] if horizon_days is None else horizon_days
    carry = max(0.0, (ex["vault_apy"] or 0.0) - alt) * h / 365
    pen = ex["force_deallocate_penalty"]
    o = {x["outcome"]: x for x in inc["outcomes"]}
    w = inc["worst_outcome"]
    Lw = o[w]["L_high"] or 0.0
    pw0 = o[w]["probability"] or 0.0
    pw = pw0 if p_worst is None else p_worst
    other = "partial" if w == "severe" else None
    ratio = (o[other]["probability"] / pw0) if other and pw0 and o[other]["L_high"] is not None else 0.0
    Lo = o[other]["L_high"] if other and o[other]["L_high"] is not None else 0.0
    po = min(ratio * pw, 1 - pw)
    el = pw * Lw + po * Lo
    free_amt = min(amount, ex["free_usd"])
    forced_amt = min(amount - free_amt, ex["forced_usd"])
    locked_amt = amount - free_amt - forced_amt
    out = {"amount": amount, "p_worst": pw, "p_other": po, "worst_outcome": w, "L_worst": Lw, "L_other": Lo,
           "expected_loss": el, "stay_loss_usd": el * amount, "carry_cost": carry, "penalty": pen,
           "free_usd": free_amt, "forced_usd": forced_amt, "locked_usd": locked_amt,
           "p_break_even": (carry / (Lw + ratio * Lo)) if (Lw + ratio * Lo) > 0 else None,
           "p_break_even_worst_alone": (carry / Lw) if Lw > 0 else None}
    if inc["type"] == "asset_issuer":
        out.update(verdict="REVIEW", exit_usd=0.0, exit_cost_usd=0.0, loss_if_exit_usd=el * amount,
                   text=f"Given {inc['key']}: withdrawing returns {inc['symbol']}, so it does not remove this risk "
                        f"(expected loss {el:.2%} of the deposit). Only swapping out of {inc['symbol']} does, at a cost "
                        f"not measured here.")
        return out
    take_free = el > carry
    take_forced = el > carry + pen
    exit_amt = free_amt * take_free + forced_amt * take_forced
    cost = free_amt * carry * take_free + forced_amt * (carry + pen) * take_forced
    verdict = "STAY" if exit_amt <= 0 else ("EXIT" if exit_amt >= amount - 1e-9 else "EXIT_PARTIAL")
    out.update(verdict=verdict, exit_usd=exit_amt, exit_cost_usd=cost,
               loss_if_exit_usd=el * (amount - exit_amt) + cost,
               text=(f"Exiting {exit_amt:,.0f} now costs {cost:,.0f} (yield given up"
                     + (" and the force-deallocation penalty" if take_forced and forced_amt > 0 else "") +
                     f"), while staying has an expected loss of {el * amount:,.0f}"
                     + (f"; {locked_amt:,.0f} cannot be withdrawn now." if locked_amt > 1e-9 else ".")
                     if exit_amt > 0 else
                     f"Staying has an expected loss of {el * amount:,.0f}, below the cost of exiting "
                     f"({carry:.3%} of the amount withdrawn: yield given up)."))
    return out


def liquidity_run(ex, amount, worst_el, worst_key):
    """Morpho liquidity incident: other depositors take a share of the free liquidity first."""
    rows = []
    for share in (0.0, 0.5, 1.0):
        free_amt = min(amount, ex["free_usd"] * (1 - share))
        forced_amt = min(amount - free_amt, ex["forced_usd"] * (1 - share))
        locked = amount - free_amt - forced_amt
        rows.append({"others_take": share, "free_usd": free_amt, "forced_usd": forced_amt, "locked_usd": locked,
                     "expected_loss_on_locked_usd": locked * worst_el})
    r = rows[-1]
    text = (f"If other depositors withdraw first and take the free liquidity, {r['locked_usd']:,.0f} of "
            f"{amount:,.0f} stays locked" + (f", losing {r['expected_loss_on_locked_usd']:,.0f} if {worst_key} hits "
                                              f"at its default severity" if worst_key else "") +
            f". Today {rows[0]['free_usd']:,.0f} can still leave without penalty.")
    return {"rows": rows, "worst_credit_incident": worst_key, "worst_expected_loss": worst_el,
            "worst_loss_at_default_severity": worst_el, "text": text,
            "evidence": {"grade": "D", "source": "share taken by other depositors is a scenario; free liquidity A"}}


def dependency_chain(vault, nodes, edges, live, incidents, asset, asset_sym, name_of):
    """The vault's dependencies as a chain from the settlement layer to the issuers."""
    roles = sorted({f"{e['type']}: {e['dst'][:10]}..." for e in edges if e["src"] == vault and e["kind"] == "role"})
    adapters = sorted({name_of(e["dst"]) for e in edges if e["src"] == vault and e["type"].startswith("adapters[")})
    return [
        {"layer": 1, "name": "Settlement chain", "items": [{"label": "Ethereum mainnet", "evidence": "A"}]},
        {"layer": 2, "name": "Vault", "items": [{"label": name_of(vault), "address": vault, "detail": "; ".join(roles[:6]),
                                                  "evidence": "A"}]},
        {"layer": 3, "name": "Protocol", "items": [{"label": "Morpho Blue", "address": "0xbbbbbbbbbb9cc5e90e3b3af64bdaf62c37eeffcb",
                                                    "detail": "adapters: " + ", ".join(adapters), "evidence": "A"}]},
        {"layer": 4, "name": "Markets", "items": [{"label": f"{m['collateral_symbol']} / {asset_sym} (LLTV {m['lltv']:g})",
                                                   "market_id": m["market_id"], "allocation": m["allocation"],
                                                   "detail": f"{m['read']['distribution']['n_borrowers'] if m['read']['distribution'] else 0} borrowers",
                                                   "evidence": "A"} for m in live]},
        {"layer": 5, "name": "Collateral and oracles", "items": [
            {"label": m["collateral_symbol"], "address": m["collateral"], "detail": f"{m['collateral_type']}; oracle "
             f"{m['oracle']['kind']} (follows market: {m['oracle']['tracks_market']}, underlying: "
             f"{m['oracle']['tracks_underlying']})", "evidence": m["oracle"]["evidence"]["grade"]} for m in live]},
        issuers_layer(live, incidents, asset, asset_sym),
    ]


def issuer_item(sym, address, role, blocks):
    """One issuer row of the chain: from offchain_deps.json when the token is listed (issuer, summary, number of sourced
    relations, grade D), else "off-chain, not verified"."""
    b = blocks.get(sym)
    if b is None or (b.get("address") and address and b["address"] != address.lower()):
        return {"label": f"{sym} issuer{role}", "detail": "off-chain, not verified", "evidence": "D"}
    c = b["counts"]
    return {"label": f"{sym} issuer{role}: {b['issuer']}", "detail": b["summary"], "evidence": "D", "offchain": sym,
            "sources": f"{c['relations']} relations from documents ({c['official']} official, {c['third_party']} "
                       f"third-party), {c['quotes_found']} quotes re-checked on their page"}


def offchain_of(live, asset, asset_sym, deps=None, check=None):
    """offchain_deps.json blocks of the vault asset and of every analysed collateral, keyed by symbol."""
    deps = deps or offchain.load()
    check = check if check is not None else offchain.load_check()
    out = {}
    for addr, sym in [(asset, asset_sym)] + [(m["collateral"], m["collateral_symbol"]) for m in live]:
        b = offchain.token_block(deps, check, address=addr)
        if b:
            out[sym] = b
    return out


def issuers_layer(live, incidents, asset, asset_sym, blocks=None):
    """Layer 6 of the dependency chain: the vault asset's issuer, stablecoin underlyings, collateral issuers."""
    blocks = offchain_of(live, asset, asset_sym) if blocks is None else blocks
    under = sorted({(i["symbol"], i["type"]) for i in incidents if i.get("type") in ("depeg",) and i.get("symbol")})
    return {"layer": 6, "name": "Underlying and issuers", "items":
            [issuer_item(asset_sym, asset, " (vault asset)", blocks)]
            + [{"label": f"{s} ({t})", "evidence": "A"} for s, t in under]
            + [issuer_item(m["collateral_symbol"], m["collateral"], "", blocks)
               for m in live if m["collateral_type"] in ("rwa_or_credit", "yield_wrapper", "pt")]}


def refresh_offchain(js_out=None, log=print):
    """Re-attach offchain_deps.json to the existing vault detail files (layer 6 and `offchain`) without re-reading the
    chain; rewrite the bundle when js_out is given."""
    deps, check = offchain.load(), offchain.load_check()
    n = 0
    for name in sorted(os.listdir(OUT)):
        if not (name.startswith("0x") and name.endswith(".json")):
            continue
        p = os.path.join(OUT, name)
        with open(p) as f:
            v = json.load(f)
        live = [m for m in v["markets"] if m.get("analyzed")]
        blocks = offchain_of(live, v["asset"], v["asset_symbol"], deps, check)
        v["offchain"] = blocks
        v["dependency_chain"] = [x for x in v["dependency_chain"] if x["layer"] != 6] + \
            [issuers_layer(live, v["incidents"], v["asset"], v["asset_symbol"], blocks)]
        edges_gate(v, attach_chain_edges(v))
        with open(p, "w") as f:
            json.dump(v, f, indent=1)
        n += 1
        log(f"  {v['vault_name']}: off-chain blocks for {', '.join(blocks) or 'none'}")
    if js_out:
        with open(os.path.join(DATA, "vaults_report.json")) as f:
            bundle_js(json.load(f), js_out)
    return n


def attach_chain_edges(v):
    """Give every dependency_chain item an `id` and set v["dependency_edges"]: the links between the items, the vault
    view's counterpart of the PT view's ui.edges ({from, to, type, grade, evidence}, from the dependency to what depends
    on it). Built from the detail's own fields (markets, incidents, chain items), no chain reads. Returns the problems
    found (ids not unique, an edge to an unknown item, an item without an edge); empty when consistent."""
    chain = {x["layer"]: x["items"] for x in v["dependency_chain"]}
    live = [m for m in v["markets"] if m.get("analyzed")]
    sym, block = v["asset_symbol"], v["block"]
    vid = f"vault:{v['vault_address'].lower()}"
    problems = []
    if len(chain[4]) != len(live) or len(chain[5]) != len(live):
        problems.append(f"layers 4 / 5 have {len(chain[4])} / {len(chain[5])} items for {len(live)} analysed markets")
        return problems
    chain[1][0]["id"], chain[2][0]["id"], chain[3][0]["id"] = "chain:ethereum", vid, "protocol:morpho_blue"
    for it, m in zip(chain[4], live):
        it["id"] = f"market:{m['market_id']}"
    for it, m in zip(chain[5], live):
        it["id"] = f"collateral:{m['market_id']}"
    under = sorted({(i["symbol"], i["type"]) for i in v["incidents"] if i.get("type") in ("depeg",) and i.get("symbol")})
    cissuers = [m for m in live if m["collateral_type"] in ("rwa_or_credit", "yield_wrapper", "pt")]
    l6 = [("asset", sym, None)] + [("underlying", s, None) for s, _ in under] + \
         [("issuer", m["collateral_symbol"], m) for m in cissuers]
    if len(chain[6]) != len(l6):
        problems.append(f"layer 6 has {len(chain[6])} items, expected {len(l6)}")
        return problems
    used = set()
    for it, (kind, s, m) in zip(chain[6], l6):
        i = f"underlying:{s}" if kind == "underlying" else f"issuer:{s}"
        if i in used:                                   # the same collateral in two markets: one issuer row each
            i = f"{i}:{m['market_id'][:10]}"
        used.add(i)
        it["id"] = i
    E = []

    def add(a, b, t, g, ev):
        E.append({"from": a, "to": b, "type": t, "grade": g, "evidence": ev})
    vault_item, proto = chain[2][0], chain[3][0]
    add("chain:ethereum", vid, "settlement", "A",
        f"{vault_item['label']} ({v['vault_address'].lower()}) is a contract on Ethereum mainnet, read at block {block}")
    add("protocol:morpho_blue", vid, "adapter", "A", f"{proto.get('detail')} (VaultV2.adapters, eth_call at block {block})")
    a_it = chain[6][0]
    add(a_it["id"], vid, "asset", a_it["evidence"],
        f"the vault holds and pays out {sym} ({v['asset']}); its issuer is off-chain"
        + (f" ({a_it['sources']})" if a_it.get("sources") else ", not verified"))
    by_key = {m["key"]: m for m in live}
    for m in live:
        add(f"market:{m['market_id']}", "protocol:morpho_blue", "allocation", "A",
            f"the vault's adapter {m['holder']} supplies {m['allocation']:,.0f} {sym} to this Morpho Blue market, "
            f"{m['share_of_market']:.2%} of its supply (block {block})")
        o = m.get("oracle") or {}
        add(f"collateral:{m['market_id']}", f"market:{m['market_id']}", "collateral", "A",
            f"marketParams.collateralToken = {m['collateral_symbol']} ({m['collateral']}), LLTV {m['lltv']:g}; "
            f"oracle {o.get('contract_name') or o.get('kind')} (grade {(o.get('evidence') or {}).get('grade', 'D')})")
    for it, (kind, s, m) in zip(chain[6], l6):
        if kind == "underlying":
            for inc in v["incidents"]:
                if inc.get("type") == "depeg" and inc.get("symbol") == s:
                    for k in inc.get("affected_markets") or []:
                        if k in by_key:
                            add(it["id"], f"collateral:{by_key[k]['market_id']}", "underlying", "A",
                                (inc.get("propagation_paths") or [f"{s} underlies {by_key[k]['collateral_symbol']}"])[0])
        elif kind == "issuer":
            who = it["label"].split(": ", 1)[1] if ": " in it["label"] else "not identified"
            add(it["id"], f"collateral:{m['market_id']}", "issuer", it["evidence"],
                f"{s} depends on its issuer ({who}); " + (it.get("sources") or it.get("detail") or "not verified"))
    ids = [it["id"] for items in chain.values() for it in items]
    # each incident's items on the chain, from where it starts to the vault (the page highlights these and the edges
    # between them); affected_markets says which markets it reaches
    l6_id = {(kind, s_): it["id"] for it, (kind, s_, _) in zip(chain[6], l6)}
    for inc in v["incidents"]:
        mk = [by_key[k] for k in inc.get("affected_markets") or [] if k in by_key] or \
            [m for m in live if inc.get("token") and inc["type"] != "asset_issuer"
             and m["collateral"].lower() == inc["token"].lower()]          # e.g. volatile_crypto: no affected_markets
        items = []
        if inc.get("type") == "asset_issuer":
            items = [l6_id.get(("asset", inc.get("symbol")))]
        elif inc.get("type") == "liquidity_run":
            items = ["protocol:morpho_blue"]
        elif inc.get("type") == "depeg":
            items = [l6_id.get(("underlying", inc.get("symbol")))]
        elif inc.get("type") == "issuer_default" and inc.get("symbol"):    # other types start at the collateral
            items = [i for i in ids if i == f"issuer:{inc['symbol']}" or i.startswith(f"issuer:{inc['symbol']}:")]
        for m in mk:
            items += [f"collateral:{m['market_id']}", f"market:{m['market_id']}"]
        if mk:
            items.append("protocol:morpho_blue")
        items.append(vid)
        inc["chain_items"] = [i for n, i in enumerate(items) if i and i not in items[:n]]
        problems += [f"incident {inc['key']}: unknown item {i}" for i in inc["chain_items"] if i not in set(ids)]
    if len(ids) != len(set(ids)):
        problems.append("item ids are not unique")
    known = set(ids)
    problems += [f"edge {e['from']} -> {e['to']} to an unknown item" for e in E if e["from"] not in known or e["to"] not in known]
    linked = {e["from"] for e in E} | {e["to"] for e in E}
    problems += [f"item {i} has no edge" for i in ids if i not in linked]
    v["dependency_edges"] = E
    return problems


def edges_gate(v, problems):
    """Record the dependency_edges check in the detail's gates (replacing an earlier one) and update all_gates_pass."""
    v["gates"] = [g for g in v["gates"] if not g["check"].startswith("dependency_edges:")]
    v["gates"].append({"pass": not problems, "check": "dependency_edges: " + ("; ".join(problems) or
                       f"{len(v.get('dependency_edges') or [])} edges, ids unique, every chain item linked")})
    v["all_gates_pass"] = all(g["pass"] for g in v["gates"])


def refresh_edges(js_out=None, log=print):
    """Add item ids and dependency_edges to the existing vault detail files (no chain reads, numbers unchanged);
    rewrite the bundle when js_out is given. Returns the number of files and the problems found."""
    n, bad = 0, []
    for name in sorted(os.listdir(OUT)):
        if not (name.startswith("0x") and name.endswith(".json")):
            continue
        p = os.path.join(OUT, name)
        with open(p) as f:
            v = json.load(f)
        if "dependency_chain" not in v:
            continue
        probs = attach_chain_edges(v)
        edges_gate(v, probs)
        bad += [f"{v['vault_name']}: {x}" for x in probs]
        with open(p, "w") as f:
            json.dump(v, f, indent=1)
        n += 1
        log(f"  {v['vault_name']}: {len(v.get('dependency_edges') or [])} edges"
            + (f"  PROBLEMS {probs}" if probs else ""))
    if js_out:
        with open(os.path.join(DATA, "vaults_report.json")) as f:
            bundle_js(json.load(f), js_out)
    return n, bad


def sentence(inc, ex):
    """Manager sentence at the incident's default severity; numbers only from the decision (checked)."""
    d, nums = inc["decision"], []

    def f(v, unit="fraction"):
        out = fmt(v, unit) if unit != "money" else f"{v:,.0f}"
        nums.append(out)
        return out
    cur = ex.get("currency") or ""
    name = inc["symbol"] or inc["key"]
    if inc["type"] == "asset_issuer":
        txt = (f"If {name} loses {f(d['severity'])}, every depositor loses {f(d['loss_if_stay_usd'], 'money')} {cur}. "
               f"Withdrawing returns {name}, so it does not remove this risk; only swapping out of {name} does, at a "
               f"cost not measured here.")
    elif d["verdict"] == "STAY":
        be = d["severity_break_even_free"]
        txt = (f"If {name} loses {f(d['severity'])}, staying loses {f(d['loss_if_stay_usd'], 'money')} {cur} "
               f"({f(d['L'])} of the deposit), less than the cost of exiting ({f(d['carry_cost'])} of the amount "
               f"withdrawn: yield given up). " + (f"Exiting pays once {name} loses more than {f(be)}." if be is not None
                                                  else "Exiting does not pay at any severity."))
    else:
        txt = (f"If {name} loses {f(d['severity'])}, staying loses {f(d['loss_if_stay_usd'], 'money')} {cur} "
               f"({f(d['L'])} of the deposit); exiting {f(d['exit_usd'], 'money')} now costs "
               f"{f(d['exit_cost_usd'], 'money')} {cur}"
               + (" including the force-deallocation penalty" if d["exit_usd"] > d["free_usd"] + 1e-9 and d["penalty"] > 0
                  else "") + "."
               + (f" {f(d['locked_usd'], 'money')} {cur} cannot be withdrawn now." if d["locked_usd"] > 1e-9 else "")
               + (f" Exiting pays once {name} loses more than {f(d['severity_break_even_free'])}."
                  if d["severity_break_even_free"] is not None else ""))
        if ex["vault_free_fraction"] < 0.999:
            txt += (f" Act early: if all depositors withdrew, only {f(ex['vault_free_fraction'])} of the vault could "
                    f"leave without penalty.")
    bad = [n for n in NUM.findall(txt.replace(inc["key"], "").replace(name, "")) if n not in nums]
    inc["decision_text"] = {"text": txt, "numbers": nums, "unchecked": bad}


def decide(inc, ex):
    L = inc["L_worst"]
    c = ex["cost_free"]
    nums = []

    def f(v, unit="fraction"):
        s = fmt(v, unit)
        nums.append(s)
        return s

    pen_txt = lambda: (f"at a {f(ex['force_deallocate_penalty'])} penalty" if ex["force_deallocate_penalty"] > 0
                       else "with no penalty")
    if L and L > 0 and c <= 0:
        inc["break_even"] = {"p_worst": 0.0, "exit_cost": c, "L_worst": L}
        txt = (f"Given {inc['key']}, exiting costs nothing here (vault APY {f(ex['vault_apy'])} is not above the assumed "
               f"{f(ex['alt_apy'])} alternative), so any probability of the {inc['worst_outcome']} outcome (vault loss "
               f"{f(L)}) favours exiting: withdraw the {f(ex['free_fraction'])} you can take out now")
        if ex["forced_fraction"] > 0:
            txt += f", and force out another {f(ex['forced_fraction'])} {pen_txt()}"
        txt += (f"; {f(ex['locked_fraction'])} stays locked until borrowers repay." if ex["locked_fraction"] > 1e-9
                else ".")
    elif not L or L <= 0:
        txt = (f"Given {inc['key']}, the {inc['worst_outcome']} outcome costs this vault nothing (no borrower is "
               f"left with bad debt), so staying is free whatever its probability.")
        inc["break_even"] = {"p_worst": None, "exit_cost": c, "L_worst": L}
    else:
        p = c / L
        inc["break_even"] = {"p_worst": p, "exit_cost": c, "L_worst": L}
        txt = (f"Given {inc['key']}, if you think the probability of the {inc['worst_outcome']} outcome (vault loss "
               f"{f(L)}) is above {f(p)}, withdraw the {f(ex['free_fraction'])} you can take out now (cost {f(c)}: "
               f"yield given up)")
        if ex["forced_fraction"] > 0:
            txt += f", and force out another {f(ex['forced_fraction'])} {pen_txt()}"
        txt += (f"; {f(ex['locked_fraction'])} stays locked until borrowers repay." if ex["locked_fraction"] > 1e-9
                else ".")
    if L and L > 0:
        if ex["vault_free_fraction"] < 0.999:
            txt += (f" Exit early: if all depositors withdrew, only {f(ex['vault_free_fraction'])} of the vault could "
                    f"leave without penalty.")
        if ex["restricted_gates"]:
            txt += " Withdrawals are gated (check the vault's gates first)."
    # token names are labels (e.g. PT-reUSD-10DEC2026), not computed numbers: leave them out of the check
    bad = [n for n in NUM.findall(txt.replace(inc["key"], "")) if n not in nums]
    inc["decision_text"] = {"text": txt, "numbers": nums, "unchecked": bad}


# ------------------------------------------------------------------ other routes
def partial(row, rpc, block, cfg):
    addr = row["vault_address"].lower()
    nodes, edges = crawl_mod.crawl([addr], rpc, block, 2, 40, log=lambda *_: None)
    os.makedirs(OUT, exist_ok=True)
    epath = os.path.join(OUT, f"edges_{addr[:10]}.csv")
    write_edges(epath, edges)
    root = nodes.get(addr, {})
    return {"contract": root.get("name"), "dependency_graph": {"edges_file": os.path.relpath(epath, HERE),
                                                              "nodes": len(nodes), "edges": len(edges)},
            "direct_dependencies": sorted({f"{e['type']}: {(nodes.get(e['dst']) or {}).get('name') or e['dst'][:10]}"
                                           for e in edges if e["src"] == addr})}


def bundle_js(report, path):
    """report + every full vault's detail file as window.VAULTS (second view of the front end)."""
    details = {}
    for v in report["vaults"]:
        if v["coverage"] == "full":
            with open(os.path.join(OUT, f"{v['vault_address'].lower()}.json")) as f:
                details[v["vault_address"].lower()] = json.load(f)
    with open(path, "w") as f:
        f.write("window.VAULTS = " + json.dumps({"report": report, "details": details}) + ";\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", nargs="?")
    ap.add_argument("--edges-only", action="store_true",
                    help="only add item ids and dependency_edges to the existing data/vaults files (no chain reads)")
    ap.add_argument("--offchain-only", action="store_true",
                    help="only re-attach offchain_deps.json to the existing data/vaults files (no chain reads)")
    ap.add_argument("--only", nargs="*", help="vault addresses to analyze (default: all)")
    ap.add_argument("--rpc", default=os.environ.get("RPC_URL", "https://ethereum-rpc.publicnode.com"))
    ap.add_argument("--deposit", type=float, default=1e7,
                    help="amount invested in the vault (vault asset units), entered by the manager; default 10,000,000")
    ap.add_argument("--alt-apy", "--alt-apy-usd", dest="alt_apy", type=float, default=0.04,
                    help="alternative yield for USD vaults (assumed)")
    ap.add_argument("--alt-apy-eur", type=float, default=0.02, help="alternative yield for EUR vaults (assumed)")
    ap.add_argument("--alt-apy-eth", type=float, default=0.03, help="alternative yield for ETH vaults (assumed)")
    ap.add_argument("--horizon-days", type=float, default=30)
    ap.add_argument("--min-alloc", type=float, default=1000.0, help="markets with less allocation are not analyzed")
    ap.add_argument("--depth", type=int, default=6)
    ap.add_argument("--max-nodes", type=int, default=150)
    ap.add_argument("--no-partial-crawl", action="store_true")
    ap.add_argument("--js-out", help="also write report + vault details as 'window.VAULTS = {...};' for the front end")
    a = ap.parse_args()
    if a.edges_only:
        n, bad = refresh_edges(a.js_out)
        print(f"GATE {'PASS' if not bad else 'FAIL'}  dependency_edges added to {n} vault files: ids unique, every edge "
              f"between known items, every chain item linked" + (f"  {bad[:3]}" if bad else "")
              + (f"; bundle -> {a.js_out}" if a.js_out else ""))
        sys.exit(1 if bad else 0)
    if a.offchain_only:
        n = refresh_offchain(a.js_out)
        print(f"off-chain dependencies re-attached to {n} vault files" + (f"; bundle -> {a.js_out}" if a.js_out else ""))
        return
    if not a.input:
        ap.error("input CSV required (unless --offchain-only)")
    cfg = vars(a)
    cfg["alt_apy_by_currency"] = {"USD": a.alt_apy, "EUR": a.alt_apy_eur, "ETH": a.alt_apy_eth}
    rows = load_rows(a.input)
    rpc = RPC(a.rpc)
    block = int(rpc.call("eth_blockNumber", []), 16)
    now = int(rpc.call("eth_getBlockByNumber", [hex(block), False])["timestamp"], 16)
    print(f"{len(rows)} vaults in {a.input}; pinned block {block}")
    report = []
    for r in rows:
        if a.only and r["vault_address"].lower() not in {x.lower() for x in a.only}:
            continue
        cov, why = route(r)
        base = {"vault_name": r["vault_name"], "vault_address": r["vault_address"], "chain": r["chain"],
                "protocol": r["protocol"], "tvl_usd": r["tvl"], "apy": r["apy_f"], "coverage": cov}
        t0 = time.time()
        try:
            if cov == "full":
                res = analyze_vault(r, rpc, block, now, cfg)
                edges_gate(res, attach_chain_edges(res))
                os.makedirs(OUT, exist_ok=True)
                with open(os.path.join(OUT, f"{r['vault_address'].lower()}.json"), "w") as f:
                    json.dump(res, f, indent=1)
                top = next((i for i in res["incidents"] if res["worst_incident"] and i.get("key") == res["worst_incident"]),
                           None)
                base.update(total_assets=res["total_assets"], markets=len(res["markets"]),
                            worst_incident=res["worst_incident"],
                            expected_loss=top and top["expected_loss"], tail_loss_95=top and top["tail_loss_95"],
                            free_fraction=res["exit"]["free_fraction"], locked_fraction=res["exit"]["locked_fraction"],
                            decision_text=res["decision_text"], all_gates_pass=res["all_gates_pass"],
                            verdict=(res["default_decision"] or {}).get("verdict"),
                            loss_if_stay_usd=(res["default_decision"] or {}).get("loss_if_stay_usd"),
                            severity=(res["default_decision"] or {}).get("severity"),
                            severity_break_even=(res["default_decision"] or {}).get("severity_break_even_free"),
                            exit_cost_usd=(res["default_decision"] or {}).get("exit_cost_usd"),
                            currency=res["exit"]["currency"],
                            detail=os.path.relpath(os.path.join(OUT, f"{r['vault_address'].lower()}.json"), HERE))
                print(f"  -> {res['decision_text']}  [{time.time() - t0:.0f}s, gates "
                      f"{sum(x['pass'] for x in res['gates'])}/{len(res['gates'])}]")
            elif cov == "partial" and not a.no_partial_crawl:
                base.update(note=why, **partial(r, rpc, block, cfg))
                print(f"\n== {r['vault_name']}: partial ({base.get('contract')}): {why}")
            else:
                base.update(note=why)
                print(f"\n== {r['vault_name']}: {cov}: {why}")
        except Exception as e:                        # one vault failing must not stop the others
            base.update(coverage="error", note=f"{type(e).__name__}: {str(e)[:200]}")
            print(f"\n== {r['vault_name']}: ERROR {base['note']}")
        report.append(base)
    out = {"block": block, "input": a.input, "assumptions": {"deposit": a.deposit, "alt_apy": a.alt_apy,
                                                             "alt_apy_by_currency": cfg["alt_apy_by_currency"],
                                                             "horizon_days": a.horizon_days},
           "coverage_counts": {c: sum(x["coverage"] == c for x in report)
                               for c in ("full", "partial", "not_supported", "out_of_scope", "error")},
           "vaults": report}
    with open(os.path.join(DATA, "vaults_report.json"), "w") as f:
        json.dump(out, f, indent=1)
    if a.js_out:
        bundle_js(out, a.js_out)
    print(f"\ncoverage: {out['coverage_counts']}  -> data/vaults_report.json")


if __name__ == "__main__":
    main()
