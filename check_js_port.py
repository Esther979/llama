#!/usr/bin/env python3
"""
Check that web/risk_model.js gives the same numbers as the Python backend (needs node).

  python3 check_js_port.py [--n 500]

Random cases (unlevered / levered, oracle true / false / unknown, shocks up to 100%, meta-oracle rules) for
positionLoss, oracleFalls, decide and breakEven, compared field by field. Prints GATE PASS / GATE FAIL.
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
             "oracle_tracks_market": flag if s["layer"] == 3 else rnd.choice([True, False, None])}
        out.append({"s": s, "p": p, "oracle": rnd.choice(ORACLES), "token": rnd.choice([None, "USDe", "sUSDe"]),
                    "prob": rnd.random() ** 3,
                    "L": rnd.random(), "carry": rnd.choice([0.0, 0.001, rnd.uniform(0, 0.01)]),
                    "scale": rnd.choice([1.0, rnd.uniform(1, 12)])})
    return out


def python_side(c):
    s, p = c["s"], c["p"]
    r = position_loss(Scenario("t", s["layer"], s["shock"], s["permanent"], s["hours"], "", False),
                      Position("t", p["collateral_usd"], p["debt_usd"], p["lltv"], p["can_hold"],
                               p["oracle_tracks_underlying"], p["oracle_tracks_market"]))
    d = decide([DScenario("e", c["prob"], c["L"])], CURVE, carry_lost=c["carry"])
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
  const r = M.positionLoss(c.s, c.p), d = M.decide(c.prob, c.L, curve, c.carry), b = M.breakEven(curve, c.L, c.scale, c.carry);
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
    dpath = os.path.join(HERE, "sample_data", "dashboard.sample.json")
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
    from frontend_contract import sensitivity
    scombos = [(pk, k.split(":")[0], k.split(":")[1], sev, 0.0) for pk in d["position_presets"]
               for k in d["ui"]["injections"] for sev in (0.5, 2, 10)]
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
    sys.exit(1 if fails or bad or vbad else 0)


if __name__ == "__main__":
    main()
