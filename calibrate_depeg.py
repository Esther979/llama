#!/usr/bin/env python3
"""
Historical outcome frequencies of stablecoin depegs, for the default probabilities of the
"underlying_depeg" incident (resolved / partial / severe).

  python3 calibrate_depeg.py            # downloads DeFiLlama data if missing, writes data/depeg_calibration.json

Data (free endpoints, via defillama-sdk 0.1.4, same calls as llama_graph.py):
  stablecoins.llama.fi/stablecoinprices   daily prices of every stablecoin, keyed by gecko_id
  stablecoins.llama.fi/stablecoins        current list with pegType (to keep USD pegs)
Coins no longer in the current list (often dead ones) are kept when their median price is 0.9-1.1,
so the sample is not limited to survivors.

Episode rules (our choices, written into the output):
  start     a day closing below 0.97 after a functioning month (30-day median >= 0.99)
  resolved  back to >= 0.99 within 7 days
  severe    price on day 30 below 0.5
  partial   everything else
Episodes whose day 30 is after the data ends are left out. A coin starts a new episode only after it
is functioning again.

Default probabilities use episodes that stay below 0.97 for at least 2 days (drops one-day price glitches of
small coins; more conservative). "range" gives min / max over three samples: all episodes, >= 2 days, first
episode per coin.
"""
import argparse
import datetime as dt
import json
import os
import statistics
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "data")
START, BACK, QUICK_DAYS, HORIZON, SEVERE = 0.97, 0.99, 7, 30, 0.5
KNOWN = [   # (gecko_id, a date inside the episode, expected outcome) - used as gates
    ("usd-coin", "2023-03-11", "resolved"),     # SVB weekend, back within days
    ("terrausd", "2022-05-10", "severe"),       # UST collapse
    ("elixir-deusd", "2025-11-06", "severe"),   # deUSD, Stream xUSD contagion
]


def day(t):
    return dt.datetime.fromtimestamp(int(t), dt.timezone.utc).strftime("%Y-%m-%d")


def load(data_dir):
    d = os.path.join(data_dir, "stablecoins")
    pf, lf = os.path.join(d, "stablecoinprices.json"), os.path.join(d, "stablecoins.json")
    if not (os.path.exists(pf) and os.path.exists(lf)):
        from defillama_sdk import DefiLlama          # only needed to download
        os.makedirs(d, exist_ok=True)
        c = DefiLlama()
        json.dump(c.stablecoins.getPrices(), open(pf, "w"))
        time.sleep(0.5)
        json.dump(c.stablecoins.getStablecoins(True), open(lf, "w"))
    with open(pf) as f:
        px = json.load(f)
    with open(lf) as f:
        lst = json.load(f)["peggedAssets"]
    return px, lst, pf


def series(px, lst):
    peg = {x["gecko_id"]: x["pegType"] for x in lst if x.get("gecko_id")}
    s = {}
    for row in px:
        t = int(row["date"])
        if t <= 0:                                   # first row has date 0 (placeholder)
            continue
        for k, v in (row.get("prices") or {}).items():
            if isinstance(v, (int, float)) and v > 0:
                s.setdefault(k, []).append((t, float(v)))
    keep, why = {}, {"usd_listed": 0, "unlisted_kept": 0, "non_usd": 0, "unlisted_dropped": 0}
    for k, pts in s.items():
        pts.sort()
        if k in peg:
            if peg[k] == "peggedUSD":
                keep[k] = pts
                why["usd_listed"] += 1
            else:
                why["non_usd"] += 1
        elif 0.9 <= statistics.median(p for _, p in pts) <= 1.1:
            keep[k] = pts
            why["unlisted_kept"] += 1
        else:
            why["unlisted_dropped"] += 1
    return keep, why


def episodes(k, pts, data_end):
    out, i, n = [], 0, len(pts)
    while i < n:
        t, p = pts[i]
        prior = [q for (u, q) in pts[max(0, i - 30):i] if t - u <= 31 * 86400]
        if p < START and len(prior) >= 20 and statistics.median(prior) >= BACK:
            end30 = t + HORIZON * 86400
            if end30 > data_end:
                break                                # censored
            quick = any(q >= BACK for (u, q) in pts[i + 1:] if u <= t + QUICK_DAYS * 86400)
            nxt = next(((u, q) for (u, q) in pts[i + 1:i + 2]), None)
            one_day = nxt is not None and nxt[0] - t <= 86400 + 3600 and nxt[1] >= BACK
            later = [q for (u, q) in pts[i:] if u <= end30]
            p30 = later[-1]
            low = min(later)
            outcome = "resolved" if quick else ("severe" if p30 < SEVERE else "partial")
            out.append({"gecko_id": k, "start": day(t), "price_start": p, "low_30d": low, "price_30d": p30,
                        "back_next_day": one_day, "outcome": outcome})
            # skip until functioning again (30 days at a median >= BACK)
            j = i + 1
            while j < n:
                window = [q for (u, q) in pts[j:] if u <= pts[j][0] + 30 * 86400]
                if len(window) >= 20 and statistics.median(window) >= BACK and pts[j][1] >= BACK:
                    break
                j += 1
            i = j
        else:
            i += 1
    return out


def run(data_dir):
    px, lst, pf = load(data_dir)
    s, why = series(px, lst)
    data_end = max(int(r["date"]) for r in px)
    eps = [e for k, pts in sorted(s.items()) for e in episodes(k, pts, data_end)]
    outcomes = ("resolved", "partial", "severe")

    def freq(es):
        k = {o: sum(e["outcome"] == o for e in es) for o in outcomes}
        return {"n": len(es), "counts": k, "probabilities": {o: k[o] / len(es) for o in outcomes} if es else None}

    first = {}
    for e in eps:
        first.setdefault(e["gecko_id"], e)
    samples = {"all": freq(eps), "min_2_days": freq([e for e in eps if not e["back_next_day"]]),
               "first_per_coin": freq(list(first.values()))}
    default = samples["min_2_days"]
    rng = {o: [min(v["probabilities"][o] for v in samples.values()),
               max(v["probabilities"][o] for v in samples.values())] for o in outcomes}
    used = [e for e in eps if not e["back_next_day"]]
    loss = {o: (statistics.median(1 - e["price_30d"] for e in used if e["outcome"] == o)
                if default["counts"][o] else None) for o in outcomes}
    gates = []
    for gid, d0, want in KNOWN:
        hit = [e for e in eps if e["gecko_id"] == gid and abs((dt.date.fromisoformat(e["start"]) -
                                                               dt.date.fromisoformat(d0)).days) <= 10]
        got = hit[0]["outcome"] if hit else None
        gates.append({"check": f"{gid} episode near {d0} classified {want}", "got": got, "pass": got == want,
                      "episode": hit[0] if hit else None})
    return {
        "source": "DeFiLlama stablecoins.llama.fi/stablecoinprices (daily, by gecko_id) + /stablecoins (pegType)",
        "file": os.path.relpath(pf, HERE), "data_from": day(min(t for p in s.values() for t, _ in p)),
        "data_to": day(data_end), "coins": len(s), "coin_selection": why,
        "rules": {"start_below": START, "functioning_median": BACK, "resolved_within_days": QUICK_DAYS,
                  "horizon_days": HORIZON, "severe_below_at_horizon": SEVERE},
        "default_sample": "min_2_days", "n_episodes": default["n"], "counts": default["counts"],
        "probabilities": default["probabilities"], "range": rng, "samples": samples,
        "median_loss_at_horizon": loss,
        "gates": gates, "all_gates_pass": all(g["pass"] for g in gates),
        "episodes": eps,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", default=OUT_DIR)
    a = ap.parse_args()
    r = run(a.data_dir)
    print(f"{r['coins']} USD stablecoins {r['coin_selection']}, {r['data_from']} .. {r['data_to']}")
    for name, v in r["samples"].items():
        print(f"  {name:15s} {v['n']:4d} episodes: " + ", ".join(f"{k} {p:.1%}" for k, p in v["probabilities"].items()))
    if r["probabilities"]:
        print(f"default ({r['default_sample']}): " + ", ".join(
            f"{k} {v:.1%} [{r['range'][k][0]:.1%}-{r['range'][k][1]:.1%}]" for k, v in r["probabilities"].items()))
        print("median loss on day 30: " + ", ".join(f"{k} {v:.1%}" if v is not None else f"{k} -"
                                                     for k, v in r["median_loss_at_horizon"].items()))
    for g in r["gates"]:
        print(f"GATE {'PASS' if g['pass'] else 'FAIL'}  {g['check']}: got {g['got']}"
              + (f" (start {g['episode']['start']}, low {g['episode']['low_30d']:.4f}, day 30 "
                 f"{g['episode']['price_30d']:.4f})" if g["episode"] else ""))
    path = os.path.join(a.data_dir, "depeg_calibration.json")
    with open(path, "w") as f:
        json.dump(r, f, indent=1)
    print(f"saved -> {path}")
    if not r["all_gates_pass"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
