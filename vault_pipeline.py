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

from Crypto.Hash import keccak

import crawl as crawl_mod
import etherscan
import incidents as inc_mod
from loss_model import PRESETS, Position, position_loss
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
    carry = max(0.0, (row["apy_f"] or 0.0) - cfg["alt_apy"]) * cfg["horizon_days"] / 365
    exit_ = {"deposit": dep, "free_usd": free, "free_fraction": f_free, "forced_fraction": f_forced,
             "vault_free_fraction": free / total if total else 0.0,
             "vault_forced_fraction": min(1 - free / total, sum(a for a, _ in forced) / total) if total else 0.0,
             "locked_fraction": max(0.0, 1 - f_free - f_forced), "force_deallocate_penalty": pen,
             "carry_cost": carry, "cost_free": carry, "cost_forced": carry + pen,
             "vault_apy": row["apy_f"], "alt_apy": cfg["alt_apy"], "horizon_days": cfg["horizon_days"],
             "restricted_gates": restricted,
             "evidence": {"tranches": {"grade": "A", "source": f"idle balance, liquidityAdapter/liquidityData, market "
                                                               f"liquidity and forceDeallocatePenalty @ block {block}"},
                          "carry_cost": {"grade": "D", "source": f"(vault APY {row.get('apy')} from the input file - "
                                                                 f"alternative APY {cfg['alt_apy']:.2%} assumed) x "
                                                                 f"{cfg['horizon_days']} days / 365"}}}
    for inc in incidents:
        if inc.get("analyzed", True):
            decide(inc, exit_)
    unchecked = [n for i in incidents for n in (i.get("decision_text") or {}).get("unchecked", [])]
    g(not unchecked, "every number in the decision texts comes from the computed values"
      + (f": unchecked {unchecked}" if unchecked else ""))
    ranked = sorted([i for i in incidents if i.get("analyzed", True)], key=lambda i: -i["expected_loss"])
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
        "incidents": incidents, "exit": exit_, "worst_incident": top and top["key"], "decision_text": summary,
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
        per, lo_sum, hi_sum = [], 0.0, 0.0
        for m in affected:
            falls = oracle_falls(m["oracle"], layer, sc.shock, sc.hours)
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
        L_lo, L_hi = (lo_sum / total, hi_sum / total) if total else (0.0, 0.0)
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
    return {"key": f"{kind}:{(t['symbol'] or tok)}", "type": kind, "token": tok, "symbol": t["symbol"], "layer": layer,
            "affected_markets": [m["key"] for m in affected],
            "affected_allocation": sum(m["allocation"] for m in affected), "propagation_paths": paths,
            "outcomes": rows, "expected_loss": exp, "tail_loss_95": cv, "var_95": var,
            "worst_outcome": sev["outcome"], "L_worst": sev["L_high"],
            "evidence": {"probabilities": pev,
                         "L": {"grade": worst("C", g_or, "A", "B", "D" if layer == 2 and outcomes["severe"] else "C"),
                               "basis": {"shock": "C", "oracle": g_or, "borrowers_and_allocations": "A",
                                         "liquidation_rules": "B", "recovery": "D"},
                               "source": "loss_model per real borrower x vault share of each affected market"}}}


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


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("--only", nargs="*", help="vault addresses to analyze (default: all)")
    ap.add_argument("--rpc", default=os.environ.get("RPC_URL", "https://ethereum-rpc.publicnode.com"))
    ap.add_argument("--deposit", type=float, default=1e6, help="depositor size in the vault's asset")
    ap.add_argument("--alt-apy", type=float, default=0.04, help="yield of the alternative use of the cash (assumed)")
    ap.add_argument("--horizon-days", type=float, default=30)
    ap.add_argument("--min-alloc", type=float, default=1000.0, help="markets with less allocation are not analyzed")
    ap.add_argument("--depth", type=int, default=6)
    ap.add_argument("--max-nodes", type=int, default=150)
    ap.add_argument("--no-partial-crawl", action="store_true")
    a = ap.parse_args()
    cfg = vars(a)
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
                                                             "horizon_days": a.horizon_days},
           "coverage_counts": {c: sum(x["coverage"] == c for x in report)
                               for c in ("full", "partial", "not_supported", "out_of_scope", "error")},
           "vaults": report}
    with open(os.path.join(DATA, "vaults_report.json"), "w") as f:
        json.dump(out, f, indent=1)
    print(f"\ncoverage: {out['coverage_counts']}  -> data/vaults_report.json")


if __name__ == "__main__":
    main()
