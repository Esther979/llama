#!/usr/bin/env python3
"""
Oracle type table: what a Morpho market's oracle reacts to, decided from verified source and on-chain parameters.

  python3 oracle_types.py 0xORACLE [...]          # prints the classification tree

For each oracle: kind, tracks_market (does it fall when the collateral's market price falls?), tracks_underlying
(does it fall when the underlying / issuer value falls?), the rule, and evidence. True / False / None (unknown).

Rules (contract names from Etherscan verified source):
  PendleSparkLinearDiscountOracle   price = 1 - timeLeft x baseDiscountPerYear / 365 days (source): no market,
                                    no underlying input                                           -> False / False  B
  MorphoChainlinkOracleV2           price = SCALE x baseVault x baseFeed1 x baseFeed2 / (quoteVault x quoteFeed1 x
                                    quoteFeed2) (source). Only the base side prices the collateral; quote feeds
                                    price the loan token. A base market-price feed of the collateral itself tracks
                                    the market; one of another asset (e.g. USDe / USD under a PT) tracks the
                                    underlying                                                     -> combine       B
  MetaOracleDeviationTimelock       price = currentOracle.price(); switches to the backup only after
                                    deviation > deviationThreshold for challengeTimelockDuration and an
                                    acceptChallenge() call (source)                                -> current now,
                                    backup after the timelock                                                     B
  Chainlink EACAggregatorProxy      description with "exchange rate" / "NAV" / "calculated": a reported rate, not a
                                    market price -> False / None; other descriptions: market price  -> True / True C
  DummyFeed                         constant (answer fixed)                                        -> False / False C
  anything else                     unknown                                                        -> None / None   D
"""
import argparse
import os
import time

from crawl import sel
from onchain_positions import RPC, words
import etherscan

ZERO = "0x" + "0" * 40


def _str(res):
    try:
        b = bytes.fromhex(res[2:])
        n = int.from_bytes(b[32:64], "big")
        return b[64:64 + n].decode()
    except Exception:
        return None


def _call(rpc, a, sig, block, args=""):
    try:
        return rpc.eth_call(a, "0x" + sel(sig) + args, block)
    except RuntimeError:
        return None


def _addr(rpc, a, sig, block):
    r = _call(rpc, a, sig, block)
    return ("0x" + r[-40:]).lower() if r and len(r) >= 42 else None


def _uint(rpc, a, sig, block):
    r = _call(rpc, a, sig, block)
    return words(r)[0] if r and len(r) > 2 else None


def _last_update(rpc, a, block, now):
    r = _call(rpc, a, "latestRoundData()", block)
    if not r or len(r) < 2 + 5 * 64:
        return None
    w = words(r)
    return {"answer": w[1], "updated_at": w[3], "age_seconds": (now - w[3]) if w[3] else None}


def _base_symbol(desc):
    return desc.split("/")[0].strip().lower() if desc and "/" in desc else None


def relative(part, collateral_symbol):
    """(tracks_market, tracks_underlying) of a base-side part for this collateral."""
    if part["kind"] == "market_price_feed":
        own = collateral_symbol and part.get("prices") and part["prices"] == collateral_symbol.lower()
        return (True, True) if own else (False, True)
    return part["tracks_market"], part["tracks_underlying"]


def classify(a, rpc, block, now=None, depth=0, chain=1, collateral_symbol=None):
    a = a.lower()
    now = now or int(time.time())
    if a == ZERO:
        return {"address": a, "kind": "none", "tracks_market": False, "tracks_underlying": False,
                "rule": "zero address: factor 1", "evidence": {"grade": "B", "source": "MorphoChainlinkOracleV2 source"}}
    try:
        info = etherscan.describe(a, chain)
        name = info.get("implementation_name") or info["contract_name"]
    except RuntimeError as e:
        name = None
    out = {"address": a, "contract_name": name}
    src = f"Etherscan verified source ({name}); eth_call @ block {block}"

    if name == "PendleSparkLinearDiscountOracle":
        disc, mat = _uint(rpc, a, "baseDiscountPerYear()", block), _uint(rpc, a, "maturity()", block)
        out.update(kind="linear_discount", tracks_market=False, tracks_underlying=False,
                   base_discount_per_year=disc / 1e18 if disc is not None else None, maturity=mat,
                   update="computed every block from time to maturity",
                   rule="1 - timeLeft x baseDiscountPerYear / 365 days: no market or underlying input",
                   evidence={"grade": "B", "source": src})
    elif name == "MorphoChainlinkOracleV2":
        parts = {}
        for f in ("BASE_FEED_1()", "BASE_FEED_2()", "QUOTE_FEED_1()", "QUOTE_FEED_2()", "BASE_VAULT()", "QUOTE_VAULT()"):
            x = _addr(rpc, a, f, block)
            if x and x != ZERO:
                parts[f[:-2]] = classify(x, rpc, block, now, depth + 1, chain) if "FEED" in f else \
                    {"address": x, "kind": "erc4626_rate", "tracks_market": False, "tracks_underlying": True,
                     "rule": "vault conversion rate (getAssets): follows the vault's own accounting",
                     "evidence": {"grade": "B", "source": "MorphoChainlinkOracleV2 source"}}
        base = [relative(p, collateral_symbol) for k, p in parts.items() if k.startswith("BASE")]
        comb = lambda xs: True if True in xs else (None if None in xs else False)
        out.update(kind="morpho_chainlink_v2", tracks_market=comb([t[0] for t in base]),
                   tracks_underlying=comb([t[1] for t in base]), parts=parts,
                   loan_side=[k for k in parts if k.startswith("QUOTE")],
                   rule="base side prices the collateral (quote side prices the loan token): tracks what any base "
                        "part tracks",
                   evidence={"grade": max([p["evidence"]["grade"] for k, p in parts.items() if k.startswith("BASE")]
                                          + ["B"], key="ABCD".index), "source": src})
    elif name == "MetaOracleDeviationTimelock":
        prim, back, cur = (_addr(rpc, a, "primaryOracle()", block), _addr(rpc, a, "backupOracle()", block),
                           _addr(rpc, a, "currentOracle()", block))
        thr, ch, heal = (_uint(rpc, a, "deviationThreshold()", block), _uint(rpc, a, "challengeTimelockDuration()", block),
                         _uint(rpc, a, "healingTimelockDuration()", block))
        dev, challenged = _uint(rpc, a, "getDeviation()", block), _uint(rpc, a, "isChallenged()", block)
        p = classify(prim, rpc, block, now, depth + 1, chain, collateral_symbol)
        b = classify(back, rpc, block, now, depth + 1, chain, collateral_symbol)
        current = p if cur == prim else b
        out.update(kind="meta_oracle_timelock", primary=p, backup=b, current=("primary" if cur == prim else "backup"),
                   deviation_threshold=thr / 1e18 if thr is not None else None, challenge_timelock_s=ch,
                   healing_timelock_s=heal, deviation_now=dev / 1e18 if dev is not None else None,
                   challenged=bool(challenged),
                   tracks_market=current["tracks_market"], tracks_underlying=current["tracks_underlying"],
                   tracks_market_after_switch=b["tracks_market"], tracks_underlying_after_switch=b["tracks_underlying"],
                   rule="current oracle now; backup only after deviation > threshold persists for the challenge "
                        "timelock and acceptChallenge() is called",
                   evidence={"grade": max(["B", p["evidence"]["grade"], b["evidence"]["grade"]], key="ABCD".index),
                             "source": src})
    elif name == "EACAggregatorProxy" or (name and "Aggregator" in name and _call(rpc, a, "description()", block)):
        desc = _str(_call(rpc, a, "description()", block) or "0x")
        lu = _last_update(rpc, a, block, now)
        rate = bool(desc) and any(k in desc.lower() for k in ("exchange rate", "nav", "calculated"))
        out.update(kind="reported_rate" if rate else "market_price_feed", description=desc, last_update=lu,
                   prices=_base_symbol(desc),
                   tracks_market=False if rate else True, tracks_underlying=None if rate else True,
                   rule=("reported exchange rate / NAV: does not follow the market; whether it falls on an issuer "
                         "failure depends on who reports it" if rate else
                         "Chainlink price feed of the described pair: follows its market price"),
                   evidence={"grade": "C", "source": f"{src}; classified from description {desc!r}"})
    elif name == "DummyFeed":
        out.update(kind="constant", tracks_market=False, tracks_underlying=False,
                   last_update=_last_update(rpc, a, block, now), rule="constant answer",
                   evidence={"grade": "C", "source": src})
    else:
        out.update(kind="unknown", tracks_market=None, tracks_underlying=None,
                   last_update=_last_update(rpc, a, block, now),
                   rule="type not in the table: both branches computed",
                   evidence={"grade": "D", "source": f"{src}; not classified"})
    return out


def oracle_falls(cls, layer, shock, hours):
    """Does this oracle fall with a shock on the collateral? layer 2 = underlying / issuer, 3 = market price.
    Meta-oracle: the backup takes over only if the shock exceeds the deviation threshold and lasts longer than
    the challenge timelock (hours None = permanent)."""
    key = "tracks_underlying" if layer == 2 else "tracks_market"
    now = cls.get(key)
    if cls.get("kind") != "meta_oracle_timelock" or now is True:
        return now
    after = cls.get(key + "_after_switch")
    lasts = hours is None or (cls.get("challenge_timelock_s") is not None and hours * 3600 >= cls["challenge_timelock_s"])
    big = cls.get("deviation_threshold") is not None and shock > cls["deviation_threshold"]
    if after is True and lasts and big:
        return True
    if after is None:
        return None
    return now


def tree(c, indent=0):
    pad = "  " * indent
    line = (f"{pad}{c.get('contract_name') or c['kind']} {c['address'][:10]}  kind={c['kind']}  market={c['tracks_market']}"
            f"  underlying={c['tracks_underlying']}  [{c['evidence']['grade']}]")
    extra = ""
    if c["kind"] == "meta_oracle_timelock":
        extra = (f"  threshold {c['deviation_threshold']:.2%}, timelock {c['challenge_timelock_s'] / 3600:g}h, "
                 f"deviation now {c['deviation_now']:.3%}, current {c['current']}")
    if c.get("description"):
        extra += f"  {c['description']!r}"
    if c.get("last_update") and c["last_update"].get("age_seconds") is not None:
        extra += f"  updated {c['last_update']['age_seconds'] / 3600:.1f}h ago"
    print(line + extra)
    for k in ("primary", "backup"):
        if k in c:
            tree(c[k], indent + 1)
    for k, p in (c.get("parts") or {}).items():
        tree(p, indent + 1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("oracles", nargs="+")
    ap.add_argument("--collateral-symbol", help="symbol of the market's collateral (market vs underlying feeds)")
    ap.add_argument("--rpc", default=os.environ.get("RPC_URL", "https://ethereum-rpc.publicnode.com"))
    a = ap.parse_args()
    rpc = RPC(a.rpc)
    block = int(rpc.call("eth_blockNumber", []), 16)
    now = int(rpc.call("eth_getBlockByNumber", [hex(block), False])["timestamp"], 16)
    for o in a.oracles:
        tree(classify(o, rpc, block, now, collateral_symbol=a.collateral_symbol))


if __name__ == "__main__":
    main()
