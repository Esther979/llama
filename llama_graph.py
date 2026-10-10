#!/usr/bin/env python3
"""
DeFiLlama -> protocol-level dependency edges + price/peg history.
Uses ONLY the free endpoints of the official SDK (github.com/DefiLlama/python-sdk, PyPI defillama-sdk 0.1.4).

  pip install defillama-sdk

  python3 llama_graph.py protocols --focus pendle,morpho,aave,ethena,euler      # step A: edges for the whole ecosystem
  python3 llama_graph.py protocol --slug pendle                                  # step B: one protocol in depth
  python3 llama_graph.py prices --coins ethereum:0xPT,ethereum:0xUNDERLYING --start 2026-07-01 --end 2026-10-10
  python3 llama_graph.py stable --symbols deUSD,xUSD,USDX,USDe --start 2025-10-25 --end 2025-11-20   # Stream replay

Outputs go to ./data/. Every step ends with a GATE line.
Not used (Pro key required in this SDK): tvl.getTokenProtocols, ecosystem.getOracles/getHacks, yields.*.
"""
import argparse
import csv
import datetime as dt
import json
import math
import os
import sys
import time

try:
    from defillama_sdk import DefiLlama
    from defillama_sdk.errors import DefiLlamaError
except ImportError:
    sys.exit("pip install defillama-sdk")

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
client = DefiLlama()  # free tier, no key


def save_json(name, obj):
    os.makedirs(DATA, exist_ok=True)
    p = os.path.join(DATA, name)
    with open(p, "w") as f:
        json.dump(obj, f, indent=1)
    return p


def save_csv(name, rows):
    os.makedirs(DATA, exist_ok=True)
    p = os.path.join(DATA, name)
    with open(p, "w", newline="") as f:
        if rows:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    return p


def gate(ok, msg):
    print(("GATE PASS: " if ok else "GATE FAIL: ") + msg)


def call(fn, *args, **kw):
    try:
        return fn(*args, **kw)
    except DefiLlamaError as e:
        print(f"  {fn.__qualname__} failed: {type(e).__name__}: {e}")
        return None


def ts(day):
    return int(dt.datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc).timestamp())


def day(t):
    return dt.datetime.fromtimestamp(int(t), dt.timezone.utc).strftime("%Y-%m-%d")


def num(x):
    return x if isinstance(x, (int, float)) else 0.0


# ------------------------------------------------------------------------- step A
def cmd_protocols(a):
    protos = call(client.tvl.getProtocols)
    chains = call(client.tvl.getChains)
    if not protos:
        return gate(False, "getProtocols returned nothing")
    save_json("llama_protocols.json", protos)
    save_json("llama_chains.json", chains or [])
    chain_tvl = {}
    for c in chains or []:
        if isinstance(c, dict) and c.get("name"):
            chain_tvl[c["name"]] = num(c.get("tvl"))

    edges = []
    by_oracle, filled = {}, 0
    for p in protos:
        name, slug, tvl = p.get("name"), p.get("slug"), num(p.get("tvl"))
        src = slug or name
        ctvls = p.get("chainTvls") or {}
        for ch in p.get("chains") or []:
            v = num(ctvls.get(ch)) if isinstance(ctvls, dict) else 0.0
            edges.append({"src": src, "dst": f"chain:{ch}", "type": "runs_on",
                          "weight_usd": round(v, 2),
                          "share_of_protocol": round(v / tvl, 4) if tvl else None,
                          "share_of_chain": round(v / chain_tvl[ch], 4) if chain_tvl.get(ch) else None,
                          "evidence": "defillama:/protocols chains+chainTvls"})
        orcs = p.get("oracles") or []
        if orcs:
            filled += 1
        for o in orcs:
            edges.append({"src": src, "dst": f"oracle:{o}", "type": "priced_by", "weight_usd": round(tvl, 2),
                          "share_of_protocol": None, "share_of_chain": None,
                          "evidence": "defillama:/protocols oracles"})
            by_oracle[o] = by_oracle.get(o, 0.0) + tvl
        if p.get("parentProtocol"):
            edges.append({"src": src, "dst": f"parent:{p['parentProtocol']}", "type": "child_of",
                          "weight_usd": round(tvl, 2), "share_of_protocol": None, "share_of_chain": None,
                          "evidence": "defillama:/protocols parentProtocol"})
        for f in p.get("forkedFrom") or []:
            edges.append({"src": src, "dst": f"code:{f}", "type": "forked_from", "weight_usd": None,
                          "share_of_protocol": None, "share_of_chain": None,
                          "evidence": "defillama:/protocols forkedFrom"})
    path = save_csv("edges_defillama.csv", edges)
    print(f"{len(protos)} protocols, {len(chain_tvl)} chains, {len(edges)} edges -> {path}")
    print(f"protocols with an 'oracles' field filled: {filled} ({filled / len(protos):.1%})")

    print("\nTop oracles by TVL that depends on them (protocol-level, can double count):")
    for o, v in sorted(by_oracle.items(), key=lambda kv: -kv[1])[:10]:
        print(f"  {o:28s} ${v / 1e9:8.2f}b")

    print("\nHighest concentration: one protocol's share of a chain's total TVL (chains with TVL > $50m):")
    conc = [e for e in edges if e["type"] == "runs_on" and e["share_of_chain"]
            and chain_tvl.get(e["dst"][6:], 0) > 5e7]
    for e in sorted(conc, key=lambda e: -e["share_of_chain"])[:12]:
        print(f"  {e['src']:28s} {e['dst']:24s} {e['share_of_chain']:.1%} of chain TVL")

    focus = [f.strip().lower() for f in a.focus.split(",") if f.strip()]
    print(f"\nFocus protocols ({', '.join(focus)}):")
    hit = 0
    for p in protos:
        key = f"{(p.get('slug') or '').lower()} {(p.get('name') or '').lower()}"
        if any(f in key for f in focus):
            hit += 1
            print(f"  slug={p.get('slug'):24s} tvl=${num(p.get('tvl')) / 1e6:10.1f}m  category={p.get('category')}  "
                  f"oracles={p.get('oracles') or '-'}  parent={p.get('parentProtocol') or '-'}  "
                  f"chains={len(p.get('chains') or [])}")
    gate(len(edges) > 0 and hit > 0, f"{len(edges)} edges built, {hit} focus protocols found")


# ------------------------------------------------------------------------- step B
def cmd_protocol(a):
    d = call(client.tvl.getProtocol, a.slug)
    if not d:
        return gate(False, f"no data for slug '{a.slug}' - copy the slug from the defillama.com URL")
    save_json(f"llama_protocol_{a.slug}.json", d)
    print(f"{d.get('name')}  category={d.get('category')}  parent?={d.get('isParentProtocol')}")
    if d.get("otherProtocols"):
        print(f"  child/related protocols: {d['otherProtocols']}  (rerun with their slug for per-product detail)")
    print(f"  oracles={d.get('oracles')}  forkedFrom={d.get('forkedFrom')}  audits={d.get('audits')}")
    cur = d.get("currentChainTvls") or {}
    print("  current TVL by chain (top 8):")
    for k, v in sorted(cur.items(), key=lambda kv: -num(kv[1]))[:8]:
        print(f"    {k:28s} ${num(v) / 1e6:10.1f}m")

    # What assets the protocol holds -> edges protocol -[holds]-> token
    tiu = d.get("tokensInUsd") or []
    rows = []
    if tiu:
        last = tiu[-1]
        toks = last.get("tokens") or {}
        total = sum(num(v) for v in toks.values()) or 1.0
        print(f"  asset composition on {day(last.get('date', 0))} (top 12 of {len(toks)}):")
        for sym, v in sorted(toks.items(), key=lambda kv: -num(kv[1]))[:12]:
            print(f"    {sym:20s} ${num(v) / 1e6:10.1f}m  {num(v) / total:6.1%}")
        for sym, v in toks.items():
            rows.append({"src": a.slug, "dst": f"token:{sym}", "type": "holds", "weight_usd": round(num(v), 2),
                         "share_of_protocol": round(num(v) / total, 4), "date": day(last.get("date", 0)),
                         "evidence": f"defillama:/protocol/{a.slug} tokensInUsd"})
    else:
        print("  no tokensInUsd on this slug (parent protocols often lack it - try a child slug)")
    if rows:
        print(f"  saved -> {save_csv(f'edges_holds_{a.slug}.csv', rows)}")

    hm = d.get("hallmarks") or []
    print(f"  hallmarks (annotated events, {len(hm)}):")
    for h in hm[-10:]:
        if isinstance(h, list) and len(h) >= 2:
            print(f"    {day(h[0])}  {h[1]}")
    tvl = d.get("tvl") or []
    gate(len(tvl) > 0, f"{len(tvl)} daily TVL points, {len(rows)} holds-edges")


# ------------------------------------------------------------------------- step C
def cmd_prices(a):
    coins = [c.strip() for c in a.coins.split(",") if c.strip()]
    start, end = ts(a.start), ts(a.end)
    period_s = {"1h": 3600, "4h": 14400, "1d": 86400}[a.period]
    span = min(500, math.ceil((end - start) / period_s) + 1)
    r = call(client.prices.getChart, coins, {"start": start, "span": span, "period": a.period})
    if not r:
        return gate(False, "getChart failed")
    save_json("llama_price_chart.json", r)
    rows, ok = [], 0
    for cid in coins:
        cd = (r.get("coins") or {}).get(cid)
        if not cd:
            print(f"  {cid}: NOT PRICED by DeFiLlama (use Pendle ohlcv for PT tokens)")
            continue
        pts = cd.get("prices") or []
        if len(pts) >= 2:
            ok += 1
        peak, mdd, lo = -1.0, 0.0, None
        for p in pts:
            px = num(p.get("price"))
            peak = max(peak, px)
            if peak > 0:
                mdd = max(mdd, 1 - px / peak)
            lo = px if lo is None else min(lo, px)
            rows.append({"coin": cid, "symbol": cd.get("symbol"), "date": day(p.get("timestamp", 0)), "price": px})
        print(f"  {cid} ({cd.get('symbol')}): {len(pts)} points, min={lo}, max drawdown={mdd:.2%}, "
              f"confidence={cd.get('confidence')}")
    print(f"saved -> {save_csv('prices_chart.csv', rows)}")
    gate(ok == len(coins), f"{ok}/{len(coins)} coins have a price series")


# ------------------------------------------------------------------------- step D
def cmd_stable(a):
    lst = call(client.stablecoins.getStablecoins, True)
    assets = (lst or {}).get("peggedAssets") or []
    if a.ids:
        # exact match on gecko_id: symbols are not unique (e.g. several coins called USDX)
        want = {s.strip().lower() for s in a.ids.split(",") if s.strip()}
        hits = [s for s in assets if (s.get("gecko_id") or "").lower() in want]
        missing = want - {(s.get("gecko_id") or "").lower() for s in hits}
    else:
        want = {s.strip().lower() for s in a.symbols.split(",") if s.strip()}
        hits = [s for s in assets if (s.get("symbol") or "").lower() in want]
        missing = want - {(s.get("symbol") or "").lower() for s in hits}
    print(f"{len(assets)} stablecoins listed; matched {len(hits)}:")
    for s in hits:
        circ = num((s.get("circulating") or {}).get("peggedUSD"))
        print(f"  id={s.get('id'):5s} {s.get('symbol'):8s} {s.get('name')}  gecko_id={s.get('gecko_id')}  "
              f"mechanism={s.get('pegMechanism')}  price={s.get('price')}  circulating=${circ / 1e6:.1f}m")
    if missing:
        print(f"  not in DeFiLlama's stablecoin list: {sorted(missing)}")
    time.sleep(0.5)
    hist = call(client.stablecoins.getPrices) or []
    lo, hi = ts(a.start), ts(a.end)
    keys = {s.get("gecko_id") for s in hits if s.get("gecko_id")}
    rows = []
    for row in hist:
        t = int(num(row.get("date")))
        if lo <= t <= hi:
            for k in keys:
                px = (row.get("prices") or {}).get(k)
                if px is not None:
                    rows.append({"date": day(t), "gecko_id": k, "price": px})
    if hist and not rows:
        print("  price keys look like:", list((hist[-1].get("prices") or {}).keys())[:12])
    supply = {}
    for s in hits:
        det = call(client.stablecoins.getStablecoin, str(s.get("id")))
        time.sleep(0.5)
        if not det:
            continue
        pts = [p for p in det.get("tokens") or [] if lo <= int(num(p.get("date"))) <= hi]
        supply[s.get("symbol")] = [{"date": day(p["date"]), "circulating_usd": num((p.get("circulating") or {}).get("peggedUSD"))}
                                   for p in pts]
    save_json(f"{a.out}.json", {"matched": hits, "prices": rows, "supply": supply})
    save_csv("replay_stable_prices.csv" if a.out == "replay_stablecoins" else f"{a.out}_prices.csv", rows)
    for k in sorted(keys):
        ser = [r for r in rows if r["gecko_id"] == k]
        if ser:
            low = min(ser, key=lambda r: r["price"])
            print(f"  {k}: {len(ser)} days, first={ser[0]['price']} on {ser[0]['date']}, "
                  f"low={low['price']} on {low['date']}")
    for sym, ser in supply.items():
        if ser:
            print(f"  {sym} supply: ${ser[0]['circulating_usd'] / 1e6:.1f}m ({ser[0]['date']}) -> "
                  f"${ser[-1]['circulating_usd'] / 1e6:.1f}m ({ser[-1]['date']})")
    gate(bool(rows), f"{len(rows)} price rows in window" if rows else "no prices in window")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("protocols"); s.add_argument("--focus", default="pendle,morpho,aave,ethena,euler")
    s = sub.add_parser("protocol"); s.add_argument("--slug", required=True)
    s = sub.add_parser("prices"); s.add_argument("--coins", required=True)
    s.add_argument("--start", required=True); s.add_argument("--end", required=True)
    s.add_argument("--period", default="1d", choices=["1h", "4h", "1d"])
    s = sub.add_parser("stable"); s.add_argument("--symbols", default="deUSD,xUSD,USDX,USDe")
    s.add_argument("--ids", help="comma-separated gecko_ids for an exact match, e.g. ethena-usde,elixir-deusd")
    s.add_argument("--out", default="replay_stablecoins", help="output file stem in data/")
    s.add_argument("--start", default="2025-10-25"); s.add_argument("--end", default="2025-11-20")
    a = p.parse_args()
    {"protocols": cmd_protocols, "protocol": cmd_protocol, "prices": cmd_prices, "stable": cmd_stable}[a.cmd](a)


if __name__ == "__main__":
    main()