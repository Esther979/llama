#!/usr/bin/env python3
"""
Minimal Etherscan V2 client (standard library only): verified source code and ABI of a contract.

  python3 etherscan.py 0xADDRESS [0xADDRESS ...] [--chain 1]     # prints ContractName / proxy / implementation

API (docs.etherscan.io, "Get Contract Source Code"):
  GET https://api.etherscan.io/v2/api?module=contract&action=getsourcecode&chainid=<id>&address=<a>&apikey=<key>
  -> {"status": "1", "message": "OK", "result": [{"SourceCode", "ABI", "ContractName", "Proxy", "Implementation", ...}]}
The key is read from the environment or from .env (ETHERSCAN_API_KEY) and never printed or saved.
Raw responses are cached in data/etherscan/<chain>_<address>.json (the key is not part of what is saved).
"""
import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "data", "etherscan")
BASE = "https://api.etherscan.io/v2/api"


def api_key():
    k = os.environ.get("ETHERSCAN_API_KEY")
    if not k and os.path.exists(os.path.join(HERE, ".env")):
        with open(os.path.join(HERE, ".env")) as f:
            for line in f:
                if line.strip().startswith("ETHERSCAN_API_KEY="):
                    k = line.strip().split("=", 1)[1].strip().strip('"').strip("'")
    if not k:
        sys.exit("ETHERSCAN_API_KEY not set (environment or .env)")
    return k


def _get(params, tries=5):
    q = urllib.parse.urlencode({**params, "apikey": api_key()})
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(f"{BASE}?{q}", headers={"User-Agent": "belem/1.0"}),
                                        timeout=60) as r:
                js = json.load(r)
        except Exception as e:                     # network error: back off and retry
            if i == tries - 1:
                raise RuntimeError(f"Etherscan {params.get('action')}: {e}")
            time.sleep(2 ** i)
            continue
        msg = str(js.get("result")) if js.get("status") != "1" else ""
        if "rate limit" in msg.lower() and i < tries - 1:
            time.sleep(2 ** i)
            continue
        time.sleep(0.25)                           # stay under the free-tier rate
        return js
    return js


def source(address, chain=1, refresh=False):
    """getsourcecode result[0] for one address (cached)."""
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, f"{chain}_{address.lower()}.json")
    if os.path.exists(path) and not refresh:
        with open(path) as f:
            js = json.load(f)
    else:
        js = _get({"chainid": chain, "module": "contract", "action": "getsourcecode", "address": address})
        js["_fetched_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with open(path, "w") as f:
            json.dump(js, f)
    if js.get("status") != "1" or not js.get("result"):
        raise RuntimeError(f"Etherscan getsourcecode {address}: {js.get('message')} {str(js.get('result'))[:200]}")
    return js["result"][0]


def describe(address, chain=1):
    """Contract name, verification and ABI; follows a proxy to its implementation (one level)."""
    r = source(address, chain)
    out = {"address": address.lower(), "chain": chain, "verified": bool(r.get("SourceCode")),
           "contract_name": r.get("ContractName") or None, "proxy": r.get("Proxy") == "1",
           "implementation": (r.get("Implementation") or "").lower() or None, "compiler": r.get("CompilerVersion"),
           "abi": None, "source": "Etherscan V2 getsourcecode"}
    abi = r.get("ABI")
    if abi and abi.startswith("["):
        out["abi"] = json.loads(abi)
    if out["proxy"] and out["implementation"]:
        impl = source(out["implementation"], chain)
        out["implementation_name"] = impl.get("ContractName") or None
        ia = impl.get("ABI")
        if ia and ia.startswith("["):
            out["implementation_abi"] = json.loads(ia)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("addresses", nargs="+")
    ap.add_argument("--chain", type=int, default=1)
    a = ap.parse_args()
    for addr in a.addresses:
        d = describe(addr, a.chain)
        abi = d.get("implementation_abi") or d.get("abi") or []
        views = [f["name"] for f in abi if f.get("type") == "function" and f.get("stateMutability") in ("view", "pure")]
        print(f"{d['address']}: {d['contract_name']!s:34s} verified={d['verified']} proxy={d['proxy']}"
              + (f" -> {d['implementation']} ({d.get('implementation_name')})" if d["proxy"] else "")
              + f"  views={len(views)}")


if __name__ == "__main__":
    main()
