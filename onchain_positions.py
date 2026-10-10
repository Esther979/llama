#!/usr/bin/env python3
"""
Every borrower of our Morpho Blue market, read from Ethereum over JSON-RPC (standard library only).

  RPC_URL=https://ethereum-rpc.publicnode.com python3 onchain_positions.py
  python3 onchain_positions.py --discover logs      # logs only (needs an RPC that serves old logs)
  python3 onchain_positions.py --wallet 0xA 0xB     # also read these wallets at the same block (PT held + Morpho)

Reads data/morpho_rest_markets_<pt[:10]>.json (market id, creation block, oracle, lltv; fetch_data.py step4),
data/morpho_markets_<pt[:10]>.json (API collateral in USD) and the exit-curve CSVs (capacity).
Writes data/morpho_positions_<id[:10]>.json. Every value is read at one pinned block.

Borrower discovery:
  logs  SupplyCollateral / Borrow events of the market, creation block -> head, in chunks.
  api   Morpho GraphQL marketPositions (addresses only; all amounts are then read on chain).
  auto  logs; if the RPC refuses old blocks (archive), api + logs over the recent blocks it does serve.
Whatever the source, the gate "sum of borrowShares == market totalBorrowShares" proves no borrower is missing.

Morpho rules (github.com/morpho-org/morpho-blue, src/Morpho.sol _isHealthy, libraries/SharesMathLib.sol,
libraries/ConstantsLib.sol, interfaces/IOracle.sol):
  borrowed = borrowShares.toAssetsUp(totalBorrowAssets, totalBorrowShares)
           = ceil(shares * (totalBorrowAssets + 1) / (totalBorrowShares + 1e6))
  healthy  <=>  collateral * price / 1e36 * lltv >= borrowed     (raw token units)
  price has 36 + loan decimals - collateral decimals decimals (1 collateral token in loan tokens)

Selectors and topic0 are keccak256 of the signatures (Id = bytes32). They were computed with pycryptodome 3.24.0
(Crypto.Hash.keccak; hashlib.sha3_256 is NOT keccak256) and are hard-coded below so this script needs only the
standard library; if pycryptodome is installed they are recomputed and compared at start. The run also checks
them against the chain: event layouts against real logs, call results against the Morpho API.
"""
import argparse
import csv
import glob
import json
import os
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
MORPHO = "0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb"   # docs.morpho.org/developers/contracts/addresses
MORPHO_GQL = "https://api.morpho.org/graphql"
LLAMA_COINS = "https://coins.llama.fi"      # same API as fetch_data.py (decimals / prices)
WETH = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
EXPECTED = {   # from the Morpho API (fetch_data.py step4); checked against idToMarketParams on chain
    "loan_token": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",          # USDC
    "collateral_token": "0xb195b618ea52b77cb2a58846f452f59f8dfa9390",    # PT-sUSDe-26NOV2026
    "oracle": "0xf8b29e7e9c00ce531434775f7923cc9fbca01b08",
    "lltv_wad": 915000000000000000,
}
SIG = {
    "position(bytes32,address)": "93c52062",
    "market(bytes32)": "5c60e39a",
    "idToMarketParams(bytes32)": "2c3c9157",
    "price()": "a035b1fe",
    "decimals()": "313ce567",
    "balanceOf(address)": "70a08231",
    "borrowRateView((address,address,address,address,uint256),(uint128,uint128,uint128,uint128,uint128,uint128))": "8c00bf6b",
    "SupplyCollateral(bytes32,address,address,uint256)":
        "a3b9472a1399e17e123f3c2e6586c23e504184d504de59cdaa2b375e880c6184",
    "Borrow(bytes32,address,address,address,uint256,uint256)":
        "570954540bed6b1304a87dfe815a5eda4a648f7097a16240dcd85c9b5fd42a43",
}
T_SUPPLY_COLL = "0x" + SIG["SupplyCollateral(bytes32,address,address,uint256)"]
T_BORROW = "0x" + SIG["Borrow(bytes32,address,address,address,uint256,uint256)"]
VIRTUAL_SHARES, VIRTUAL_ASSETS = 10 ** 6, 1
DROPS = [round(0.005 * i, 3) for i in range(1, 21)] + [round(0.01 * i, 2) for i in range(11, 41)]   # 0.5%..10%, 11%..40%

GATES = []


def gate(ok, msg):
    GATES.append({"pass": bool(ok), "check": msg})
    print(f"GATE {'PASS' if ok else 'FAIL'}  {msg}")
    return ok


def check_selectors():
    try:
        from Crypto.Hash import keccak
    except ImportError:
        return "hard-coded (computed with pycryptodome 3.24.0 keccak256; pycryptodome not installed here)"
    for sig, h in SIG.items():
        k = keccak.new(digest_bits=256, data=sig.encode()).hexdigest()
        if not k.startswith(h):
            sys.exit(f"selector mismatch for {sig}: {h} vs keccak {k}")
    return "recomputed with pycryptodome keccak256 at run time: all match"


# ------------------------------------------------------------------ JSON-RPC
class ArchiveError(Exception):
    pass


class RPC:
    def __init__(self, url):
        self.url = url
        self.n = 0

    def call(self, method, params, tries=6):
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
        for k in range(tries):
            self.n += 1
            req = urllib.request.Request(self.url, body, {"Content-Type": "application/json",
                                                          "User-Agent": "belem-onchain/1.0"})
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    js = json.load(r)
            except urllib.error.HTTPError as e:
                txt = e.read().decode(errors="replace")
                if "archive" in txt.lower():
                    raise ArchiveError(txt[:200])
                if e.code in (429, 500, 502, 503, 504) and k < tries - 1:
                    time.sleep(2 ** k)
                    continue
                raise RuntimeError(f"{method}: HTTP {e.code} {txt[:200]}")
            except (urllib.error.URLError, TimeoutError) as e:
                if k < tries - 1:
                    time.sleep(2 ** k)
                    continue
                raise RuntimeError(f"{method}: {e}")
            if "error" in js:
                msg = str(js["error"])
                if "archive" in msg.lower():
                    raise ArchiveError(msg[:200])
                raise RuntimeError(f"{method}: {msg[:300]}")
            return js["result"]

    def eth_call(self, to, data, block):
        return self.call("eth_call", [{"to": to, "data": data}, hex(block)])

    def batch_calls(self, calls, block, size=50, tries=5):
        """eth_call for [(to, data)] in JSON-RPC batches; returns results in order (None where a call failed)."""
        out = []
        for i in range(0, len(calls), size):
            chunk = calls[i:i + size]
            body = json.dumps([{"jsonrpc": "2.0", "id": j, "method": "eth_call",
                                "params": [{"to": t, "data": d}, hex(block)]} for j, (t, d) in enumerate(chunk)]).encode()
            for k in range(tries):
                self.n += 1
                try:
                    req = urllib.request.Request(self.url, body, {"Content-Type": "application/json",
                                                                  "User-Agent": "belem-onchain/1.0"})
                    with urllib.request.urlopen(req, timeout=60) as r:
                        js = json.load(r)
                    if isinstance(js, list):
                        break
                except (urllib.error.URLError, TimeoutError):
                    pass
                time.sleep(2 ** k)
            else:
                raise RuntimeError("eth_call batch failed")
            res = {x.get("id"): x.get("result") for x in js}
            out += [res.get(j) for j in range(len(chunk))]
        return out


def words(hexstr):
    h = hexstr[2:] if hexstr.startswith("0x") else hexstr
    return [int(h[i:i + 64], 16) for i in range(0, len(h), 64)]


def addr_word(a):
    return a.lower().replace("0x", "").rjust(64, "0")


def get_logs(rpc, topics, start, end, chunk, log=print):
    """eth_getLogs over [start, end] in chunks; halves the chunk on range / size errors.
    Raises ArchiveError if the node refuses old blocks."""
    out, a = [], start
    while a <= end:
        b = min(end, a + chunk - 1)
        try:
            out += rpc.call("eth_getLogs", [{"address": MORPHO, "fromBlock": hex(a), "toBlock": hex(b),
                                             "topics": topics}])
            a = b + 1
        except RuntimeError as e:
            if chunk <= 100:
                raise
            chunk //= 2
            log(f"  getLogs {a}-{b} failed ({str(e)[:80]}); chunk -> {chunk}")
            time.sleep(1)
    return out


def recent_logs(rpc, topics, start, head, chunk):
    """Scan backwards from head until the node refuses (archive) or start is reached."""
    out, b = [], head
    while b >= start:
        a = max(start, b - chunk + 1)
        try:
            out += get_logs(rpc, topics, a, b, chunk, log=lambda *_: None)
        except ArchiveError:
            return out, b + 1
        b = a - 1
    return out, start


def api_addresses(market_id):
    q = ("query($k:[String!],$s:Int){ marketPositions(first:100, skip:$s, where:{marketUniqueKey_in:$k, "
         "chainId_in:[1]}){ items { user { address } } pageInfo { count countTotal } } }")
    got, skip = [], 0
    while True:
        req = urllib.request.Request(MORPHO_GQL, json.dumps({"query": q, "variables": {"k": [market_id], "s": skip}}).encode(),
                                     {"Content-Type": "application/json", "User-Agent": "belem-onchain/1.0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            js = json.load(r)
        if "errors" in js:
            raise RuntimeError(f"Morpho GraphQL: {js['errors']}")
        d = js["data"]["marketPositions"]
        got += [x["user"]["address"].lower() for x in d["items"]]
        skip += d["pageInfo"]["count"]
        if d["pageInfo"]["count"] == 0 or skip >= d["pageInfo"]["countTotal"]:
            return got


# ------------------------------------------------------------------ maths shared with export_dashboard.py
def lif(lltv):
    from loss_model import lif as _lif
    return _lif(lltv)


def liquidation_curve(borrowers, price, lltv, capacity_pt, drops=DROPS):
    """For each oracle drop d: borrowers whose distance to liquidation < d are liquidatable. Assumes each is
    liquidated in full (Morpho has no close factor): seized PT = borrow x LIF / (price x (1 - d)), capped at the
    borrower's collateral; what the collateral cannot cover is bad debt."""
    f = lif(lltv)
    rows, first = [], None
    for d in drops:
        p = price * (1 - d)
        hit = [b for b in borrowers if b["borrow_usdc"] > 0 and b["collateral_pt"] * p * lltv < b["borrow_usdc"]]
        seized, bad = 0.0, 0.0
        for b in hit:
            s = b["borrow_usdc"] * f / p
            if s > b["collateral_pt"]:
                bad += b["borrow_usdc"] - b["collateral_pt"] * p / f
                s = b["collateral_pt"]
            seized += s
        row = {"oracle_drop": d, "n_liquidatable": len(hit),
               "debt_liquidatable_usdc": sum(b["borrow_usdc"] for b in hit),
               "pt_seized": seized, "bad_debt_usdc": bad,
               "seized_exceeds_capacity": capacity_pt is not None and seized > capacity_pt}
        rows.append(row)
        if first is None and row["seized_exceeds_capacity"]:
            first = d
    return rows, first


def capacity_from_curves(paths):
    """max_exit_fraction x notional (USD) and the PT price used for those quotes -> capacity in PT."""
    best, notional, pt_usd = 0.0, None, None
    for p in paths:
        with open(p) as fh:
            for r in csv.DictReader(fh):
                if r.get("realized_loss_vs_mark") or r.get("price_impact_raw"):
                    fr = float(r["fraction"])
                    n = float(r["usd"]) / fr
                    notional = notional or n
                    pt_usd = pt_usd or float(r["usd"]) / (int(r["pt_amount_wei"]) / 1e18)
                    best = max(best, fr)
    if notional is None:
        return None
    return {"max_exit_fraction": best, "notional_usd": notional, "capacity_usd": best * notional,
            "pt_price_usd": pt_usd, "capacity_pt": best * notional / pt_usd,
            "curves": [os.path.basename(p) for p in paths]}


def distribution(borrowers):
    debt = [b for b in borrowers if b["borrow_usdc"] > 0]
    if not debt:
        return None
    ltvs = sorted(b["ltv"] for b in debt)
    tot = sum(b["borrow_usdc"] for b in debt)
    edges = [0, 0.005, 0.01, 0.02, 0.03, 0.05, 0.1, 1.0]
    buckets = []
    for lo, hi in zip(edges, edges[1:]):
        inb = [b for b in debt if lo <= b["distance_to_liquidation"] < hi]
        buckets.append({"distance_from": lo, "distance_to": hi, "n": len(inb),
                        "borrow_usdc": sum(b["borrow_usdc"] for b in inb)})
    return {"n_borrowers": len(debt), "ltv_min": ltvs[0], "ltv_median": ltvs[len(ltvs) // 2], "ltv_max": ltvs[-1],
            "ltv_debt_weighted": sum(b["ltv"] * b["borrow_usdc"] for b in debt) / tot,
            "distance_buckets": buckets}


def borrow_rate(rpc, block, mid, params_hex=None, market_hex=None):
    """Borrow rate of a market from its IRM: borrowRateView(MarketParams, Market) (AdaptiveCurveIrm ABI, Etherscan);
    returns (rate per second in WAD, APR). None if the call fails."""
    try:
        p = params_hex or rpc.eth_call(MORPHO, "0x" + SIG["idToMarketParams(bytes32)"] + mid[2:], block)[2:]
        m = market_hex or rpc.eth_call(MORPHO, "0x" + SIG["market(bytes32)"] + mid[2:], block)[2:]
        irm = "0x" + p[3 * 64 + 24:4 * 64]
        r = words(rpc.eth_call(irm, "0x" + SIG["borrowRateView((address,address,address,address,uint256),(uint128,uint128,uint128,uint128,uint128,uint128))"] + p + m, block))[0]
        return r, r * 31536000 / 1e18
    except (RuntimeError, IndexError, ValueError):
        return None, None


def read_positions(rpc, block, mid, addrs, tba, tbs, price_raw, lltv_wad, dec_loan, dec_col):
    """position() of every address at block -> borrowers with collateral or debt, highest LTV first.
    Field names keep the original market's units (collateral_pt = collateral tokens, *_usdc = loan tokens)."""
    addrs = sorted(addrs)
    res = rpc.batch_calls([(MORPHO, "0x" + SIG["position(bytes32,address)"] + mid[2:] + addr_word(u)) for u in addrs],
                          block)
    price = price_raw * 10 ** dec_col / 10 ** dec_loan / 1e36
    lltv = lltv_wad / 1e18
    out = []
    for u, r in zip(addrs, res):
        if r is None:
            r = rpc.eth_call(MORPHO, "0x" + SIG["position(bytes32,address)"] + mid[2:] + addr_word(u), block)
        ss, bs, col = words(r)
        if bs == 0 and col == 0:
            continue
        borrowed = -(-bs * (tba + VIRTUAL_ASSETS) // (tbs + VIRTUAL_SHARES))      # toAssetsUp
        max_borrow = col * price_raw // 10 ** 36 * lltv_wad // 10 ** 18
        c_pt, b_usdc = col / 10 ** dec_col, borrowed / 10 ** dec_loan
        ltv = b_usdc / (c_pt * price) if c_pt and price else (float("inf") if b_usdc else 0.0)
        out.append({"address": u, "collateral_pt": c_pt, "collateral_usdc": c_pt * price,
                    "borrow_usdc": b_usdc, "borrow_shares": str(bs), "ltv": ltv,
                    "distance_to_liquidation": 1 - ltv / lltv, "healthy": max_borrow >= borrowed})
    out.sort(key=lambda b: -b["ltv"])
    return out


def read_market(rpc, block, mid, recent_window=20000, chunk=5000, log=print):
    """Any Morpho Blue market at block: params, state, oracle price, every borrower. Addresses from Morpho GraphQL
    marketPositions + recent SupplyCollateral / Borrow logs; amounts on chain. Own gates (no API files needed)."""
    gates = []
    g = lambda ok, msg: gates.append({"pass": bool(ok), "check": msg}) or ok
    mid = mid.lower()
    v = words(rpc.eth_call(MORPHO, "0x" + SIG["idToMarketParams(bytes32)"] + mid[2:], block))
    params = {"loan_token": "0x" + f"{v[0]:040x}", "collateral_token": "0x" + f"{v[1]:040x}",
              "oracle": "0x" + f"{v[2]:040x}", "irm": "0x" + f"{v[3]:040x}", "lltv_wad": v[4]}
    if not g(v[0] != 0, f"market {mid[:10]} exists on Morpho Blue"):
        return {"market_id": mid, "gates": gates, "all_gates_pass": False}
    tsa, tss, tba, tbs, last_update, fee = words(rpc.eth_call(MORPHO, "0x" + SIG["market(bytes32)"] + mid[2:], block))
    calls = [(params["loan_token"], "0x" + SIG["decimals()"]), (params["collateral_token"], "0x" + SIG["decimals()"])]
    if params["oracle"] != "0x" + "0" * 40:
        calls.append((params["oracle"], "0x" + SIG["price()"]))
    r = rpc.batch_calls(calls, block)
    dec_loan, dec_col = words(r[0])[0], words(r[1])[0]
    price_raw = words(r[2])[0] if len(r) > 2 and r[2] else 0
    price = price_raw * 10 ** dec_col / 10 ** dec_loan / 1e36
    found = set(api_addresses(mid))
    logs, covered = recent_logs(rpc, [[T_SUPPLY_COLL, T_BORROW], mid], max(0, block - recent_window), block, chunk)
    for l in logs:
        ob = l["topics"][3] if l["topics"][0] == T_SUPPLY_COLL else l["topics"][2]
        found.add("0x" + ob[-40:].lower())
    borrowers = read_positions(rpc, block, mid, found, tba, tbs, price_raw, params["lltv_wad"], dec_loan, dec_col)
    rate_s, apr = borrow_rate(rpc, block, mid)
    sum_bs = sum(int(b["borrow_shares"]) for b in borrowers)
    g(sum_bs == tbs, f"sum of borrowShares == totalBorrowShares ({sum_bs} / {tbs}): no borrower missing")
    sum_b = sum(b["borrow_usdc"] for b in borrowers)
    tb = tba / 10 ** dec_loan
    g(tb == 0 or abs(sum_b / tb - 1) < 0.01, f"sum of borrow {sum_b:,.2f} within 1% of totalBorrowAssets {tb:,.2f}")
    return {"block": block, "market_id": mid, "market_params": params, "lltv": params["lltv_wad"] / 1e18,
            "loan_decimals": dec_loan, "collateral_decimals": dec_col, "oracle_price_raw": str(price_raw),
            "oracle_price": price,
            "market": {"total_supply_assets_usdc": tsa / 10 ** dec_loan, "total_borrow_assets_usdc": tb,
                       "total_supply_shares": str(tss), "total_borrow_shares": str(tbs), "last_update": last_update,
                       "fee_wad": str(fee), "liquidity_usdc": (tsa - tba) / 10 ** dec_loan},
            "discovery": {"sources": [f"Morpho GraphQL marketPositions + eth_getLogs blocks {covered}-{block}"],
                          "candidates": len(found)},
            "borrow_rate_per_second": rate_s, "borrow_apr": apr,
            "borrowers": borrowers, "distribution": distribution(borrowers), "gates": gates,
            "all_gates_pass": all(x["pass"] for x in gates)}


def read_wallets(rpc, block, mid, addrs, params, tba, tbs, price_raw, dec_loan, dec_col, borrowers):
    """Wallets typed on the command line, read at `block`: PT held in the wallet (collateral token balanceOf) and the
    position in this market (read_positions, same code as the borrowers). Holdings elsewhere (Pendle LP, other
    lending markets) are not read. Gate: a wallet that is also a borrower gets the same numbers as the borrower list."""
    out = []
    addrs = list(dict.fromkeys(x.lower() for x in addrs))
    for u in addrs:
        if not (u.startswith("0x") and len(u) == 42 and all(c in "0123456789abcdef" for c in u[2:])):
            sys.exit(f"--wallet {u}: not an address (0x + 40 hex characters)")
    if not addrs:
        return out
    bal = rpc.batch_calls([(params["collateral_token"], "0x" + SIG["balanceOf(address)"] + addr_word(u))
                           for u in addrs], block)
    code = [rpc.call("eth_getCode", [u, hex(block)]) for u in addrs]
    pos = {b["address"]: b for b in read_positions(rpc, block, mid, addrs, tba, tbs, price_raw, params["lltv_wad"],
                                                   dec_loan, dec_col)}
    listed = {b["address"]: b for b in borrowers}
    price = price_raw * 10 ** dec_col / 10 ** dec_loan / 1e36
    for u, b, c in zip(addrs, bal, code):
        m = pos.get(u, {})
        out.append({"address": u, "pt_in_wallet": words(b)[0] / 10 ** dec_col,
                    "collateral_pt": m.get("collateral_pt", 0.0), "collateral_usdc": m.get("collateral_usdc", 0.0),
                    "borrow_usdc": m.get("borrow_usdc", 0.0), "borrow_shares": m.get("borrow_shares", "0"),
                    "ltv": m.get("ltv", 0.0), "healthy": m.get("healthy", True),
                    "is_contract": len(c) > 2, "in_borrower_list": u in listed, "oracle_price": price, "block": block})
        if u in listed:
            same = all(m.get(k) == listed[u][k] for k in ("collateral_pt", "borrow_usdc", "borrow_shares"))
            gate(same, f"wallet {u[:10]} read with --wallet = its entry in the borrower list")
    return out


# ------------------------------------------------------------------ main
def run(a):
    rest_files = glob.glob(os.path.join(a.data_dir, "morpho_rest_markets_*.json"))
    if not rest_files:
        sys.exit("no data/morpho_rest_markets_*.json - run fetch_data.py step4")
    with open(rest_files[0]) as fh:
        mk = json.load(fh)["data"][0]
    mid, created = mk["market_id"].lower(), int(mk["creation_block_number"])
    api_file = os.path.join(a.data_dir, f"morpho_markets_{mk['collateral_token'].lower()[:10]}.json")
    with open(api_file) as fh:
        api = next(x for x in json.load(fh) if (x.get("marketId") or "").lower() == mid)
    print(f"market {mid}\ncreated at block {created} ({os.path.basename(rest_files[0])})")
    sel_note = check_selectors()
    print(f"selectors: {sel_note}")

    rpc = RPC(a.rpc)
    head = int(rpc.call("eth_blockNumber", []), 16)
    blk = rpc.call("eth_getBlockByNumber", [hex(head), False])
    ts = int(blk["timestamp"], 16)
    base_fee = int(blk.get("baseFeePerGas", "0x0"), 16)
    try:
        prio = int(rpc.call("eth_maxPriorityFeePerGas", []), 16)
    except RuntimeError:
        prio = None
    try:
        req = urllib.request.Request(f"{LLAMA_COINS}/prices/current/ethereum:{WETH}",
                                     headers={"User-Agent": "belem-onchain/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            eth = json.load(r)["coins"][f"ethereum:{WETH}"]
        eth_usd, eth_ts = float(eth["price"]), int(eth["timestamp"])
    except Exception as e:                       # gas in USD is then unknown, not guessed
        print(f"ETH price unavailable ({e})")
        eth_usd = eth_ts = None
    print(f"pinned block {head} ({time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(ts))}) via {a.rpc}")

    # 1. market params on chain == API
    w = rpc.eth_call(MORPHO, "0x" + SIG["idToMarketParams(bytes32)"] + mid[2:], head)
    v = words(w)
    params = {"loan_token": "0x" + f"{v[0]:040x}", "collateral_token": "0x" + f"{v[1]:040x}",
              "oracle": "0x" + f"{v[2]:040x}", "irm": "0x" + f"{v[3]:040x}", "lltv_wad": v[4]}
    want = dict(EXPECTED, irm=mk["irm_address"].lower())
    bad = {k: (params[k], want[k]) for k in want if params[k] != want[k]}
    if not gate(not bad, f"idToMarketParams on chain = Morpho API (USDC / PT / oracle / irm / lltv 0.915)"
                         + (f": mismatch {bad}" if bad else "")):
        return None
    lltv = params["lltv_wad"] / 1e18

    # 2. market state, oracle price, decimals
    tsa, tss, tba, tbs, last_update, fee = words(rpc.eth_call(MORPHO, "0x" + SIG["market(bytes32)"] + mid[2:], head))
    price_raw = words(rpc.eth_call(params["oracle"], "0x" + SIG["price()"], head))[0]
    dec_loan = words(rpc.eth_call(params["loan_token"], "0x" + SIG["decimals()"], head))[0]
    dec_col = words(rpc.eth_call(params["collateral_token"], "0x" + SIG["decimals()"], head))[0]
    price = price_raw * 10 ** dec_col / 10 ** dec_loan / 1e36           # USDC per PT
    pt_in_morpho = words(rpc.eth_call(params["collateral_token"],
                                      "0x" + SIG["balanceOf(address)"] + addr_word(MORPHO), head))[0] / 10 ** dec_col
    print(f"totalBorrowAssets {tba / 10 ** dec_loan:,.2f} USDC  totalBorrowShares {tbs}  oracle price {price:.6f} USDC/PT")
    api_price = None
    st = (api.get("_oracle_state_rest") or {}).get("data") or {}
    if st.get("price"):
        api_price = int(st["price"]) * 10 ** dec_col / 10 ** dec_loan / 1e36
        gate(abs(price / api_price - 1) < 0.01,
             f"price() on chain {price:.6f} within 1% of Morpho API oracle price {api_price:.6f} "
             f"(block {st.get('last_indexed_block')})")
    gate(abs(tba / 10 ** dec_loan / api["state"]["borrowAssetsUsd"] - 1) < 0.01,
         f"market() totalBorrowAssets {tba / 10 ** dec_loan:,.0f} USDC within 1% of API borrow "
         f"${api['state']['borrowAssetsUsd']:,.0f}")

    # 3. verify event layouts against real logs, then discover borrowers
    probe = get_logs(rpc, [[T_SUPPLY_COLL, T_BORROW]], head - 4999, head, 5000)
    sc = [l for l in probe if l["topics"][0] == T_SUPPLY_COLL]
    bo = [l for l in probe if l["topics"][0] == T_BORROW]
    ok_sc = bool(sc) and all(len(l["topics"]) == 4 and len(l["data"]) == 2 + 64 for l in sc)
    ok_bo = bool(bo) and all(len(l["topics"]) == 4 and len(l["data"]) == 2 + 3 * 64 for l in bo)
    gate(ok_sc and ok_bo, f"topic0 match real Morpho logs in blocks {head - 4999}-{head}: SupplyCollateral "
                          f"{len(sc)} logs (4 topics, 1 data word), Borrow {len(bo)} logs (4 topics, 3 data words)")

    found, sources, covered_from = set(), [], None
    topics = [[T_SUPPLY_COLL, T_BORROW], mid]

    def from_logs(logs):
        for l in logs:
            # SupplyCollateral: [t0, id, caller, onBehalf]; Borrow: [t0, id, onBehalf, receiver]
            ob = l["topics"][3] if l["topics"][0] == T_SUPPLY_COLL else l["topics"][2]
            found.add("0x" + ob[-40:].lower())

    if a.discover in ("logs", "auto"):
        try:
            logs = get_logs(rpc, topics, created, head, a.chunk)
            from_logs(logs)
            covered_from = created
            sources.append(f"eth_getLogs SupplyCollateral/Borrow, blocks {created}-{head} ({len(logs)} logs)")
        except ArchiveError as e:
            if a.discover == "logs":
                gate(False, f"RPC refuses logs before the recent blocks (archive): {e}")
                return None
            print(f"RPC refuses old logs (archive) -> Morpho API for addresses + recent logs")
    if covered_from is None:
        logs, covered_from = recent_logs(rpc, topics, created, head, a.chunk)
        from_logs(logs)
        sources.append(f"eth_getLogs SupplyCollateral/Borrow, blocks {covered_from}-{head} only "
                       f"({len(logs)} logs; older blocks need an archive RPC)")
        api_list = api_addresses(mid)
        sources.append(f"Morpho GraphQL marketPositions: {len(api_list)} addresses (amounts not used)")
        found.update(api_list)
    print(f"candidates: {len(found)} addresses")

    # 4. read every candidate's position on chain
    borrowers = read_positions(rpc, head, mid, found, tba, tbs, price_raw, params["lltv_wad"], dec_loan, dec_col)
    rate_s, borrow_apr = borrow_rate(rpc, head, mid)
    print(f"borrow APR {borrow_apr:.4%} (IRM borrowRateView)" if borrow_apr is not None else "borrow rate unavailable")
    n_debt = sum(b["borrow_usdc"] > 0 for b in borrowers)
    print(f"positions with collateral or debt: {len(borrowers)} ({n_debt} with debt)")

    # 5. gates on totals
    sum_bs = sum(int(b["borrow_shares"]) for b in borrowers)
    gate(sum_bs == tbs, f"sum of borrowShares {sum_bs} == market totalBorrowShares {tbs} (no borrower missing)")
    sum_b = sum(b["borrow_usdc"] for b in borrowers)
    gate(abs(sum_b / (tba / 10 ** dec_loan) - 1) < 0.01,
         f"sum of borrow {sum_b:,.2f} USDC within 1% of totalBorrowAssets {tba / 10 ** dec_loan:,.2f}")
    sum_c = sum(b["collateral_pt"] for b in borrowers)
    api_c = api["state"]["collateralAssetsUsd"]
    gate(abs(sum_c * price / api_c - 1) < 0.01,
         f"sum of collateral {sum_c:,.2f} PT x oracle {price:.4f} = ${sum_c * price:,.0f} within 1% of API "
         f"collateral ${api_c:,.0f} (API reports USD)")
    print(f"INFO  PT held by Morpho (balanceOf) {pt_in_morpho:,.2f}; sum of collateral {sum_c:,.2f}")

    # 5b. wallets given with --wallet, at the same block: PT in the wallet (balanceOf) + position in this market
    wallets = read_wallets(rpc, head, mid, a.wallet or [], params, tba, tbs, price_raw, dec_loan, dec_col, borrowers)
    for w in wallets:
        print(f"wallet {w['address']}: {w['pt_in_wallet']:,.2f} PT in the wallet, {w['collateral_pt']:,.2f} PT as "
              f"collateral, {w['borrow_usdc']:,.2f} USDC borrowed")

    # 6. liquidation curve vs Pendle exit capacity
    curves = a.curves or sorted(glob.glob(os.path.join(a.data_dir, "exit_curve_*_10m.csv")) +
                                glob.glob(os.path.join(a.data_dir, "exit_curve_*_cap.csv")))
    cap = capacity_from_curves(curves) if curves else None
    rows, first = liquidation_curve(borrowers, price, lltv, cap and cap["capacity_pt"])
    if cap:
        print(f"Pendle capacity now: {cap['max_exit_fraction']:.0%} x ${cap['notional_usd']:,.0f} = "
              f"{cap['capacity_pt']:,.0f} PT")
    for r in rows:
        print(f"  drop {r['oracle_drop']:5.1%}: {r['n_liquidatable']:2d} liquidatable, debt "
              f"{r['debt_liquidatable_usdc']:>13,.0f} USDC, PT seized {r['pt_seized']:>13,.0f}"
              + ("  > capacity" if r["seized_exceeds_capacity"] else ""))
    print(f"first drop where seized PT > Pendle capacity: {first}")

    # oracle type tree at the same block (oracle_types.py; imported here to avoid an import cycle)
    oracle_cls = None
    try:
        import oracle_types
        sym = oracle_types._str(rpc.eth_call(params["collateral_token"], "0x95d89b41", head))   # symbol()
        oracle_cls = oracle_types.classify(params["oracle"], rpc, head, ts, collateral_symbol=sym)
        print(f"oracle {params['oracle'][:10]}: {oracle_cls['kind']}, tracks market={oracle_cls['tracks_market']}, "
              f"underlying={oracle_cls['tracks_underlying']}")
    except Exception as e:                       # Etherscan key missing etc.: oracle stays unclassified
        print(f"oracle not classified ({type(e).__name__}: {str(e)[:80]})")
    ev = {"grade": "A", "source": f"Ethereum JSON-RPC eth_call at block {head} (Morpho {MORPHO})", "block": head}
    return {
        "block": head, "block_timestamp": ts, "rpc": a.rpc.split("?")[0], "morpho": MORPHO,
        "market_id": mid, "market_params": params, "lltv": lltv, "lif": lif(lltv),
        "loan_decimals": dec_loan, "collateral_decimals": dec_col,
        "oracle_price_raw": str(price_raw), "oracle_price": price,
        "borrow_rate_per_second": rate_s, "borrow_apr": borrow_apr,
        "market": {"total_supply_assets_usdc": tsa / 10 ** dec_loan, "total_borrow_assets_usdc": tba / 10 ** dec_loan,
                   "total_borrow_shares": str(tbs), "last_update": last_update, "fee_wad": str(fee),
                   "pt_held_by_morpho": pt_in_morpho},
        "discovery": {"mode": a.discover, "sources": sources, "logs_cover_from_block": covered_from,
                      "candidates": len(found)},
        "selectors": sel_note,
        "oracle": oracle_cls,
        "gas": {"base_fee_gwei": base_fee / 1e9, "priority_fee_gwei": None if prio is None else prio / 1e9,
                "eth_usd": eth_usd, "eth_price_timestamp": eth_ts,
                "source": f"baseFeePerGas of block {head} and eth_maxPriorityFeePerGas ({a.rpc.split('?')[0]}); "
                          f"ETH = WETH price from {LLAMA_COINS}/prices/current"},
        "borrowers": borrowers,
        "wallets": wallets,
        "distribution": distribution(borrowers),
        "capacity": cap,
        "liquidation_curve": rows,
        "first_drop_seized_exceeds_capacity": first,
        "notes": ["borrow is stored totalBorrowAssets-based: interest accrued since market.last_update is not "
                  "included (Morpho accrues it on the next interaction)",
                  "liquidation curve assumes every liquidatable borrower is liquidated in full at the dropped "
                  "oracle price; seized PT is compared with what one Pendle sale can absorb now"],
        "evidence": {**{k: ev for k in ("market_params", "lltv", "oracle_price", "market", "borrowers", "wallets",
                                        "distribution", "liquidation_curve")},
                     "gas": {"grade": "A", "source": "block base fee + RPC priority fee; ETH price DeFiLlama coins API",
                             "block": head}},
        "gates": GATES, "all_gates_pass": all(g["pass"] for g in GATES),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rpc", default=os.environ.get("RPC_URL"))
    ap.add_argument("--discover", choices=["auto", "logs", "api"], default="auto")
    ap.add_argument("--chunk", type=int, default=5000, help="eth_getLogs block range per request")
    ap.add_argument("--curves", nargs="*", help="exit-curve CSVs for the capacity (default: *_10m + *_cap)")
    ap.add_argument("--data-dir", default=DATA)
    ap.add_argument("--wallet", nargs="*", default=[],
                    help="wallet addresses to read at the same block (PT in the wallet + position in this market); "
                         "the PT view's wallet input finds them")
    a = ap.parse_args()
    if not a.rpc:
        sys.exit("set RPC_URL or pass --rpc")
    out = run(a)
    if out is None:
        sys.exit(1)
    path = os.path.join(a.data_dir, f"morpho_positions_{out['market_id'][:10]}.json")
    with open(path, "w") as fh:
        json.dump(out, fh, indent=1)
    print(f"saved -> {path}")
    n_fail = sum(not g["pass"] for g in GATES)
    print(f"{len(GATES) - n_fail}/{len(GATES)} gates pass")
    if n_fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
