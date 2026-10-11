#!/usr/bin/env python3
"""
Check that web/risk_model.js gives the same numbers as the Python backend (needs node).

  python3 check_js_port.py [--n 500]

Random cases (unlevered / levered, oracle true / false / unknown, shocks up to 100%, meta-oracle rules, collateral at
the oracle price apart from the market value, exit caps off the 1% grid) for positionLoss, oracleFalls, decide and
breakEven, compared field by field; then the sample dashboard at several position sizes and wallets (atSize, inject,
decideAt, breakEvenSeverity, sensitivity, timeline) and the vault files. Prints GATE PASS / GATE FAIL.
"""
import argparse
import json
import os
import random
import subprocess
import sys
import tempfile

from decision_core import Scenario as DScenario, decide
from incidents import exit_costs
from loss_model import Position, Scenario, position_loss
from oracle_types import oracle_falls

HERE = os.path.dirname(os.path.abspath(__file__))
JS = os.path.join(HERE, "web", "risk_model.js")
CURVE = [[0.01, 0.000153], [0.05, 0.000199], [0.1, 0.00033], [0.25, 0.00082], [0.3, 0.001375], [0.35, 0.002124],
         [0.4, 0.003135], [0.45, 0.004909]]
ORACLES = [
    {"kind": "meta_oracle_timelock", "tracks_market": False, "tracks_underlying": False,
     "tracks_market_after_switch": False, "tracks_underlying_after_switch": True,
     "deviation_threshold": 0.0075, "challenge_timelock_s": 57600,
     "underlying_assets": [], "underlying_assets_after_switch": ["usde"]},
    {"kind": "meta_oracle_timelock", "tracks_market": False, "tracks_underlying": False,
     "tracks_market_after_switch": None, "tracks_underlying_after_switch": None,
     "deviation_threshold": 0.01, "challenge_timelock_s": 3600},
    {"kind": "morpho_chainlink_v2", "tracks_market": True, "tracks_underlying": None},
    {"kind": "morpho_chainlink_v2", "tracks_market": False, "tracks_underlying": True, "underlying_assets": ["usde"]},
    {"kind": "linear_discount", "tracks_market": False, "tracks_underlying": False},
    {"kind": "unknown", "tracks_market": None, "tracks_underlying": None},
]


def cases(n, rnd):
    out = []
    for i in range(n):
        C = rnd.choice([1e5, 1e6, 1e7, rnd.uniform(1e4, 2e7)])
        lltv = rnd.choice([0.77, 0.86, 0.915, 0.945])
        D = 0.0 if rnd.random() < 0.25 else C * lltv * rnd.uniform(0.3, 0.999)
        flag = rnd.choice([True, False, None])
        s = {"layer": rnd.choice([2, 3]), "shock": rnd.choice([0.0162, 0.0297, 0.5, 0.9987, 1.0, rnd.random()]),
             "permanent": rnd.choice([0.0, 0.5, 1.0, rnd.random()]), "hours": rnd.choice([None, 1, 24, rnd.uniform(0, 48)])}
        p = {"collateral_usd": C, "debt_usd": D, "lltv": lltv, "can_hold": rnd.random() < 0.5,
             "oracle_tracks_underlying": flag if s["layer"] == 2 else rnd.choice([True, False, None]),
             "oracle_tracks_market": flag if s["layer"] == 3 else rnd.choice([True, False, None]),
             "collateral_oracle_usd": None if rnd.random() < 0.5 else C * rnd.uniform(0.98, 1.02)}
        k = 1.0 if rnd.random() < 0.5 else rnd.uniform(0.1, 2.2)       # cap = 0.45 k: mostly off the 1% grid
        curve = [[min(1.0, x * k), y] for x, y in CURVE if x * k <= 1.0] or [[1.0, CURVE[0][1]]]
        out.append({"s": s, "p": p, "curve": curve, "oracle": rnd.choice(ORACLES), "token": rnd.choice([None, "USDe", "sUSDe"]),
                    "prob": rnd.random() ** 3,
                    "L": rnd.random(), "carry": rnd.choice([0.0, 0.001, rnd.uniform(0, 0.01)]),
                    "scale": rnd.choice([1.0, rnd.uniform(1, 12)])})
    return out


def python_side(c):
    s, p = c["s"], c["p"]
    r = position_loss(Scenario("t", s["layer"], s["shock"], s["permanent"], s["hours"], "", False),
                      Position("t", p["collateral_usd"], p["debt_usd"], p["lltv"], p["can_hold"],
                               p["oracle_tracks_underlying"], p["oracle_tracks_market"], p["collateral_oracle_usd"]))
    d = decide([DScenario("e", c["prob"], c["L"])], [tuple(x) for x in c["curve"]], carry_lost=c["carry"])
    ec = exit_costs(CURVE, None, 1.0)
    f = lambda x: (x + c["carry"]) * c["scale"] / c["L"] if c["L"] > 0 else None
    return {"L_low": r["L_low"], "L_high": r["L_high"], "oracle_known": r["oracle_known"],
            "branches": [[b["oracle_falls"], b["liquidated"], b["bad_debt_usd"], b["loss_of_equity"]]
                         for b in r["branches"]],
            "oracle_falls": oracle_falls(c["oracle"], s["layer"], s["shock"], s["hours"], c["token"]),
            "exit_fraction": d["best_exit_fraction"], "expected_cost": d["expected_total_cost_at_best"],
            "be": [f(ec["cost_first"]), f(ec["cost_avg_cap"]), f(ec["cost_marginal_cap"])]}


NODE = r"""
const M = require(process.argv[2]); const cs = JSON.parse(require('fs').readFileSync(process.argv[3]));
const curve = JSON.parse(process.argv[4]);
console.log(JSON.stringify(cs.map(c => {
  const r = M.positionLoss(c.s, c.p), d = M.decide(c.prob, c.L, c.curve, c.carry), b = M.breakEven(curve, c.L, c.scale, c.carry);
  return {L_low: r.L_low, L_high: r.L_high, oracle_known: r.oracle_known,
          branches: r.branches.map(x => [x.oracle_falls, x.liquidated, x.bad_debt_usd, x.loss_of_equity]),
          oracle_falls: M.oracleFalls(c.oracle, c.s.layer, c.s.shock, c.s.hours, c.token),
          exit_fraction: d.exitFraction, expected_cost: d.expectedCost,
          be: [b.p_start, b.p_exit_sellable, b.p_sell_to_cap]};
})));
"""


def same(a, b, tol=1e-9):
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same(x, y, tol) for x, y in zip(a, b))
    if isinstance(a, bool) or isinstance(b, bool) or a is None or b is None:
        return a == b
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=500)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--dashboard", default=os.path.join(HERE, "sample_data", "dashboard.sample.json"),
                    help="dashboard for the PT-view checks (e.g. one exported with onchain_positions.py --wallet)")
    a = ap.parse_args()
    cs = cases(a.n, random.Random(a.seed))
    with tempfile.TemporaryDirectory() as d:
        cf, sf = os.path.join(d, "cases.json"), os.path.join(d, "run.js")
        json.dump(cs, open(cf, "w"))
        open(sf, "w").write(NODE)
        js = json.loads(subprocess.run(["node", sf, JS, cf, json.dumps(CURVE)], check=True, capture_output=True,
                                       text=True).stdout)
    fails = {}
    for i, (c, j) in enumerate(zip(cs, js)):
        py = python_side(c)
        for k in py:
            if not same(py[k], j[k]):
                fails.setdefault(k, []).append((i, py[k], j[k]))
    for k in ("L_low", "L_high", "oracle_known", "branches", "oracle_falls", "exit_fraction", "expected_cost", "be"):
        n_bad = len(fails.get(k, []))
        print(f"GATE {'PASS' if not n_bad else 'FAIL'}  {k}: {len(cs) - n_bad}/{len(cs)} equal"
              + (f"  first mismatch {fails[k][0]}" if n_bad else ""))
    # fault injection on the Risk Desk's nodes, on the real sample dashboard
    dpath = a.dashboard
    d = json.load(open(dpath))
    from frontend_contract import inject
    combos = [(pk, k.split(":")[0], k.split(":")[1], sev) for pk in d["position_presets"] for k in d["ui"]["injections"]
              for sev in (0.5, 1, 2.77, 10, 50, 99)]
    with tempfile.TemporaryDirectory() as tmp:
        cf, sf = os.path.join(tmp, "c.json"), os.path.join(tmp, "i.js")
        json.dump(combos, open(cf, "w"))
        open(sf, "w").write("const M=require(process.argv[2]);const d=require(process.argv[3]);"
                            "const cs=JSON.parse(require('fs').readFileSync(process.argv[4]));"
                            "console.log(JSON.stringify(cs.map(c=>M.inject(d,c[0],c[1],c[2],c[3]))));")
        jout = json.loads(subprocess.run(["node", sf, JS, dpath, cf], check=True, capture_output=True, text=True).stdout)
    keys = ("L_low", "L_high", "loss_usd", "oracle_falls", "liquidated", "sellable_later", "avg_cost_later")
    bad = [(c, k, inject(d, *c)[k], j.get(k)) for c, j in zip(combos, jout) for k in keys if not same(inject(d, *c)[k], j.get(k))]
    print(f"GATE {'PASS' if not bad else 'FAIL'}  inject: {len(combos)} (preset, node, failure, severity) combinations "
          f"equal on {', '.join(keys)}" + (f"  first mismatch {bad[0]}" if bad else ""))
    # decision without a probability (PT view): decideAt and breakEvenSeverity on the sample dashboard
    from frontend_contract import break_even_severity, decide_at
    dcombos = [(pk, k.split(":")[0], k.split(":")[1], sev, carry) for pk in d["position_presets"]
               for k in d["ui"]["injections"] for sev in (0.5, 2, 10, 50) for carry in (0.0, 0.002)]
    bcombos = [(pk, k.split(":")[0], k.split(":")[1], carry) for pk in d["position_presets"]
               for k in d["ui"]["injections"] for carry in (0.0, 0.002)]
    with tempfile.TemporaryDirectory() as tmp:
        cf, bf, sf = os.path.join(tmp, "d.json"), os.path.join(tmp, "b.json"), os.path.join(tmp, "d.js")
        json.dump(dcombos, open(cf, "w"))
        json.dump(bcombos, open(bf, "w"))
        open(sf, "w").write("const M=require(process.argv[2]);const d=require(process.argv[3]);const fs=require('fs');"
                            "const a=JSON.parse(fs.readFileSync(process.argv[4])),b=JSON.parse(fs.readFileSync(process.argv[5]));"
                            "console.log(JSON.stringify([a.map(c=>M.decideAt(d,c[0],c[1],c[2],c[3],c[4])),"
                            "b.map(c=>M.breakEvenSeverity(d,c[0],c[1],c[2],c[3]))]));")
        jd, jb = json.loads(subprocess.run(["node", sf, JS, dpath, cf, bf], check=True, capture_output=True, text=True).stdout)
    dk = ("verdict", "sell_fraction", "sale_cost_usd", "loss_if_stay_usd", "loss_kept_usd", "stuck_fraction")
    dbad = [(c, k) for c, j in zip(dcombos, jd) for k in dk
            if not (decide_at(d, *c)[k] == j[k] if k == "verdict" else same(decide_at(d, *c)[k], j[k]))]
    bbad = [(c, k) for c, j in zip(bcombos, jb) for k in ("start", "cap")
            if not same(break_even_severity(d, *c)[k], j[k], 1e-7)]
    print(f"GATE {'PASS' if not dbad else 'FAIL'}  decideAt: {len(dcombos)} combinations equal on {', '.join(dk)}"
          + (f"  first mismatch {dbad[0]}" if dbad else ""))
    print(f"GATE {'PASS' if not bbad else 'FAIL'}  breakEvenSeverity: {len(bcombos)} combinations equal"
          + (f"  first mismatch {bbad[0]}" if bbad else ""))
    bad = bad + dbad + bbad

    # sensitivity (no probability): same candidates, flips, effects and weakest link
    from frontend_contract import carry_of, sensitivity
    ccombos = [(alt, days) for alt in (None, 0.0, 0.02, 0.04, 0.0501, 0.08) for days in (None, 0.5, 10, 46, 100)]
    with tempfile.TemporaryDirectory() as tmp:
        cf, sf = os.path.join(tmp, "c.json"), os.path.join(tmp, "c.js")
        json.dump(ccombos, open(cf, "w"))
        open(sf, "w").write("const M=require(process.argv[2]);const d=require(process.argv[3]);"
                            "const a=JSON.parse(require('fs').readFileSync(process.argv[4]));"
                            "console.log(JSON.stringify(a.map(c=>M.carryOf(d,c[0],c[1]))));")
        jc = json.loads(subprocess.run(["node", sf, JS, dpath, cf], check=True, capture_output=True, text=True).stdout)
    cbad = [c for c, j in zip(ccombos, jc) if not same(carry_of(d, *c), j)]
    print(f"GATE {'PASS' if not cbad else 'FAIL'}  carryOf: {len(ccombos)} (cash APY, days) cases equal"
          + (f"  first mismatch {cbad[0]}" if cbad else ""))
    bad = bad + cbad
    c4 = carry_of(d, 0.04)
    scombos = [(pk, k.split(":")[0], k.split(":")[1], sev, c) for pk in d["position_presets"]
               for k in d["ui"]["injections"] for sev in (0.5, 2, 10) for c in (0.0, c4)]
    with tempfile.TemporaryDirectory() as tmp:
        cf, sf = os.path.join(tmp, "s.json"), os.path.join(tmp, "s.js")
        json.dump(scombos, open(cf, "w"))
        open(sf, "w").write("const M=require(process.argv[2]);const d=require(process.argv[3]);"
                            "const a=JSON.parse(require('fs').readFileSync(process.argv[4]));"
                            "console.log(JSON.stringify(a.map(c=>M.sensitivity(d,c[0],c[1],c[2],c[3],c[4]))));")
        js_sens = json.loads(subprocess.run(["node", sf, JS, dpath, cf], check=True, capture_output=True, text=True).stdout)
    sbad = []
    for c, j in zip(scombos, js_sens):
        py = sensitivity(d, *c)
        okk = py["verdict"] == j["verdict"] and len(py["candidates"]) == len(j["candidates"]) and all(
            a["key"] == b["key"] and a["verdict"] == b["verdict"] and a["flips"] == b["flips"] and same(a["effect"], b["effect"])
            for a, b in zip(py["candidates"], j["candidates"])) and \
            ((py["weakest"] is None and j["weakest"] is None) or
             (py["weakest"] and j["weakest"] and py["weakest"]["alternative"] == j["weakest"]["alternative"]))
        if not okk:
            sbad.append(c)
    print(f"GATE {'PASS' if not sbad else 'FAIL'}  sensitivity: {len(scombos)} combinations equal (candidates, flips, "
          f"effects, weakest)" + (f"  first mismatch {sbad[0]}" if sbad else ""))
    bad = bad + sbad

    # timeline (incident duration): every point of every timeline
    from frontend_contract import timeline_pt
    tcombos = [(pk, k.split(":")[0], k.split(":")[1], sev, rec) for pk in d["position_presets"]
               for k in d["ui"]["injections"] for sev in (2, 10) for rec in (True, False)]
    with tempfile.TemporaryDirectory() as tmp:
        cf, sf = os.path.join(tmp, "t.json"), os.path.join(tmp, "t.js")
        json.dump(tcombos, open(cf, "w"))
        open(sf, "w").write("const M=require(process.argv[2]);const d=require(process.argv[3]);"
                            "const a=JSON.parse(require('fs').readFileSync(process.argv[4]));"
                            "console.log(JSON.stringify(a.map(c=>{const t=M.timeline(d,c[0],c[1],c[2],c[3],c[4]);"
                            "return [t, M.timelineSummary(d,c[0],t)];})));")
        jout = json.loads(subprocess.run(["node", sf, JS, dpath, cf], check=True, capture_output=True, text=True).stdout)
        jt, jsum = [x[0] for x in jout], [x[1] for x in jout]
    from frontend_contract import timeline_summary
    tk = ("hours", "verdict", "L_high", "loss_if_stay_usd", "sell_fraction", "oracle_falls", "pt_price_market",
          "pt_price_oracle", "position_value_usd", "debt_usd", "carry")
    tbad = []
    for c, j in zip(tcombos, jt):
        py = timeline_pt(d, *c)
        if len(py) != len(j) or not all((a[k] == b[k]) if isinstance(a[k], (str, bool)) or a[k] is None else same(a[k], b[k])
                                        for a, b in zip(py, j) for k in tk):
            tbad.append(c)
        elif timeline_summary(d, c[0], py) != jsum[tcombos.index(c)]:
            tbad.append(("summary",) + c)
    print(f"GATE {'PASS' if not tbad else 'FAIL'}  timeline: {len(tcombos)} timelines equal at every duration"
          + (f"  first mismatch {tbad[0]}" if tbad else ""))
    bad = bad + tbad

    # position size (the manager's input) and wallets: atSize, then the PT-view functions on the resized dashboard
    from frontend_contract import at_size, decide_at_duration
    sizes = [5e3, 1e5, 1e6, 3.25e6, 4.5e6, 7e6, 1e7, 5e7]
    wallets = [None] + [b["address"] for b in d["borrowers"]["list"][:3]] + \
              [w["address"] for w in d["borrowers"].get("wallets") or []] + ["0x0000000000000000000000000000000000000001"]
    zcombos = [(sz, w) for sz in sizes for w in (wallets if sz == 1e7 else [None, wallets[1]])]
    inj = ["usde:depeg", "susde:navLoss", "oracle:oracleLow", "lending:cascade", "market:drain", "pt:depeg"]
    with tempfile.TemporaryDirectory() as tmp:
        cf, sf = os.path.join(tmp, "z.json"), os.path.join(tmp, "z.js")
        json.dump([zcombos, inj], open(cf, "w"))
        open(sf, "w").write("const M=require(process.argv[2]);const d0=require(process.argv[3]);"
                            "const [zs,inj]=JSON.parse(require('fs').readFileSync(process.argv[4]));"
                            "console.log(JSON.stringify(zs.map(([sz,w])=>{const d=M.atSize(d0,sz,w);"
                            "const dec=[];for(const pk of Object.keys(d.position_presets))for(const k of inj)for(const sev of [0.5,2,10,40])"
                            "for(const c of [0,0.002])dec.push(M.decideAt(d,pk,k.split(':')[0],k.split(':')[1],sev,c));"
                            "const be=[];for(const pk of Object.keys(d.position_presets))for(const k of inj)"
                            "be.push(M.breakEvenSeverity(d,pk,k.split(':')[0],k.split(':')[1],0));"
                            "const pk=Object.keys(d.position_presets);"
                            "const tl=pk.map(p=>M.timeline(d,p,'usde','depeg',2,false,0.04));"
                            "const sv=pk.map(p=>M.sensitivity(d,p,'susde','navLoss',2,0));"
                            "return {presets:d.position_presets,wallet_found:d.wallet_found===undefined?null:d.wallet_found,"
                            "wallet_read:d.wallet_read===undefined?null:d.wallet_read,"
                            "exit_curve:d.exit_curve,max:d.max_exit_fraction,later:d.borrowers.exit_later,dec,be,tl,sv};})));")
        jz = json.loads(subprocess.run(["node", sf, JS, dpath, cf], check=True, capture_output=True, text=True).stdout)
    zbad = []
    pkeys = ("collateral_usd", "collateral_oracle_usd", "pt_units", "debt_usd", "ltv", "lltv", "sized", "label")
    for (sz, w), j in zip(zcombos, jz):
        dz = at_size(d, sz, w)
        if dz.get("wallet_found") != j["wallet_found"] or dz.get("wallet_read") != j["wallet_read"] or \
                list(dz["position_presets"]) != list(j["presets"]):
            zbad.append((sz, w, "presets / wallet_found"))
            continue
        for pk, p in dz["position_presets"].items():
            for k in pkeys:
                if not (p.get(k) == j["presets"][pk].get(k) if isinstance(p.get(k), (str, bool)) or p.get(k) is None
                        else same(p[k], j["presets"][pk][k])):
                    zbad.append((sz, w, pk, k))
        if not same([[x["fraction"], x["usd"], x["loss"], x["gas_usd"]] for x in dz["exit_curve"]],
                     [[x["fraction"], x["usd"], x["loss"], x["gas_usd"]] for x in j["exit_curve"]]) or \
                not same(dz["max_exit_fraction"], j["max"]):
            zbad.append((sz, w, "exit_curve"))
        lk = ("oracle_drop", "seized_usd", "sellable_now", "avg_cost_now", "sellable_later", "avg_cost_later",
              "market_impact_of_liquidations")
        if not same([[r[k] for k in lk] for r in dz["borrowers"]["exit_later"]], [[r[k] for k in lk] for r in j["later"]]):
            zbad.append((sz, w, "exit_later"))
        i = 0
        for pk in dz["position_presets"]:
            for k in inj:
                for sev in (0.5, 2, 10, 40):
                    for c in (0.0, 0.002):
                        py, jj = decide_at(dz, pk, *k.split(":"), sev, c), j["dec"][i]
                        i += 1
                        for f in dk + ("sell_usd", "sellable_now", "sellable_later", "avg_cost_later", "liquidated"):
                            if not (py[f] == jj[f] if isinstance(py[f], str) else same(py[f], jj[f])):
                                zbad.append((sz, w, pk, k, sev, c, f, py[f], jj[f]))
        i = 0
        for pk in dz["position_presets"]:
            for k in inj:
                py, jj = break_even_severity(dz, pk, *k.split(":"), 0.0), j["be"][i]
                i += 1
                if not (same(py["start"], jj["start"], 1e-7) and same(py["cap"], jj["cap"], 1e-7)):
                    zbad.append((sz, w, pk, k, "breakEvenSeverity"))
        for pk, jt, js in zip(dz["position_presets"], j["tl"], j["sv"]):
            pt = timeline_pt(dz, pk, "usde", "depeg", 2, False, 0.04)
            tk2 = tk + ("collateral_usd", "sale_cost_usd")
            if len(pt) != len(jt) or not all((a[k] == b[k]) if isinstance(a[k], (str, bool)) or a[k] is None
                                             else same(a[k], b[k]) for a, b in zip(pt, jt) for k in tk2):
                zbad.append((sz, w, pk, "timeline"))
            ps = sensitivity(dz, pk, "susde", "navLoss", 2, 0.0)
            if ps["verdict"] != js["verdict"] or [x["verdict"] for x in ps["candidates"]] != \
                    [x["verdict"] for x in js["candidates"]]:
                zbad.append((sz, w, pk, "sensitivity"))
    n_dec = sum(len(at_size(d, sz, w)["position_presets"]) for sz, w in zcombos) * len(inj) * 8
    print(f"GATE {'PASS' if not zbad else 'FAIL'}  position size: {len(zcombos)} (size, wallet) cases equal on atSize "
          f"(presets, exit curve, exit later), {n_dec} decideAt, breakEvenSeverity, timelines and sensitivity"
          + (f"  first mismatch {zbad[0]}" if zbad else ""))
    bad = bad + zbad

    # reasons (PT view): decisionText, same text as Python, every number from the model
    from frontend_contract import decision_text
    from frontend_contract import past_incidents
    pis = d.get("past_incidents") or past_incidents()
    xcombos = [(sz, pk, k, sev, c, None) for sz in (1e6, 1e7) for pk in at_size(d, sz)["position_presets"]
               for k in d["ui"]["injections"] for sev in (0.5, 2, 10, 40) for c in (0.0, carry_of(d, 0.04))] + \
              [(sz, pk, f"{pi['node']}:{pi['fail']}", pi["sev"], c, pi["opts"]) for sz in (1e6, 1e7)
               for pk in at_size(d, sz)["position_presets"] for pi in pis for c in (0.0, carry_of(d, 0.04))]
    pi_bad = [pi["key"] for pi in pis if f"{pi['node']}:{pi['fail']}" not in d["ui"]["injections"]
              or pi["fail"] not in d["ui"]["nodes"][pi["node"]]["failures"]]
    print(f"GATE {'PASS' if not pi_bad else 'FAIL'}  past_incidents: {len(pis)} incidents point to an existing node and "
          f"failure" + (f": not {pi_bad}" if pi_bad else ""))
    with tempfile.TemporaryDirectory() as tmp:
        cf, sf = os.path.join(tmp, "x.json"), os.path.join(tmp, "x.js")
        json.dump(xcombos, open(cf, "w"))
        open(sf, "w").write("const M=require(process.argv[2]);const d0=require(process.argv[3]);"
                            "const a=JSON.parse(require('fs').readFileSync(process.argv[4]));const cache={};"
                            "console.log(JSON.stringify(a.map(c=>{const d=cache[c[0]]||(cache[c[0]]=M.atSize(d0,c[0]));"
                            "const k=c[2].split(':');return M.decisionText(d,c[1],k[0],k[1],c[3],c[4],c[5]);})));")
        jx = json.loads(subprocess.run(["node", sf, JS, dpath, cf], check=True, capture_output=True, text=True).stdout)
    sized = {sz: at_size(d, sz) for sz in (1e6, 1e7)}
    xbad, xunchecked = [], []
    for c, j in zip(xcombos, jx):
        py = decision_text(sized[c[0]], c[1], *c[2].split(":"), c[3], c[4], c[5])
        if py != j:
            xbad.append(c)
        if py["unchecked"]:
            xunchecked.append((c, py["unchecked"]))
    print(f"GATE {'PASS' if not xbad else 'FAIL'}  decisionText: {len(xcombos)} cases give the same text in JS and Python"
          + (f"  first mismatch {xbad[0]}" if xbad else ""))
    print(f"GATE {'PASS' if not xunchecked else 'FAIL'}  decisionText: every number in the text comes from the model"
          + (f"  first {xunchecked[0]}" if xunchecked else ""))
    bad = bad + xbad + xunchecked + pi_bad

    # propagation (PT view): the five layers step by step; same text as Python, every number from the model, and each
    # layer's state agrees with decideAt (oracle follows <-> layer 3 hit, liquidated <-> layer 5 hit)
    from frontend_contract import propagation
    pcombos = xcombos + [(sz, pk, k, sev, c, o) for sz in (1e6, 1e7) for pk in at_size(d, sz)["position_presets"]
                         for k in d["ui"]["injections"] for sev in (0.5, 3) for c in (carry_of(d, 0.04),)
                         for o in ({"hours": 6}, {"hours": 24, "permanent": 0})]
    with tempfile.TemporaryDirectory() as tmp:
        cf, sf = os.path.join(tmp, "p.json"), os.path.join(tmp, "p.js")
        json.dump(pcombos, open(cf, "w"))
        open(sf, "w").write("const M=require(process.argv[2]);const d0=require(process.argv[3]);"
                            "const a=JSON.parse(require('fs').readFileSync(process.argv[4]));const cache={};"
                            "console.log(JSON.stringify(a.map(c=>{const d=cache[c[0]]||(cache[c[0]]=M.atSize(d0,c[0]));"
                            "const k=c[2].split(':');return M.propagation(d,c[1],k[0],k[1],c[3],c[4],c[5]);})));")
        jp = json.loads(subprocess.run(["node", sf, JS, dpath, cf], check=True, capture_output=True, text=True).stdout)
    pbad, punchecked, pstate = [], [], []
    for c, j in zip(pcombos, jp):
        node, fail = c[2].split(":")
        py = propagation(sized[c[0]], c[1], node, fail, c[3], c[4], c[5])
        if py != j:
            pbad.append(c)
        if py["unchecked"]:
            punchecked.append((c, py["unchecked"]))
        r = decide_at(sized[c[0]], c[1], node, fail, c[3], c[4], c[5])
        lay = {x["n"]: x["state"] for x in py["layers"]}
        if r["type"] == "loss_model" and node not in ("feeds", "oracle"):
            if (lay[3] == "hit") != (r["oracle_falls"] is True):
                pstate.append((c, "layer 3"))
        if r["type"] == "loss_model" and node != "lending" and sized[c[0]]["position_presets"][c[1]]["debt_usd"] > 0 \
                and c[5] is None:
            if (lay[5] == "hit") != any(r["liquidated"] or []):
                pstate.append((c, "layer 5"))
        if lay[py["origin"]["layer"]] != "origin" or py["steps"][-1]["text"].split(":")[0] != r["verdict"]:
            pstate.append((c, "origin / verdict"))
    print(f"GATE {'PASS' if not pbad else 'FAIL'}  propagation: {len(pcombos)} cases give the same layers and text in JS "
          f"and Python" + (f"  first mismatch {pbad[0]}" if pbad else ""))
    print(f"GATE {'PASS' if not punchecked else 'FAIL'}  propagation: every number in the text comes from the model"
          + (f"  first {punchecked[0]}" if punchecked else ""))
    print(f"GATE {'PASS' if not pstate else 'FAIL'}  propagation: layer states agree with decideAt (oracle follows, "
          f"liquidated, origin, verdict)" + (f"  first {pstate[0]}" if pstate else ""))
    bad = bad + pbad + punchecked + pstate

    # propagation along the duration slider: propagationEvents, same events in JS and Python; each event is a real
    # change (the propagation just before differs from just after) and no change is missed between events
    import math
    from frontend_contract import propagation_events, propagation_at_duration
    ecombos = [(pk, k, sev, rec) for pk in sized[1e7]["position_presets"] for k in d["ui"]["injections"]
               for sev in (0.5, 3, 20) for rec in (True, False)]
    with tempfile.TemporaryDirectory() as tmp:
        cf, sf = os.path.join(tmp, "e.json"), os.path.join(tmp, "e.js")
        json.dump(ecombos, open(cf, "w"))
        open(sf, "w").write("const M=require(process.argv[2]);const d=M.atSize(require(process.argv[3]),1e7);"
                            "const a=JSON.parse(require('fs').readFileSync(process.argv[4]));"
                            "console.log(JSON.stringify(a.map(c=>{const k=c[1].split(':');"
                            "return M.propagationEvents(d,c[0],k[0],k[1],c[2],c[3],0.04);})));")
        je = json.loads(subprocess.run(["node", sf, JS, dpath, cf], check=True, capture_output=True, text=True).stdout)
    dz = sized[1e7]
    sig = lambda pg: [(x["node"], x["state"]) for x in pg["steps"]] + [("verdict", pg["verdict"])]
    ebad, ereal, n_ev, rnd = [], [], 0, random.Random(7)
    for c, j in zip(ecombos, je):
        node, fail = c[1].split(":")
        py = propagation_events(dz, c[0], node, fail, c[2], c[3], 0.04)
        if len(py["events"]) != len(j["events"]) or py["start"] != j["start"] or \
                any(not same(a["hours"], b["hours"], 1e-6) or {k: v for k, v in a.items() if k != "hours"} !=
                    {k: v for k, v in b.items() if k != "hours"} for a, b in zip(py["events"], j["events"])):
            ebad.append(c)
        at = lambda h: sig(propagation_at_duration(dz, c[0], node, fail, c[2], h, c[3], 0.04))
        for ev in py["events"]:
            n_ev += 1
            if at(ev["hours"] * (1 - 1e-5)) == at(ev["hours"] * (1 + 1e-5)):
                ereal.append((c, ev["hours"], "no change at the event"))
        bounds = [1.0] + [ev["hours"] for ev in py["events"]] + [4320.0]
        for lo, hi in zip(bounds, bounds[1:]):         # one random duration inside each segment: same state as its start
            if hi / lo < 1 + 1e-4:
                continue
            h = lo * math.exp(math.log(hi / lo) * rnd.uniform(0.01, 0.99))
            if at(h) != at(lo * (1 + 1e-5) if lo > 1.0 else 1.0):
                ereal.append((c, round(h, 3), "change between events"))
    print(f"GATE {'PASS' if not ebad else 'FAIL'}  propagationEvents: {len(ecombos)} cases give the same events in JS "
          f"and Python ({n_ev} events)" + (f"  first mismatch {ebad[0]}" if ebad else ""))
    print(f"GATE {'PASS' if not ereal else 'FAIL'}  propagationEvents: every event changes the propagation and none is "
          f"missed between events" + (f"  first {ereal[0]}" if ereal else ""))
    bad = bad + ebad + ereal

    # recovers / stays toggle: shown only for off-chain causes; where hidden, the toggle changes nothing
    from frontend_contract import recovery_toggle
    keys = list(d["ui"]["injections"])
    with tempfile.TemporaryDirectory() as tmp:
        sf = os.path.join(tmp, "r.js")
        open(sf, "w").write("const M=require(process.argv[2]);const d=require(process.argv[3]);"
                            "console.log(JSON.stringify(Object.keys(d.ui.injections).map(k=>{const [n,f]=k.split(':');"
                            "return M.recoveryToggle(d,n,f);})));")
        jr = json.loads(subprocess.run(["node", sf, JS, dpath], check=True, capture_output=True, text=True).stdout)
    rbad = [k for k, j in zip(keys, jr) if recovery_toggle(d, *k.split(":")) != j]
    rhidden, rshown = [], []
    for k in keys:
        node, fail = k.split(":")
        changes = False
        for pk in dz["position_presets"]:
            for sev in (0.5, 3, 20):
                for h in (1, 6, 24, 720, 4320):
                    a = decide_at_duration(dz, pk, node, fail, sev, h, True, 0.04)
                    b = decide_at_duration(dz, pk, node, fail, sev, h, False, 0.04)
                    if a["verdict"] != b["verdict"] or not same(a["loss_if_stay_usd"], b["loss_if_stay_usd"]) or \
                            not same(a["total_if_act_usd"], b["total_if_act_usd"]):
                        changes = True
        show = recovery_toggle(d, node, fail)["show"]
        if not show and changes:
            rhidden.append(k)
        if show and not changes:
            rshown.append(k)
    shown = [k for k in keys if recovery_toggle(d, *k.split(":"))["show"]]
    print(f"GATE {'PASS' if not rbad else 'FAIL'}  recoveryToggle: {len(keys)} failures give the same answer in JS and "
          f"Python (shown for {', '.join(shown)})" + (f"  mismatch {rbad}" if rbad else ""))
    print(f"GATE {'PASS' if not (rhidden or rshown) else 'FAIL'}  recoveryToggle: hidden where recovers / stays changes "
          f"nothing, shown where it changes the loss (4 presets x 3 severities x 5 durations)"
          + (f"  hidden but changes: {rhidden}" if rhidden else "") + (f"  shown but no effect: {rshown}" if rshown else ""))
    bad = bad + rbad + rhidden + rshown

    # one duration mechanism (guide 5b): decideAt with the inputs decideAtDuration used equals decideAtDuration
    from frontend_contract import decide_at_duration
    dur_bad, n_dur = [], 0
    for sz in (1e6, 1e7):
        dz = at_size(d, sz)
        for pk, P in dz["position_presets"].items():
            for k in dz["ui"]["injections"]:
                for sev in (0.5, 2, 10):
                    for hours, rec in ((1, True), (24, True), (24, False), (720, False)):
                        n_dur += 1
                        node, fail = k.split(":")
                        r = decide_at_duration(dz, pk, node, fail, sev, hours, rec, 0.04)
                        o = {"hours": hours, "collateral_usd": r["position_value_usd"],
                             "collateral_oracle_usd": r["collateral_usd"], "debt_usd": r["debt_usd"],
                             "sale_value_usd": P["collateral_usd"]}
                        if rec:
                            o["permanent"] = 0
                        a = decide_at(dz, pk, node, fail, sev, r["carry"], o)
                        if any(a[f] != r[f] for f in ("verdict", "sell_fraction", "sale_cost_usd", "loss_if_stay_usd",
                                                      "loss_kept_usd")):
                            dur_bad.append((sz, pk, k, sev, hours, rec))
    print(f"GATE {'PASS' if not dur_bad else 'FAIL'}  one duration mechanism: decideAt with decideAtDuration's inputs "
          f"equals decideAtDuration in {n_dur - len(dur_bad)}/{n_dur} cases" + (f"  first {dur_bad[0]}" if dur_bad else ""))
    bad = bad + dur_bad

    # second view: vault decisions on the vault detail files (data/vaults)
    import glob
    from vault_pipeline import liquidity_run, vault_decide, vault_decide_at
    vcases, vfiles = [], sorted(glob.glob(os.path.join(HERE, "data", "vaults", "0x*.json")))
    for vf in vfiles:
        v = json.load(open(vf))
        for inc in v["incidents"]:
            if inc.get("analyzed", True) and inc.get("outcomes"):
                for amount in (1e4, 1e6, 5e7):
                    for pw in (None, 0.0, 0.01, 0.2):
                        for alt in (None, 0.0, 0.08):
                            vcases.append((vf, inc["key"], amount, pw, alt, None))
    vbad = 0
    if vcases:
        with tempfile.TemporaryDirectory() as tmp:
            cf, sf = os.path.join(tmp, "v.json"), os.path.join(tmp, "v.js")
            json.dump(vcases, open(cf, "w"))
            open(sf, "w").write("const M=require(process.argv[2]);const fs=require('fs');"
                                "const cs=JSON.parse(fs.readFileSync(process.argv[3]));const cache={};"
                                "console.log(JSON.stringify(cs.map(c=>{const v=cache[c[0]]||(cache[c[0]]=JSON.parse(fs.readFileSync(c[0])));"
                                "const inc=v.incidents.find(i=>i.key===c[1]);"
                                "return [M.vaultDecide(inc,v.exit,c[2],c[3],c[4],c[5]),M.vaultRun(v.exit,c[2],0.5,0.03)];})));")
            jv = json.loads(subprocess.run(["node", sf, JS, cf], check=True, capture_output=True, text=True).stdout)
        cache = {}
        vk = ("verdict", "expected_loss", "stay_loss_usd", "exit_usd", "exit_cost_usd", "locked_usd", "p_break_even")
        for c, (jd, jr) in zip(vcases, jv):
            v = cache.setdefault(c[0], json.load(open(c[0])))
            inc = next(i for i in v["incidents"] if i["key"] == c[1])
            pd = vault_decide(inc, v["exit"], c[2], c[3], c[4], c[5])
            pr = liquidity_run(v["exit"], c[2], 0.03, None)["rows"][1]
            if not all(same(pd[k], jd[k]) if not isinstance(pd[k], str) else pd[k] == jd[k] for k in vk) or \
                    not all(same(pr[k], jr[k]) for k in ("free_usd", "forced_usd", "locked_usd", "expected_loss_on_locked_usd")):
                vbad += 1
        print(f"GATE {'PASS' if not vbad else 'FAIL'}  vaultDecide / vaultRun: {len(vcases) - vbad}/{len(vcases)} cases "
              f"equal ({len(vfiles)} vault files)")
        # severity-based vault decision
        scases = [(vf, inc["key"], amount, sev, alt) for vf in vfiles for inc in json.load(open(vf))["incidents"]
                  if inc.get("severity_grid") for amount in (1e4, 1e6, 5e7) for sev in (None, 0.0, 0.004, 0.05, 0.2, 0.84, 1.0)
                  for alt in (None, 0.0)]
        with tempfile.TemporaryDirectory() as tmp:
            cf, sf = os.path.join(tmp, "s.json"), os.path.join(tmp, "s.js")
            json.dump(scases, open(cf, "w"))
            open(sf, "w").write("const M=require(process.argv[2]);const fs=require('fs');"
                                "const cs=JSON.parse(fs.readFileSync(process.argv[3]));const cache={};"
                                "console.log(JSON.stringify(cs.map(c=>{const v=cache[c[0]]||(cache[c[0]]=JSON.parse(fs.readFileSync(c[0])));"
                                "return M.vaultDecideAt(v.incidents.find(i=>i.key===c[1]),v.exit,c[2],c[3],c[4],null);})));")
            js_s = json.loads(subprocess.run(["node", sf, JS, cf], check=True, capture_output=True, text=True).stdout)
        sk = ("verdict", "L", "loss_if_stay_usd", "exit_usd", "exit_cost_usd", "locked_usd", "severity_break_even_free",
              "severity_break_even_forced")
        sbad = 0
        for c, j in zip(scases, js_s):
            v = cache.setdefault(c[0], json.load(open(c[0])))
            pd = vault_decide_at(next(i for i in v["incidents"] if i["key"] == c[1]), v["exit"], c[2], c[3], c[4], None)
            sbad += not all(pd[k] == j[k] if isinstance(pd[k], str) else same(pd[k], j[k]) for k in sk)
        print(f"GATE {'PASS' if not sbad else 'FAIL'}  vaultDecideAt: {len(scases) - sbad}/{len(scases)} cases equal")
        vbad += sbad
        from vault_pipeline import vault_sensitivity
        vs = [(vf, inc["key"], amount, sev) for vf in vfiles for inc in json.load(open(vf))["incidents"]
              if inc.get("severity_grid") for amount in (1e5, 1e7) for sev in (None, 0.05, 0.3)]
        with tempfile.TemporaryDirectory() as tmp:
            cf, sf = os.path.join(tmp, "vs.json"), os.path.join(tmp, "vs.js")
            json.dump(vs, open(cf, "w"))
            open(sf, "w").write("const M=require(process.argv[2]);const fs=require('fs');"
                                "const cs=JSON.parse(fs.readFileSync(process.argv[3]));const cache={};"
                                "console.log(JSON.stringify(cs.map(c=>{const v=cache[c[0]]||(cache[c[0]]=JSON.parse(fs.readFileSync(c[0])));"
                                "return M.vaultSensitivity(v.incidents.find(i=>i.key===c[1]),v.exit,c[2],c[3]);})));")
            jvs = json.loads(subprocess.run(["node", sf, JS, cf], check=True, capture_output=True, text=True).stdout)
        vsbad = 0
        for c, j in zip(vs, jvs):
            v = cache.setdefault(c[0], json.load(open(c[0])))
            py = vault_sensitivity(next(i for i in v["incidents"] if i["key"] == c[1]), v["exit"], c[2], c[3])
            vsbad += not (py["verdict"] == j["verdict"] and all(
                a["verdict"] == b["verdict"] and a["flips"] == b["flips"] and same(a["effect"], b["effect"])
                for a, b in zip(py["candidates"], j["candidates"])) and
                ((py["weakest"] is None and j["weakest"] is None) or
                 (py["weakest"] and j["weakest"] and py["weakest"]["alternative"] == j["weakest"]["alternative"])))
        print(f"GATE {'PASS' if not vsbad else 'FAIL'}  vaultSensitivity: {len(vs) - vsbad}/{len(vs)} cases equal")
        vbad += vsbad
        from vault_pipeline import vault_timeline
        vt = [(vf, inc["key"], amount, sev, rec) for vf in vfiles for inc in json.load(open(vf))["incidents"]
              if inc.get("duration_grids") for amount in (1e5, 1e7) for sev in (None, 0.3) for rec in (True, False)]
        with tempfile.TemporaryDirectory() as tmp:
            cf, sf = os.path.join(tmp, "vt.json"), os.path.join(tmp, "vt.js")
            json.dump(vt, open(cf, "w"))
            open(sf, "w").write("const M=require(process.argv[2]);const fs=require('fs');"
                                "const cs=JSON.parse(fs.readFileSync(process.argv[3]));const cache={};"
                                "console.log(JSON.stringify(cs.map(c=>{const v=cache[c[0]]||(cache[c[0]]=JSON.parse(fs.readFileSync(c[0])));"
                                "const inc=v.incidents.find(i=>i.key===c[1]);const t=M.vaultTimeline(inc,v.exit,c[2],c[3],c[4]);"
                                "return [t, M.vaultTimelineSummary(inc,t)];})));")
            jvt = json.loads(subprocess.run(["node", sf, JS, cf], check=True, capture_output=True, text=True).stdout)
        vtk = ("hours", "verdict", "L", "loss_if_stay_usd", "exit_usd", "exit_cost_usd", "locked_usd", "carry_cost")
        from vault_pipeline import vault_timeline_summary
        vtbad = 0
        for c, (j, jsm) in zip(vt, jvt):
            v = cache.setdefault(c[0], json.load(open(c[0])))
            inc = next(i for i in v["incidents"] if i["key"] == c[1])
            py = vault_timeline(inc, v["exit"], c[2], c[3], c[4])
            vtbad += not (len(py) == len(j) and all(a[k] == b[k] if isinstance(a[k], str) else same(a[k], b[k])
                                                    for a, b in zip(py, j) for k in vtk)
                          and vault_timeline_summary(inc, py) == jsm)
        print(f"GATE {'PASS' if not vtbad else 'FAIL'}  vaultTimeline: {len(vt) - vtbad}/{len(vt)} timelines equal")
        vbad += vtbad
    sys.exit(1 if fails or bad or vbad else 0)


if __name__ == "__main__":
    main()
