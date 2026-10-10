#!/usr/bin/env python3
"""
Belem DeFi Risk Dependency Challenge - raw data fetcher.
Python 3.9+, standard library only (no pip install needed).

Run the steps in order. Each step saves raw JSON under ./data/ and ends with a
GATE line. Do not move on until the gate passes.

  python3 fetch_data.py step0                                  # can I reach the APIs?
  python3 fetch_data.py step1 --filter sUSDe                   # Pendle markets -> pick one
  python3 fetch_data.py step2 --chain 1 --market 0xMARKET      # PT price / implied APY history
  python3 fetch_data.py step3 --chain 1 --market 0xMARKET --notional 1000000   # real exit quotes
  python3 fetch_data.py step4 --chain 1 --market 0xMARKET      # Morpho markets using this PT as collateral
  python3 fetch_data.py step5 --chain 1 --market 0xMARKET --slugs pendle       # DeFiLlama TVL + prices
  python3 fetch_data.py step6                                  # Stream / deUSD replay (Nov 2025)

Optional: export PENDLE_API_KEY=...  (only if Pendle answers 401/403;
key from https://api-v2.pendle.finance/dashboard)
"""
import argparse
import csv
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
PENDLE = "https://api-v2.pendle.finance/core"
MORPHO_GQL = "https://api.morpho.org/graphql"
MORPHO_REST = "https://api.morpho.org"
LLAMA = "https://api.llama.fi"
LLAMA_COINS_FALLBACK = "https://coins.llama.fi"
CHAIN_NAME = {1: "ethereum", 10: "optimism", 56: "bsc", 146: "sonic", 5000: "mantle",
              8453: "base", 42161: "arbitrum", 80094: "berachain", 9745: "plasma"}


# ----------------------------------------------------------------------------- helpers
def http(method, url, body=None, pendle=False):
    h = {"User-Agent": "belem-hackathon/0.1", "Accept": "application/json"}
    if pendle and os.environ.get("PENDLE_API_KEY"):
        h["Authorization"] = "Bearer " + os.environ["PENDLE_API_KEY"]
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            raw = r.read().decode(errors="replace")
            try:
                return r.status, json.loads(raw) if raw else None
            except json.JSONDecodeError:
                return r.status, {"_non_json": raw[:500]}
    except urllib.error.HTTPError as e:
        return e.code, {"_error": e.read().decode(errors="replace")[:800]}
    except Exception as e:  # network, TLS, timeout
        return 0, {"_error": repr(e)}


def save(name, obj):
    os.makedirs(DATA, exist_ok=True)
    path = os.path.join(DATA, name)
    with open(path, "w") as f:
        json.dump(obj, f, indent=1)
    return path


def load(name):
    path = os.path.join(DATA, name)
    if not os.path.exists(path):
        sys.exit(f"missing {path} - run the earlier step first")
    with open(path) as f:
        return json.load(f)


def addr(x):
    """Pendle sometimes returns ids as '1-0xabc...'. Return the bare lowercase address."""
    if not isinstance(x, str):
        return x
    if "-" in x and x.split("-", 1)[0].isdigit():
        x = x.split("-", 1)[1]
    return x.lower()


def gate(ok, msg):
    print(("GATE PASS: " if ok else "GATE FAIL: ") + msg)
    return ok


def hint_auth(status):
    if status in (401, 403):
        print("  -> Pendle refused the call. export PENDLE_API_KEY=... "
              "(free key at https://api-v2.pendle.finance/dashboard) and rerun.")


def iso_days_ago(days):
    t = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def find_market(market):
    js = load("pendle_markets.json")
    for m in js["markets"]:
        if addr(m.get("address")) == market.lower():
            return m
    sys.exit(f"market {market} not found in data/pendle_markets.json - check the address from step1")


def first_list(js, keys):
    if isinstance(js, list):
        return js
    if isinstance(js, dict):
        for k in keys:
            v = js.get(k)
            if isinstance(v, list):
                return v
            if isinstance(v, dict):  # e.g. {"data": {"items": [...]}}
                inner = first_list(v, keys)
                if inner:
                    return inner
    return []


# ----------------------------------------------------------------------------- step 0
def step0(a):
    checks = [
        ("Pendle", f"{PENDLE}/v1/chains", True),
        ("Morpho REST", f"{MORPHO_REST}/v1/blue/markets?chain_id=1&limit=1", False),
        ("DeFiLlama", f"{LLAMA}/protocol/pendle", False),
    ]
    ok_all = True
    for name, url, pend in checks:
        st, js = http("GET", url, pendle=pend)
        ok = st == 200
        ok_all &= ok
        print(f"{name:12s} HTTP {st}  {'' if ok else str(js)[:200]}")
        if name == "Pendle":
            hint_auth(st)
    st, js = http("POST", MORPHO_GQL, {"query": "{ __typename }"})
    print(f"{'Morpho GQL':12s} HTTP {st}  {'' if st == 200 else str(js)[:200]}")
    ok_all &= st == 200
    gate(ok_all, "all four endpoints answered 200" if ok_all else "fix the failing endpoint before step1")


# ----------------------------------------------------------------------------- step 1
def step1(a):
    items, skip, src, st, js = [], 0, "v2", None, None
    while True:
        st, js = http("GET", f"{PENDLE}/v2/markets/all?limit=100&skip={skip}", pendle=True)
        if st != 200:
            break
        batch = first_list(js, ["markets", "results", "data", "items"])
        items += batch
        if len(batch) < 100:
            break
        skip += 100
        time.sleep(1)
    if not items:
        print(f"v2/markets/all -> HTTP {st} {str(js)[:200]}; trying v1/markets/all")
        hint_auth(st)
        st, js = http("GET", f"{PENDLE}/v1/markets/all", pendle=True)
        src = "v1"
        items = first_list(js, ["markets", "results", "data", "items"])
        hint_auth(st)
    path = save("pendle_markets.json", {"source": src, "fetched_at": iso_days_ago(0), "markets": items})
    print(f"saved {len(items)} markets ({src}) -> {path}")
    if items:
        print("fields on one market object:", sorted(items[0].keys()))
    f = a.filter.lower()
    rows = [m for m in items if f in (m.get("name") or "").lower()]
    print(f"\n{len(rows)} markets whose name contains '{a.filter}':")
    print(f"{'chain':>6}  {'name':28s} {'expiry':10s} {'liquidity$':>14s} {'impliedAPY':>10s}  market / pt")
    for m in sorted(rows, key=lambda m: (m.get("chainId") or 0, m.get("expiry") or "")):
        d = m.get("details") or {}
        liq = d.get("liquidity")
        apy = d.get("impliedApy")
        print(f"{str(m.get('chainId')):>6}  {str(m.get('name'))[:28]:28s} {str(m.get('expiry'))[:10]:10s} "
              f"{(f'{liq:,.0f}' if isinstance(liq, (int, float)) else '?'):>14s} "
              f"{(f'{apy:.2%}' if isinstance(apy, (int, float)) else '?'):>10s}  "
              f"{addr(m.get('address'))} / {addr(m.get('pt'))}")
    gate(len(rows) > 0, f"found {len(rows)} candidate markets - pick ONE live market (expiry in the future)")


# ----------------------------------------------------------------------------- step 2
def step2(a):
    m = find_market(a.market)
    pt = addr(m.get("pt"))
    start = iso_days_ago(a.days)
    out = {}
    q = urllib.parse.urlencode({"time_frame": "day", "timestamp_start": start})
    for ver in ("v3", "v2"):
        st, js = http("GET", f"{PENDLE}/{ver}/{a.chain}/markets/{a.market.lower()}/historical-data?{q}", pendle=True)
        print(f"historical-data {ver}: HTTP {st}")
        if st == 200:
            out["historical"] = {"version": ver, "data": js}
            break
        hint_auth(st)
    time.sleep(1)
    q = urllib.parse.urlencode({"time_frame": "hour", "timestamp_start": start})
    st, js = http("GET", f"{PENDLE}/v4/{a.chain}/prices/{pt}/ohlcv?{q}", pendle=True)
    print(f"PT ohlcv v4: HTTP {st}")
    out["pt_ohlcv"] = js
    time.sleep(1)
    st, js = http("GET", f"{PENDLE}/v1/sdk/{a.chain}/markets/{a.market.lower()}/swapping-prices", pendle=True)
    print(f"swapping-prices: HTTP {st}")
    out["spot_swapping_prices"] = js
    path = save(f"pendle_history_{a.market.lower()[:10]}.json", out)
    print(f"saved -> {path}")
    h = (out.get("historical") or {}).get("data")
    if isinstance(h, dict):
        print("historical top-level keys:", sorted(h.keys()))
    if isinstance(out["pt_ohlcv"], dict):
        print("ohlcv top-level keys:", sorted(out["pt_ohlcv"].keys()))
    print("spot swapping prices:", str(out["spot_swapping_prices"])[:300])
    gate("historical" in out, "market history saved" if "historical" in out else "no history - paste the HTTP error to Claude")


# ----------------------------------------------------------------------------- step 3
def step3(a):
    m = find_market(a.market)
    pt, und = addr(m.get("pt")), addr(m.get("underlyingAsset"))
    print(f"PT {pt}\nunderlying {und}")
    ids = f"{a.chain}-{pt},{a.chain}-{und}"
    st, js = http("GET", f"{PENDLE}/v1/prices/assets?ids={ids}", pendle=True)
    hint_auth(st)
    prices = (js or {}).get("prices", {}) if isinstance(js, dict) else {}
    p_pt = prices.get(f"{a.chain}-{pt}")
    p_und = prices.get(f"{a.chain}-{und}")
    print(f"prices HTTP {st}: PT ${p_pt}  underlying ${p_und}")
    if not p_pt:
        gate(False, "no PT price - cannot size the quotes")
        return
    time.sleep(1)
    st, js = http("GET", f"{PENDLE}/v1/assets/all?chainId={a.chain}", pendle=True)
    assets = first_list(js, ["assets", "results", "data", "items"])
    dec = {addr(x.get("address")): x.get("decimals") for x in assets if isinstance(x, dict)}
    d_pt, d_und = dec.get(pt), dec.get(und)
    # Tokens that are not Pendle assets (e.g. sUSDe) are missing from assets/all:
    # ask DeFiLlama's coins API, which returns decimals with the price.
    cname = CHAIN_NAME.get(a.chain, "ethereum")
    for tok in [t for t in (pt, und) if dec.get(t) is None]:
        st2, js2 = http("GET", f"{LLAMA_COINS_FALLBACK}/prices/current/{cname}:{tok}")
        cd = ((js2 or {}).get("coins") or {}).get(f"{cname}:{tok}") if isinstance(js2, dict) else None
        if cd and cd.get("decimals") is not None:
            dec[tok] = int(cd["decimals"])
            print(f"decimals for {tok} from DeFiLlama coins API: {dec[tok]}")
    d_pt, d_und = dec.get(pt), dec.get(und)
    if d_pt is None:
        print("WARNING: PT decimals not found in assets/all, assuming 18")
        d_pt = 18
    if d_und is None:
        print("WARNING: underlying decimals not found - realized_loss column will be empty")
    fracs = [float(x) for x in a.fractions.split(",")]
    rows, raw = [], []
    for f in fracs:
        usd = a.notional * f
        amt = int(usd / p_pt * 10 ** d_pt)
        # The API rejects quotes without a receiver; a quote needs no balance or approval,
        # so any valid address works (nothing is sent on-chain).
        body = {"receiver": a.receiver, "slippage": 0.01, "inputs": [{"token": pt, "amount": str(amt)}],
                "outputs": [und], "enableAggregator": False}
        st, js = http("POST", f"{PENDLE}/v3/sdk/{a.chain}/convert", body, pendle=True)
        if st not in (200, 201):
            body["enableAggregator"] = True
            time.sleep(1)
            st, js = http("POST", f"{PENDLE}/v3/sdk/{a.chain}/convert", body, pendle=True)
        raw.append({"fraction": f, "usd": usd, "request": body, "status": st, "response": js})
        pi = out_amt = realized = None
        routes = (js or {}).get("routes") if isinstance(js, dict) else None
        if routes:
            r0 = routes[0]
            pi = (r0.get("data") or {}).get("priceImpact")
            outs = r0.get("outputs") or []
            if outs:
                out_amt = int(outs[0]["amount"])
                if d_und is not None and p_und:
                    realized = 1 - (out_amt / 10 ** d_und * p_und) / usd
        else:
            print(f"  f={f}: HTTP {st} {str(js)[:200]}")
            hint_auth(st)
        rows.append({"fraction": f, "usd": round(usd, 2), "pt_amount_wei": amt,
                     "price_impact_raw": pi, "realized_loss_vs_mark": realized})
        print(f"  sell {f:>5.0%} (${usd:,.0f}): priceImpact={pi}  realized_loss_vs_mark="
              f"{'' if realized is None else f'{realized:.4%}'}")
        time.sleep(1.5)
    tag = f"_{a.tag}" if a.tag else ""
    save(f"exit_quotes_raw_{a.market.lower()[:10]}{tag}.json", raw)
    path = os.path.join(DATA, f"exit_curve_{a.market.lower()[:10]}{tag}.csv")
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"saved -> {path}")
    got = [r for r in rows if r["price_impact_raw"] is not None]
    mono = all(abs(got[i + 1]["price_impact_raw"]) >= abs(got[i]["price_impact_raw"]) - 1e-9
               for i in range(len(got) - 1))
    gate(len(got) == len(rows), f"{len(got)}/{len(rows)} quotes returned")
    if len(got) < 2:
        gate(False, "fewer than 2 quotes - monotonicity not checked")
        return
    gate(mono, "price impact grows with size (pre-registered prediction)"
         if mono else "price impact NOT monotone in size - send exit_quotes_raw to Claude")


# ----------------------------------------------------------------------------- step 4
GQL_BY_ID = """
query M($id: String!, $chain: Int!) {
  marketById(marketId: $id, chainId: $chain) {
    marketId lltv
    loanAsset { address symbol decimals }
    collateralAsset { address symbol decimals }
    state { collateralAssetsUsd borrowAssetsUsd supplyAssetsUsd liquidityAssetsUsd utilization }
    oracle { address type data {
      ... on MorphoChainlinkOracleData { baseFeedOne { address } baseFeedTwo { address }
            baseOracleVault { address } quoteFeedOne { address } quoteFeedTwo { address } scaleFactor }
      ... on MorphoChainlinkOracleV2Data { baseFeedOne { address } baseFeedTwo { address }
            baseOracleVault { address } quoteFeedOne { address } quoteFeedTwo { address }
            quoteOracleVault { address } scaleFactor }
    } }
  }
}"""
# Older docs name the same query marketByUniqueKey(uniqueKey:, chainId:) - used as fallback.
GQL_BY_KEY = (GQL_BY_ID.replace("marketById(marketId: $id", "marketByUniqueKey(uniqueKey: $id")
              .replace("marketId lltv", "uniqueKey lltv"))
# Not in the docs I could verify: GraphQL collateral filter. Used only if REST finds nothing.
GQL_LIST_FALLBACK = """
query L($chain: Int!, $col: String!) {
  markets(first: 100, where: { chainId_in: [$chain], collateralAssetAddress_in: [$col] }) {
    items { marketId uniqueKey lltv }
  }
}"""


def step4(a):
    pt = addr(find_market(a.market).get("pt")) if a.market else a.pt.lower()
    print(f"looking for Morpho markets with collateral = PT {pt}")
    st, js = http("GET", f"{MORPHO_REST}/v1/blue/markets?chain_id={a.chain}&collateral_token={pt}&limit=100")
    save(f"morpho_rest_markets_{pt[:10]}.json", js)
    items = first_list(js, ["items", "data", "markets", "results"])
    print(f"REST v1/blue/markets: HTTP {st}, {len(items)} items")
    if items:
        print("fields on one REST item:", sorted(items[0].keys()) if isinstance(items[0], dict) else items[0])
    ids = []
    for it in items:
        if isinstance(it, dict):
            for k in ("marketId", "uniqueKey", "market_id", "id"):
                if it.get(k):
                    ids.append(str(it[k]).split(":")[-1])
                    break
    if not ids:
        print("REST gave no ids - trying GraphQL list filter (field name unverified)")
        st, js = http("POST", MORPHO_GQL, {"query": GQL_LIST_FALLBACK, "variables": {"chain": a.chain, "col": pt}})
        save(f"morpho_gql_list_{pt[:10]}.json", js)
        for it in first_list((js or {}).get("data", {}).get("markets", {}) if isinstance(js, dict) else {}, ["items"]):
            ids.append(it.get("marketId") or it.get("uniqueKey"))
        if isinstance(js, dict) and js.get("errors"):
            print("  GraphQL said:", str(js["errors"])[:400])
    ids = [i for i in dict.fromkeys(ids) if i]
    details = []
    for mid in ids:
        st, js = http("POST", MORPHO_GQL, {"query": GQL_BY_ID, "variables": {"id": mid, "chain": a.chain}})
        if isinstance(js, dict) and js.get("errors"):
            st, js = http("POST", MORPHO_GQL, {"query": GQL_BY_KEY, "variables": {"id": mid, "chain": a.chain}})
        d = (js or {}).get("data") or {}
        mk = d.get("marketById") or d.get("marketByUniqueKey")
        if not mk:
            print(f"  {mid[:12]}: no detail - {str(js)[:300]}")
            details.append({"id": mid, "error": js})
            continue
        orc = (mk.get("oracle") or {}).get("address")
        if orc:
            _, ost = http("GET", f"{MORPHO_REST}/v0/oracles/{a.chain}:{orc}/state")
            mk["_oracle_state_rest"] = ost
        details.append(mk)
        s = mk.get("state") or {}
        lltv = mk.get("lltv")
        try:
            lltv_f = int(lltv) / 1e18
        except (TypeError, ValueError):
            lltv_f = lltv
        o = mk.get("oracle") or {}
        print(f"  {mid[:12]}  loan={((mk.get('loanAsset') or {}).get('symbol'))}  lltv={lltv_f}  "
              f"collateral$={s.get('collateralAssetsUsd')}  borrow$={s.get('borrowAssetsUsd')}  "
              f"liquidity$={s.get('liquidityAssetsUsd')}  oracle={o.get('type')} {o.get('address')}")
        time.sleep(0.5)
    path = save(f"morpho_markets_{pt[:10]}.json", details)
    print(f"saved -> {path}")
    gate(any("error" not in d for d in details),
         f"{sum('error' not in d for d in details)} Morpho markets with full detail")


# ----------------------------------------------------------------------------- step 5
def step5(a):
    out = {"protocols": {}, "prices": None}
    for slug in [s.strip() for s in a.slugs.split(",") if s.strip()]:
        st, js = http("GET", f"{LLAMA}/protocol/{slug}")
        out["protocols"][slug] = js
        tvl = js.get("tvl") if isinstance(js, dict) else None
        last = tvl[-1] if isinstance(tvl, list) and tvl else None
        print(f"protocol/{slug}: HTTP {st}  latest tvl point: {last}")
        if st != 200:
            print("  -> slug wrong? open defillama.com, search the protocol, copy the slug from the URL")
        time.sleep(0.5)
    coins = a.coins
    if not coins and a.market:
        m = find_market(a.market)
        cname = CHAIN_NAME.get(a.chain, "ethereum")
        coins = f"{cname}:{addr(m.get('pt'))},{cname}:{addr(m.get('underlyingAsset'))}"
    if coins:
        for base in (LLAMA, LLAMA_COINS_FALLBACK):
            st, js = http("GET", f"{base}/prices/current/{coins}")
            print(f"{base}/prices/current: HTTP {st}")
            if st == 200:
                out["prices"] = js
                print("  ", str(js)[:400])
                break
    path = save("defillama.json", out)
    print(f"saved -> {path}")
    ok = all(isinstance(v, dict) and v.get("tvl") for v in out["protocols"].values())
    gate(ok, "TVL history for every slug" if ok else "at least one slug failed")


# ----------------------------------------------------------------------------- step 6
def step6(a):
    want = {s.lower() for s in a.symbols.split(",")}
    st, js = http("GET", f"{LLAMA}/stablecoins?includePrices=true")
    if st != 200:
        st, js = http("GET", "https://stablecoins.llama.fi/stablecoins?includePrices=true")
    assets = first_list(js, ["peggedAssets", "stablecoins", "data"])
    hits = [x for x in assets if isinstance(x, dict) and (x.get("symbol") or "").lower() in want]
    print(f"stablecoins: HTTP {st}, {len(assets)} total, matched:")
    for x in hits:
        print(f"  id={x.get('id')} symbol={x.get('symbol')} name={x.get('name')} gecko_id={x.get('gecko_id')} price={x.get('price')}")
    st2, hist = http("GET", f"{LLAMA}/stablecoinprices")
    if st2 != 200:
        st2, hist = http("GET", "https://stablecoins.llama.fi/stablecoinprices")
    print(f"stablecoinprices: HTTP {st2}")
    lo = int(dt.datetime(2025, 10, 25, tzinfo=dt.timezone.utc).timestamp())
    hi = int(dt.datetime(2025, 11, 20, tzinfo=dt.timezone.utc).timestamp())
    keys = {str(x.get(k)) for x in hits for k in ("gecko_id", "symbol", "id", "name") if x.get(k)}
    window = []
    if isinstance(hist, list):
        for row in hist:
            try:
                t = int(row.get("date"))
            except (TypeError, ValueError):
                continue
            if lo <= t <= hi:
                p = row.get("prices") or {}
                window.append({"date": t, "prices": {k: v for k, v in p.items() if k in keys}})
        if hist and isinstance(hist[-1], dict):
            sample = list((hist[-1].get("prices") or {}).keys())[:15]
            print("  price keys look like:", sample)
    save("replay_stream_nov2025.json", {"matched": hits, "window": window})
    for w in window[:: max(1, len(window) // 12)]:
        print(" ", dt.datetime.fromtimestamp(w["date"], dt.timezone.utc).date(), w["prices"])
    got = any(w["prices"] for w in window)
    gate(bool(hits) and got, "replay price series saved" if got else
         "no matching price series - send the 'price keys look like' line to Claude")


# ----------------------------------------------------------------------------- main
def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("step0")
    s1 = sub.add_parser("step1"); s1.add_argument("--filter", default="sUSDe")
    s2 = sub.add_parser("step2"); s2.add_argument("--chain", type=int, default=1)
    s2.add_argument("--market", required=True); s2.add_argument("--days", type=int, default=90)
    s3 = sub.add_parser("step3"); s3.add_argument("--chain", type=int, default=1)
    s3.add_argument("--market", required=True); s3.add_argument("--notional", type=float, default=1_000_000)
    s3.add_argument("--fractions", default="0.01,0.05,0.1,0.25,0.5,1")
    s3.add_argument("--receiver", default="0x000000000000000000000000000000000000dEaD",
                    help="any valid address; quotes only, nothing is sent")
    s3.add_argument("--tag", default="", help="suffix for output files, e.g. 1m or 10m")
    s4 = sub.add_parser("step4"); s4.add_argument("--chain", type=int, default=1)
    s4.add_argument("--market"); s4.add_argument("--pt")
    s5 = sub.add_parser("step5"); s5.add_argument("--chain", type=int, default=1)
    s5.add_argument("--market"); s5.add_argument("--slugs", default="pendle"); s5.add_argument("--coins")
    s6 = sub.add_parser("step6"); s6.add_argument("--symbols", default="deUSD,xUSD,USDX,scUSD,USDe")
    a = p.parse_args()
    if a.cmd == "step4" and not (a.market or a.pt):
        p.error("step4 needs --market or --pt")
    {"step0": step0, "step1": step1, "step2": step2, "step3": step3,
     "step4": step4, "step5": step5, "step6": step6}[a.cmd](a)


if __name__ == "__main__":
    main()
