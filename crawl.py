#!/usr/bin/env python3
"""
Generic on-chain dependency crawler: start from contracts, read their verified ABI (Etherscan), call every
view function that returns addresses, and follow the results layer by layer.

  RPC_URL=https://ethereum-rpc.publicnode.com python3 crawl.py 0xADDRESS [...] [--morpho-market 0xID] \
      [--depth 4] [--max-nodes 80] [--tag NAME]

Writes data/edges_<tag>.csv  (src, dst, type, weight_usd, evidence)  and  data/nodes_<tag>.json.
- Edge type = the function that returned the address (e.g. primaryOracle, BASE_FEED_1, asset).
- f(uint256) -> address with a matching fLength() is enumerated (e.g. VaultV2 adapters).
- Struct outputs: every address field becomes an edge named function.field.
- Edge kinds: data (followed), role (owner, curator, minter, gates, ...: EOAs / multisigs, key risk),
  operator (e.g. Chainlink transmitters: who reports a feed), infra (factories, bytecode stores, LINK).
  Only data edges are followed.
- --morpho-market adds the Morpho Blue market's idToMarketParams (loan, collateral, oracle, irm) as edges.
Every value is read at one pinned block. Needs pycryptodome (keccak256 for selectors; hashlib's sha3 is not keccak).
"""
import argparse
import csv
import json
import os
import re
import sys


import etherscan
from onchain_positions import MORPHO, RPC, words

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
ROLE = re.compile(r"(owner|admin|curator|guardian|sentinel|allocator|recipient|gate|manager|governance|"
                  r"registry|pauser|keeper|skim|timelock|feeTo|treasury|minter|blacklister|accesscontroller|"
                  r"billing|requester)", re.I)
OPERATOR = re.compile(r"(transmitter|forwarder|operator|signer)", re.I)
INFRA = re.compile(r"(creationcode|linktoken|factory)", re.I)


def kind_of(fn):
    """data edges are followed; the others are recorded only."""
    return ("operator" if OPERATOR.search(fn) else "infra" if INFRA.search(fn)
            else "role" if ROLE.search(fn) else "data")
ZERO = "0x" + "0" * 40


def sel(sig):
    from Crypto.Hash import keccak      # imported here: modules that only import crawl run without pycryptodome
    return keccak.new(digest_bits=256, data=sig.encode()).hexdigest()[:8]


def sig_of(f):
    def t(x):
        if x["type"].startswith("tuple"):
            return "(" + ",".join(t(c) for c in x["components"]) + ")" + x["type"][5:]
        return x["type"]
    return f"{f['name']}({','.join(t(i) for i in f['inputs'])})"


def static_words(t):
    """Number of 32-byte words of a static ABI type, None if dynamic."""
    if t["type"] == "tuple":
        n = [static_words(c) for c in t["components"]]
        return None if None in n else sum(n)
    if t["type"].endswith("[]") or t["type"] in ("bytes", "string"):
        return None
    return 1


def addresses_in(outputs, hexdata):
    """[(label, address)] for address fields in static outputs and in a single address[] output."""
    w = words(hexdata) if hexdata and hexdata != "0x" else []
    out = []
    if len(outputs) == 1 and outputs[0]["type"] == "address[]" and len(w) >= 2:
        n = w[1] if w[0] == 32 else 0
        return [(f"[{i}]", "0x" + f"{w[2 + i]:040x}") for i in range(min(n, len(w) - 2))]
    pos = 0

    def walk(t, label):
        nonlocal pos
        if t["type"] == "tuple":
            for c in t["components"]:
                walk(c, f"{label}.{c['name']}" if label else c["name"])
            return
        if pos < len(w) and t["type"] == "address":
            out.append((label, "0x" + f"{w[pos]:040x}"))
        pos += 1

    if all(static_words(o) is not None for o in outputs):
        for o in outputs:
            walk(o, o.get("name") or "")
    return out


def returns_address(f):
    def has(t):
        return t["type"] in ("address", "address[]") or (t["type"] == "tuple" and any(has(c) for c in t["components"]))
    return any(has(o) for o in f["outputs"])


def morpho_market(rpc, block, market_id):
    """(loanToken, collateralToken, oracle, irm, lltv) of a Morpho Blue market id, None if it is not one."""
    try:
        v = words(rpc.eth_call(MORPHO, "0x" + sel("idToMarketParams(bytes32)") + market_id[2:], block))
    except RuntimeError:
        return None
    if len(v) < 5 or v[0] == 0:
        return None
    return ["0x" + f"{x:040x}" for x in v[:4]] + [v[4]]


def crawl(starts, rpc, block, depth, max_nodes, market_id=None, chain=1, log=print):
    nodes, edges, queue, seen = {}, [], [(a.lower(), 0) for a in starts], set()
    ev_call = lambda fn: f"eth_call {fn} @ block {block}; ABI from Etherscan verified source"

    def add_market(mid, d, src=None, src_label=None, weight=None):
        p = morpho_market(rpc, block, mid)
        if p is None:
            return False
        key = f"morpho_market:{mid[:10]}"
        if src:
            edges.append({"src": src, "dst": key, "type": src_label, "kind": "data", "weight_usd": weight,
                          "evidence": ev_call(src_label)})
        if key in nodes:
            return True
        nodes[key] = {"address": MORPHO.lower(), "name": "Morpho Blue market", "market_id": mid,
                      "lltv": p[4] / 1e18, "kind": "morpho_market", "depth": d}
        log(f"{'  ' * d}{key} lltv {p[4] / 1e18:g}")
        for name, a in zip(("loanToken", "collateralToken", "oracle", "irm"), p[:4]):
            edges.append({"src": key, "dst": a, "type": f"marketParams.{name}", "kind": "data", "weight_usd": None,
                          "evidence": f"eth_call Morpho.idToMarketParams({mid[:10]}...) @ block {block}"})
            if a != ZERO:
                queue.append((a, d + 1))
        return True

    if market_id:
        add_market(market_id, 0)
    while queue and len(nodes) < max_nodes:
        a, d = queue.pop(0)
        if a in seen or a == ZERO:
            continue
        seen.add(a)
        code = rpc.call("eth_getCode", [a, hex(block)])
        if code in ("0x", "0x0", None):
            nodes[a] = {"address": a, "name": None, "kind": "eoa", "depth": d}
            continue
        try:
            info = etherscan.describe(a, chain)
        except RuntimeError as e:
            nodes[a] = {"address": a, "name": None, "kind": "contract", "verified": False, "depth": d,
                        "note": str(e)[:120]}
            continue
        abi = info.get("implementation_abi") or info.get("abi") or []
        nodes[a] = {"address": a, "name": info.get("implementation_name") or info["contract_name"],
                    "contract_name": info["contract_name"], "kind": "contract", "verified": info["verified"],
                    "proxy": info["proxy"], "implementation": info["implementation"], "depth": d}
        log(f"{'  ' * d}{a} {nodes[a]['name']}")
        if d >= depth:
            continue
        fns = [f for f in abi if f.get("type") == "function" and f.get("stateMutability") in ("view", "pure")
               and returns_address(f)]
        names = {f["name"]: f for f in abi if f.get("type") == "function"}
        # f(uint256) -> bytes32 with fLength(): ids; those that are Morpho Blue markets become market nodes,
        # weighted by expectedSupplyAssets(id) when the contract has it (loan-token units; USDC ~ USD)
        for f in abi:
            if (f.get("type") == "function" and [i["type"] for i in f["inputs"]] == ["uint256"]
                    and [o["type"] for o in f["outputs"]] == ["bytes32"] and f["name"] + "Length" in names):
                try:
                    n = words(rpc.eth_call(a, "0x" + sel(sig_of(names[f["name"] + "Length"])), block))[0]
                except RuntimeError:
                    continue
                for i in range(min(n, 50)):
                    mid = rpc.eth_call(a, "0x" + sel(sig_of(f)) + f"{i:064x}", block)
                    w = None
                    if "expectedSupplyAssets" in names:
                        try:
                            raw = words(rpc.eth_call(a, "0x" + sel("expectedSupplyAssets(bytes32)") + mid[2:], block))[0]
                            p = morpho_market(rpc, block, mid)
                            dec = words(rpc.eth_call(p[0], "0x" + sel("decimals()"), block))[0] if p else 18
                            w = raw / 10 ** dec
                        except RuntimeError:
                            w = None
                    add_market(mid, d + 1, a, f"{f['name']}[{i}]", w)
        for f in fns:
            calls = []
            if not f["inputs"]:
                calls.append((f["name"], "0x" + sel(sig_of(f))))
            elif [i["type"] for i in f["inputs"]] == ["uint256"]:
                ln = names.get(f["name"] + "Length")
                if ln and not ln["inputs"]:
                    try:
                        n = words(rpc.eth_call(a, "0x" + sel(sig_of(ln)), block))[0]
                    except RuntimeError:
                        n = 0
                    calls += [(f"{f['name']}[{i}]", "0x" + sel(sig_of(f)) + f"{i:064x}") for i in range(min(n, 50))]
            for label, data in calls:
                try:
                    res = rpc.eth_call(a, data, block)
                except RuntimeError:
                    continue
                for field, dst in addresses_in(f["outputs"], res):
                    if dst == ZERO or dst == a:
                        continue
                    t = label + (f".{field}" if field and not field.startswith("[") else field)
                    kind = kind_of(f["name"] + "." + field if field else f["name"])
                    edges.append({"src": a, "dst": dst, "type": t, "kind": kind, "weight_usd": None,
                                  "evidence": ev_call(f"{nodes[a]['name']}.{label}")})
                    if kind == "data":
                        queue.append((dst, d + 1))
                    elif dst not in nodes:
                        nodes[dst] = {"address": dst, "name": None, "kind": f"{kind}_holder", "depth": d + 1}
    return nodes, edges


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("addresses", nargs="*")
    ap.add_argument("--morpho-market")
    ap.add_argument("--rpc", default=os.environ.get("RPC_URL", "https://ethereum-rpc.publicnode.com"))
    ap.add_argument("--depth", type=int, default=4)
    ap.add_argument("--max-nodes", type=int, default=80)
    ap.add_argument("--tag", default="crawl")
    a = ap.parse_args()
    if not a.addresses and not a.morpho_market:
        sys.exit("give start addresses and / or --morpho-market")
    rpc = RPC(a.rpc)
    block = int(rpc.call("eth_blockNumber", []), 16)
    print(f"pinned block {block}")
    nodes, edges = crawl(a.addresses, rpc, block, a.depth, a.max_nodes, a.morpho_market)
    path = os.path.join(DATA, f"edges_{a.tag}.csv")
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["src", "dst", "type", "kind", "weight_usd", "evidence"])
        w.writeheader()
        w.writerows(edges)
    with open(os.path.join(DATA, f"nodes_{a.tag}.json"), "w") as fh:
        json.dump({"block": block, "starts": a.addresses, "morpho_market": a.morpho_market, "nodes": nodes}, fh,
                  indent=1)
    from collections import Counter
    k = Counter(e["kind"] for e in edges)
    print(f"{len(nodes)} nodes, {len(edges)} edges ({', '.join(f'{n} {c}' for c, n in k.most_common())}) -> {path}")


if __name__ == "__main__":
    main()
