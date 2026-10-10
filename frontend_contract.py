"""
Fields of dashboard.json that the Risk Desk front end reads (dependency graph by layer, failure types,
position presets, detector feed). Used by export_dashboard.py; contract in README "Frontend integration".
"""
import csv
import json
import os

LAYERS = [(1, "Settlement chain"), (2, "Underlying yield source and its issuer"), (3, "Oracle pricing the asset"),
          (4, "PT market and its AMM curve"), (5, "Lending market holding it as collateral")]
LAYER_OF = {  # contract name (Etherscan) -> layer
    "PendleSUSDESY": 2, "StakedUSDeV2": 2, "USDe": 2, "EthenaMinting": 2, "USDeSilo": 2,
    "MetaOracleDeviationTimelock": 3, "MorphoChainlinkOracleV2": 3, "PendleSparkLinearDiscountOracle": 3,
    "EACAggregatorProxy": 3, "AccessControlledOCR2Aggregator": 3, "DummyFeed": 3,
    "PendlePrincipalToken": 4, "PendleYieldToken": 4, "PendleYieldContractFactoryUpg": 4, "PendleMarketV7": 4,
    "Morpho Blue market": 5, "Morpho": 5, "AdaptiveCurveIrm": 5, "FiatTokenV2_2": 5, "MasterMinter": 5,
}


def dependency_graph(edges_csv, nodes_json, position, lending):
    """Crawl output (crawl.py) arranged in the brief's five layers, plus the chain, the Pendle market (Pendle API)
    and the off-chain issuer (not verified). Returns None if the crawl files are missing."""
    if not (os.path.exists(edges_csv) and os.path.exists(nodes_json)):
        return None
    with open(edges_csv) as f:
        edges = list(csv.DictReader(f))
    with open(nodes_json) as f:
        meta = json.load(f)
    block = meta["block"]
    labels = {position["pt"]: f"PT-{position['name']} ({position['expiry']})", position["underlying"]: "sUSDe"}
    if lending:
        labels[next(iter([e["dst"] for e in edges if e["type"] == "marketParams.loanToken"]), "")] = lending["loan_asset"]
    nodes = {}
    for k, n in meta["nodes"].items():
        name = n.get("name")
        nodes[k] = {"id": k, "label": labels.get(k) or name or (k[:10] + "..."), "contract_name": name,
                    "address": n.get("address"), "kind": n.get("kind"), "layer": LAYER_OF.get(name),
                    "verified": n.get("verified"),
                    "evidence": {"grade": "A", "source": f"Etherscan verified source + eth_call @ block {block}"}
                    if name else {"grade": "A", "source": f"eth_getCode @ block {block} ({n.get('kind')})"}}
    # unlabelled nodes (role holders, operators, helpers) take the layer of the node that points to them
    for _ in range(4):
        for e in edges:
            if e["dst"] in nodes and nodes[e["dst"]]["layer"] is None and e["src"] in nodes:
                nodes[e["dst"]]["layer"] = nodes[e["src"]]["layer"]
    chain = f"chain:{position['chain_id']}"
    nodes[chain] = {"id": chain, "label": "Ethereum mainnet", "kind": "chain", "layer": 1, "address": None,
                    "evidence": {"grade": "A", "source": f"Pendle API chain_id = {position['chain_id']}; RPC block {block}"}}
    pm = f"pendle_market:{position['market']}"
    nodes[pm] = {"id": pm, "label": f"Pendle {position['name']} market", "kind": "amm_market", "layer": 4,
                 "address": position["market"], "contract_name": None,
                 "evidence": {"grade": "A", "source": "Pendle API markets list (fetch_data.py step1)"}}
    off = "offchain:ethena"
    nodes[off] = {"id": off, "label": "Ethena: issuer, exchanges, custodians", "kind": "offchain_issuer", "layer": 2,
                  "address": None, "evidence": {"grade": "D", "source": "not verified: off-chain, needs documents"}}
    out_edges = [{"from": e["src"], "to": e["dst"], "type": e["type"], "kind": e["kind"], "evidence": e["evidence"]}
                 for e in edges]
    usde = next((k for k, n in nodes.items() if n.get("contract_name") == "USDe"), None)
    out_edges += [{"from": pm, "to": position["pt"], "type": "liquidity", "kind": "data",
                   "evidence": "Pendle API market.pt, details.liquidity"}]
    if usde:
        out_edges.append({"from": off, "to": usde, "type": "backing", "kind": "data",
                          "evidence": "not verified (off-chain)"})
    by_layer = [{"n": n, "name": nm, "nodes": [k for k, v in nodes.items() if v["layer"] == n]} for n, nm in LAYERS]
    return {"block": block, "source": os.path.basename(edges_csv), "layers": by_layer, "nodes": nodes,
            "edges": out_edges,
            "counts": {k: sum(e["kind"] == k for e in out_edges) for k in ("data", "role", "operator", "infra")}}


def failure_types(cal, graph):
    """Failure types with the same keys as the front end's FAIL table; how the backend models each one, default
    severity with historical anchors, and default outcome probabilities with their evidence."""
    c = None
    if cal:
        pr, ml = cal["probabilities"], cal["median_loss_at_horizon"]
        c = {"outcomes": pr, "p_severe": pr["severe"], "partial_to_severe_prob": pr["partial"] / pr["severe"],
             "partial_severity_share": ml["partial"] / ml["severe"],
             "evidence": {"grade": "C", "source": f"{cal['n_episodes']} stablecoin depeg episodes, {cal['data_from']}.."
                                                  f"{cal['data_to']} (calibrate_depeg.py); severe {cal['range']['severe'][0]:.1%}"
                                                  f"-{cal['range']['severe'][1]:.1%} across samples"}}
    nd = lambda why: {"outcomes": None, "p_severe": None, "evidence": {"grade": "D", "source": why}}
    ft = {
        "shortfall": {"label": "Issuer cannot back the asset", "layer": 2, "unit": "%", "min": 1, "max": 100,
                      "default_severity": 50, "anchors": [{"value": 50, "source": "Stream xUSD, Nov 2025 (C)"},
                                                          {"value": 99.87, "source": "Elixir deUSD, Nov 2025 (C)"}],
                      "model": {"type": "loss_model", "scenario_layer": 2, "permanent": 1.0, "hours": None,
                                "oracle": "oracleFalls(oracle, 2, shock, hours)"},
                      "probabilities": dict(c, evidence={"grade": "C", "source": "by analogy: " + c["evidence"]["source"]})
                      if c else nd("no calibration file")},
        "depeg": {"label": "Loses value", "layer": 2, "unit": "%", "min": 1, "max": 100,
                  "default_severity": round(100 * cal["median_loss_at_horizon"]["severe"], 1) if cal else 10,
                  "anchors": [{"value": 1.62, "source": "USDe daily low, 1 Feb 2026, recovered next day (C)"},
                              {"value": round(100 * cal["median_loss_at_horizon"]["partial"], 1) if cal else None,
                               "source": "median day-30 loss of partial depegs (C)"},
                              {"value": round(100 * cal["median_loss_at_horizon"]["severe"], 1) if cal else None,
                               "source": "median day-30 loss of severe depegs (C)"}],
                  "model": {"type": "loss_model", "scenario_layer": 2, "permanent": 1.0, "hours": None,
                            "oracle": "oracleFalls(oracle, 2, shock, hours)"},
                  "probabilities": c or nd("no calibration file")},
        "navLoss": {"label": "NAV falls (USDe per sUSDe)", "layer": 2, "unit": "%", "min": 0.5, "max": 100,
                    "default_severity": 5, "anchors": [],
                    "model": {"type": "loss_model", "scenario_layer": 2, "permanent": 1.0, "hours": None,
                              "oracle": "false: no feed prices sUSDe's NAV"},
                    "probabilities": nd("no historical sUSDe NAV loss in our data")},
        "discount": {"label": "Trades below its NAV", "layer": 2, "unit": "%", "min": 0.5, "max": 30,
                     "default_severity": 3, "anchors": [],
                     "model": {"type": "loss_model", "scenario_layer": 2, "permanent": 0.0, "hours": None,
                               "oracle": "false: no feed prices sUSDe"},
                     "probabilities": nd("no sample")},
        "oracleLow": {"label": "Reports a price that is too low", "layer": 3, "unit": "%", "min": 1, "max": 40,
                      "default_severity": 2.77, "anchors": [{"value": 2.77, "source": "PT-reUSD oracle drop, 25 Aug "
                                                                                        "2026 (HackMD, back-tested 9/9)"}],
                      "model": {"type": "loss_model", "scenario_layer": 3, "permanent": 0.0, "hours": None,
                                "oracle": "true: the oracle itself reports the low price"},
                      "probabilities": {"outcomes": {"resolved": 0.5, "partial": 0.5, "severe": 0.0}, "p_severe": None,
                                        "evidence": {"grade": "D", "source": "one historical event only: placeholder"}}},
        "stale": {"label": "Stops updating", "layer": 3, "unit": "h", "min": 1, "max": 48, "default_severity": 6,
                  "anchors": [], "model": {"type": "not_modelled",
                                           "note": "liquidations use the last price; no direct loss modelled"},
                  "probabilities": nd("no sample")},
        "cascade": {"label": "Other borrowers are liquidated into the pool", "layer": 5, "unit": "%", "min": 1,
                    "max": 10, "default_severity": 1.0, "anchors": [],
                    "model": {"type": "exit_later", "source_field": "borrowers.exit_later",
                              "oracle": "oracleFalls(oracle, 3, shock, hours): false for this market, so the PT "
                                        "price fall alone liquidates nobody here",
                              "note": "severity = oracle drop of the liquidation curve (0.5%..10%)"},
                    "probabilities": nd("no sample")},
        "drain": {"label": "Liquidity leaves the pool", "layer": 4, "unit": "%", "min": 10, "max": 90,
                  "default_severity": 50, "anchors": [],
                  "model": {"type": "exit_only", "note": "share of pool liquidity removed is an assumption (D); "
                                                         "measured alternative: borrowers.exit_later"},
                  "probabilities": nd("no sample")},
        "halt": {"label": "Chain halts", "layer": 1, "unit": "h", "min": 1, "max": 48, "default_severity": 6,
                 "anchors": [], "model": {"type": "not_modelled", "note": "no exit and no liquidation while halted"},
                 "probabilities": nd("no sample")},
    }
    by_node = {}
    if graph:
        for k, n in graph["nodes"].items():
            L, kind, cn = n["layer"], n.get("kind"), n.get("contract_name")
            if L == 1:
                by_node[k] = ["halt"]
            elif kind == "offchain_issuer":
                by_node[k] = ["shortfall"]
            elif L == 2 and cn == "USDe":
                by_node[k] = ["depeg"]
            elif L == 2 and cn in ("StakedUSDeV2", "PendleSUSDESY"):
                by_node[k] = ["navLoss", "discount"]
            elif L == 3 and cn in ("MetaOracleDeviationTimelock", "MorphoChainlinkOracleV2", "EACAggregatorProxy",
                                   "PendleSparkLinearDiscountOracle"):
                by_node[k] = ["oracleLow", "stale"]
            elif kind == "amm_market":
                by_node[k] = ["drain"]
            elif cn == "PendlePrincipalToken":
                by_node[k] = ["depeg"]
            elif kind == "morpho_market":
                by_node[k] = ["cascade"]
    return {"types": ft, "by_node": by_node}


def position_presets(notional, lending, onc, oracle):
    """Positions the front end can switch between; oracle flags are per scenario: oracleFalls(oracle, ...)."""
    base = {"collateral_usd": notional, "lltv": lending["lltv"] if lending else None, "can_hold": True}
    out = {"spot": dict(base, label="PT held outright", debt_usd=0.0,
                        evidence={"grade": "D", "source": "position size assumed"})}
    if lending and lending.get("aggregate_ltv"):
        out["lev_market_avg"] = dict(base, label="PT as collateral, LTV of the Morpho market average",
                                     debt_usd=lending["aggregate_ltv"] * notional,
                                     evidence={"grade": "A", "source": "Morpho API aggregate LTV x assumed size"})
    if onc and onc.get("borrowers"):
        b = max((x for x in onc["borrowers"] if x["borrow_usdc"] > 0), key=lambda x: x["borrow_usdc"])
        out["lev_largest_borrower"] = dict(base, label=f"PT as collateral, LTV of the largest real borrower "
                                                       f"({b['address'][:10]}...)", debt_usd=b["ltv"] * notional,
                                           ltv=b["ltv"], lltv=onc["lltv"],
                                           evidence={"grade": "A", "source": f"eth_call @ block {onc['block']} x "
                                                                             f"assumed size"})
        c = max((x for x in onc["borrowers"] if x["borrow_usdc"] > 0), key=lambda x: x["ltv"])
        out["lev_closest_to_liquidation"] = dict(base, label=f"PT as collateral, LTV of the real borrower closest to "
                                                             f"liquidation ({c['address'][:10]}...)",
                                                 debt_usd=c["ltv"] * notional, ltv=c["ltv"], lltv=onc["lltv"],
                                                 evidence={"grade": "A", "source": f"eth_call @ block {onc['block']} "
                                                                                   f"x assumed size"})
    for v in out.values():
        v["oracle_rule"] = "set oracle_tracks_underlying / oracle_tracks_market per scenario with oracleFalls(oracle, " \
                           "layer, shock, hours)" if oracle else "oracle unknown: leave both null (both branches)"
    return out


# ------------------------------------------------------------------ the 9 nodes of the Risk Desk and fault injection
UI_LAYERS = {1: "Settlement chain", 2: "Yield source and its issuer", 3: "Oracle", 4: "PT and its market",
             5: "Lending market"}
# (node, fail) -> how the backend models it. oracle: "rule" = oracleFalls(oracle, layer, shock, hours) from the
# on-chain oracle tree; true / false = fixed by what the feeds price (see notes)
INJECTIONS = {
    "eth:halt": {"type": "not_modelled", "note": "no exit and no liquidation while the chain is halted"},
    "ethena:shortfall": {"type": "loss_model", "scenario_layer": 2, "permanent": 1.0, "hours": None, "oracle": "rule",
                         "note": "USDe loses backing; the oracle follows only after the meta-oracle switches to its "
                                 "USDe / USD backup (deviation above threshold for the challenge timelock)"},
    "usde:depeg": {"type": "loss_model", "scenario_layer": 2, "permanent": 1.0, "hours": None, "oracle": "rule",
                   "token": "USDe",
                   "note": "USDe falls against USD: the PT is denominated in USDe, so it falls by the same share; USDe / USD "
                           "is priced only by the backup oracle, which takes over after the meta-oracle switch"},
    "susde:navLoss": {"type": "loss_model", "scenario_layer": 2, "permanent": 1.0, "hours": None, "oracle": False,
                      "note": "sUSDe's NAV (USDe per sUSDe = totalAssets / totalSupply) falls: the SY exchange rate falls "
                              "with it and the PT index never decreases (max of rate and stored index), so PT holders "
                              "lose the same share for good (Pendle PendleERC4626SY / PendleYieldToken source). No feed "
                              "prices sUSDe's NAV, so nobody is liquidated and lenders' bad debt builds silently"},
    "susde:discount": {"type": "loss_model", "scenario_layer": 2, "permanent": 0.0, "hours": None, "oracle": False,
                       "note": "sUSDe trades below its NAV on markets while the NAV is unchanged: the PT still redeems at "
                               "the NAV-based rate, so holding to expiry recovers it; selling now would lock in the loss"},
    "feeds:oracleLow": {"type": "loss_model", "scenario_layer": 3, "permanent": 0.0, "hours": None, "oracle": True,
                        "note": "the feed reports the low price itself; the price recovers but liquidations stay"},
    "feeds:stale": {"type": "not_modelled", "note": "liquidations use the last price; the PT feed is computed every "
                                                    "block and cannot go stale, the USDe / USD feed can"},
    "oracle:oracleLow": {"type": "loss_model", "scenario_layer": 3, "permanent": 0.0, "hours": None, "oracle": True,
                         "note": "the oracle reports the low price itself; the price recovers but liquidations stay"},
    "oracle:stale": {"type": "not_modelled", "note": "liquidations use the last price until it updates"},
    "market:drain": {"type": "exit_only", "note": "pool liquidity removed is the severity (assumption): sellable "
                                                  "= max_exit_fraction x (1 - d), each sale costs what a sale 1/(1-d) "
                                                  "times larger costs today"},
    "pt:depeg": {"type": "loss_model", "scenario_layer": 3, "permanent": 0.0, "hours": None, "oracle": False,
                 "note": "the PT market price falls; the oracle prices the PT by a linear discount (no market input), "
                         "and the PT still redeems at expiry, so holding to expiry recovers it"},
    "lending:cascade": {"type": "exit_later", "note": "other borrowers are liquidated and their PT is sold into the "
                                                      "pool first; severity = oracle drop that liquidates them "
                                                      "(borrowers.exit_later). The PT market price alone does not "
                                                      "move this oracle"},
}


def ui_view(graph, oracle, position, lending, onc):
    """The Risk Desk's 9 nodes, 5 layer rows and 8 edges, filled from the crawl graph (addresses, evidence)."""
    if not graph:
        return None
    by_name = {}
    for k, n in graph["nodes"].items():
        by_name.setdefault(n.get("contract_name"), []).append(k)
    one = lambda name: (by_name.get(name) or [None])[0]
    g = graph["nodes"]
    ev = lambda k: g[k]["evidence"] if k in g else {"grade": "D", "source": "not found in the crawl"}
    feeds = [k for nm in ("PendleSparkLinearDiscountOracle", "EACAggregatorProxy", "DummyFeed",
                          "AccessControlledOCR2Aggregator") for k in by_name.get(nm, [])]
    n_tx = sum(1 for e in graph["edges"] if e["kind"] == "operator" and "Transmitters" in e["type"])
    o = oracle or {}
    ofact = (f"{o.get('contract_name')}: price from a {o['primary']['parts']['BASE_FEED_1']['kind'].replace('_', ' ')} "
             f"feed (no market input); switches to a backup with USDe / USD only after a deviation above "
             f"{o['deviation_threshold']:.2%} lasting {o['challenge_timelock_s'] / 3600:g} h "
             f"(deviation now {o['deviation_now']:.3%})") if o.get("kind") == "meta_oracle_timelock" else \
        (f"{o.get('contract_name')}: {o.get('rule')}" if o else "not classified")
    mm = next((k for k, n in g.items() if n.get("kind") == "morpho_market"), None)
    nodes = {
        "eth": {"label": "Ethereum mainnet", "kind": "Chain", "layer": 1, "members": ["chain:1"], "address": None},
        "ethena": {"label": "Ethena: issuer, exchanges, custodians", "kind": "Issuer", "layer": 2,
                   "members": ["offchain:ethena"] + by_name.get("EthenaMinting", []) + by_name.get("USDeSilo", []),
                   "address": one("EthenaMinting"),
                   "note": "minting and silo contracts read on chain; exchanges and custodians off-chain (not verified)"},
        "usde": {"label": "USDe", "kind": "Asset", "layer": 2, "members": by_name.get("USDe", []), "address": one("USDe")},
        "susde": {"label": "sUSDe", "kind": "Asset (PT redeems to this)", "layer": 2,
                  "members": by_name.get("StakedUSDeV2", []) + by_name.get("PendleSUSDESY", []),
                  "address": position["underlying"]},
        "feeds": {"label": "Upstream price feeds", "kind": "Oracle feeds", "layer": 3, "members": feeds,
                  "address": one("PendleSparkLinearDiscountOracle"),
                  "note": f"PT linear discount feed, Chainlink USDe / USD (reported by {n_tx} transmitters), constant "
                          f"quote feed"},
        "oracle": {"label": "Morpho market oracle", "kind": "Oracle", "layer": 3,
                   "members": by_name.get("MetaOracleDeviationTimelock", []) + by_name.get("MorphoChainlinkOracleV2", []),
                   "address": lending["oracle_address"].lower() if lending else None, "note": ofact},
        "market": {"label": f"Pendle PT-{position['name']} market", "kind": "AMM market", "layer": 4,
                   "members": [f"pendle_market:{position['market']}"], "address": position["market"]},
        "pt": {"label": f"PT-{position['name']} ({position['expiry']})", "kind": "Asset", "layer": 4,
               "members": by_name.get("PendlePrincipalToken", []) + by_name.get("PendleYieldToken", []),
               "address": position["pt"]},
        "lending": {"label": f"Morpho market PT-{position['name']} / {lending['loan_asset'] if lending else ''}",
                    "kind": "Lending market", "layer": 5, "members": ([mm] if mm else []) + by_name.get("Morpho", [])
                    + by_name.get("AdaptiveCurveIrm", []), "address": None,
                    "market_id": lending.get("market_id") if lending else None},
    }
    for k, n in nodes.items():
        first = next((m for m in n["members"] if m in g), None)
        n["contract_name"] = g[first].get("contract_name") if first else None
        n["evidence"] = ev(first) if first else {"grade": "D", "source": "not verified"}
        if k == "ethena":
            n["evidence"] = {"grade": "A", "source": "EthenaMinting / USDeSilo found by the crawler (on-chain part); "
                                                     "off-chain part D"}
        n["failures"] = [i.split(":")[1] for i in INJECTIONS if i.startswith(k + ":")]
    lay = [{"n": n, "name": nm, "nodes": [k for k, v in nodes.items() if v["layer"] == n]} for n, nm in UI_LAYERS.items()]
    e_of = lambda t: next((e["evidence"] for e in graph["edges"] if e["type"] == t), "not found in the crawl")
    edges = [
        {"from": "ethena", "to": "usde", "type": "backing", "grade": "D", "evidence": "off-chain backing: not verified"},
        {"from": "usde", "to": "susde", "type": "staking", "grade": "A", "evidence": e_of("asset")},
        {"from": "susde", "to": "pt", "type": "redemption", "grade": "A", "evidence": e_of("SY")},
        {"from": "market", "to": "pt", "type": "liquidity", "grade": "A", "evidence": "Pendle API market.pt, details.liquidity"},
        {"from": "feeds", "to": "oracle", "type": "price", "grade": "A", "evidence": e_of("BASE_FEED_1")},
        {"from": "oracle", "to": "lending", "type": "liquidation", "grade": "A", "evidence": e_of("marketParams.oracle")},
        {"from": "pt", "to": "lending", "type": "collateral", "grade": "A", "evidence": e_of("marketParams.collateralToken")},
        {"from": "lending", "to": "market", "type": "forced selling", "grade": "B",
         "evidence": "liquidators sell seized PT into the pool: borrowers.exit_later"},
        {"from": "pt", "to": "position", "type": "holding", "grade": "D",
         "evidence": "the position holds the PT; its size is assumed (position_presets)"},
        {"from": "lending", "to": "position", "type": "liquidation", "grade": "B",
         "evidence": "Morpho liquidation rule (source, back-tested 9/9); only for levered presets",
         "applies_to": [k for k in ("lev_market_avg", "lev_largest_borrower", "lev_closest_to_liquidation")]},
    ]
    return {"nodes": nodes, "layers": lay, "edges": edges, "injections": INJECTIONS}


def inject(d, preset_key, node, fail, sev, opts=None):
    """Reference implementation of RiskModel.inject (web/risk_model.js): loss and exit effect of failing `node` with
    `fail` at severity `sev` (in the failure's unit, % or h) for position preset `preset_key` of dashboard d.
    opts (sensitivity / timeline): {"hours": incident duration, "oracle_falls": forced oracle behaviour, "can_hold": bool,
    "permanent": share of the shock left after the incident, "collateral_usd" / "debt_usd": position at that time}."""
    opts = opts or {}
    from loss_model import Position, Scenario, position_loss
    from oracle_types import oracle_falls
    from decision_core import slippage_at
    m = INJECTIONS[f"{node}:{fail}"]
    p = d["position_presets"][preset_key]
    C, D_ = opts.get("collateral_usd", p["collateral_usd"]), opts.get("debt_usd", p["debt_usd"])
    can_hold = opts.get("can_hold", p["can_hold"])
    equity = C - D_
    curve = [(x["fraction"], x["loss"]) for x in d["exit_curve"]]
    cap = d["max_exit_fraction"]
    out = {"type": m["type"], "note": m["note"], "L_low": 0.0, "L_high": 0.0, "loss_usd": 0.0, "oracle_falls": None,
           "liquidated": None, "sellable_now": cap, "sellable_later": cap, "avg_cost_later": slippage_at(cap, curve)}

    def later(drop):
        rows = (d.get("borrowers") or {}).get("exit_later") or []
        if not rows:
            return
        r = min(rows, key=lambda r: abs(r["oracle_drop"] - drop))
        out.update(sellable_later=r["sellable_later"], avg_cost_later=r["avg_cost_later"], exit_row_drop=r["oracle_drop"])

    if m["type"] == "loss_model":
        shock = sev / 100
        hours = opts.get("hours", m["hours"])
        flag = (oracle_falls(d["oracle"], m["scenario_layer"], shock, hours, m.get("token"))
                if m["oracle"] == "rule" else m["oracle"])
        if "oracle_falls" in opts:
            flag = opts["oracle_falls"]
        s = Scenario("inject", m["scenario_layer"], shock, opts.get("permanent", m["permanent"]), hours, "", False)
        r = position_loss(s, Position("p", C, D_, p["lltv"] or 0.915, can_hold,
                                      flag if m["scenario_layer"] == 2 else None,
                                      flag if m["scenario_layer"] == 3 else None))
        out.update(L_low=r["L_low"], L_high=r["L_high"], loss_usd=r["L_high"] * equity, oracle_falls=flag,
                   liquidated=[b["liquidated"] for b in r["branches"]])
        if flag is True:
            later(shock)
    elif m["type"] == "exit_later":
        later(sev / 100)
    elif m["type"] == "exit_only":
        dd = sev / 100
        # the remaining capacity cap x (1 - d) costs what a sale of size cap costs today
        out.update(sellable_later=cap * (1 - dd), avg_cost_later=slippage_at(cap, curve))
    return out


# ------------------------------------------------------------------ decision without a probability
def decide_at(d, preset_key, node, fail, sev, carry=0.0, opts=None):
    """Given the incident has happened at severity `sev`: sell the share x of the position that minimises
    x * (slippage + carry) + (1 - x) * L(sev), never beyond the largest quote (decision_core.decide with p = 1).
    Costs per unit of equity: slippage and carry x collateral / equity. Mirrored by RiskModel.decideAt."""
    from decision_core import Scenario as DS, decide, slippage_at
    r = inject(d, preset_key, node, fail, sev, opts)
    p = d["position_presets"][preset_key]
    o = opts or {}
    C = o.get("collateral_usd", p["collateral_usd"])
    E = C - o.get("debt_usd", p["debt_usd"])
    scale = C / E
    raw = [(x["fraction"], x["loss"]) for x in d["exit_curve"]]
    L = r["L_high"]
    res = decide([DS("incident", 1.0, L)], [(x, s * scale) for x, s in raw], carry_lost=carry * scale)
    x = res["best_exit_fraction"]
    sale = x * ((slippage_at(x, raw) if x > 0 else 0.0) + carry) * C
    kept = (1 - x) * L * E
    verdict = ("STAY" if x <= 0 else "SELL_TO_CAP" if res["stuck_fraction"] > 0 else
               "EXIT" if x >= 1 - 1e-12 else "REDUCE")
    return dict(r, verdict=verdict, sell_fraction=x, sell_usd=x * C, sale_cost_usd=sale, loss_if_stay_usd=L * E,
                loss_kept_usd=kept, total_if_act_usd=sale + kept, avoided_usd=L * E - sale - kept,
                stuck_fraction=res["stuck_fraction"])


def break_even_severity(d, preset_key, node, fail, carry=0.0, lo=None, hi=None, steps=400):
    """Smallest severity (failure's unit) at which selling starts, and at which it reaches the cap or full exit:
    scan + bisection on decide_at. None = not within [lo, hi]. Mirrored by RiskModel.breakEvenSeverity."""
    ft = d["failure_types"]["types"][fail]
    lo = ft["min"] if lo is None else lo
    hi = ft["max"] if hi is None else hi
    if INJECTIONS[f"{node}:{fail}"]["type"] != "loss_model":
        return {"start": None, "cap": None, "lo": lo, "hi": hi}

    def first(pred):
        if pred(lo):
            return lo
        prev = lo
        for i in range(1, steps + 1):
            s = lo + (hi - lo) * i / steps
            if pred(s):
                a, b = prev, s
                for _ in range(40):
                    m = (a + b) / 2
                    a, b = (a, m) if pred(m) else (m, b)
                return b
            prev = s
        return None
    sells = lambda s: decide_at(d, preset_key, node, fail, s, carry)["sell_fraction"] > 0
    full = lambda s: decide_at(d, preset_key, node, fail, s, carry)["verdict"] in ("SELL_TO_CAP", "EXIT")
    return {"start": first(sells), "cap": first(full), "lo": lo, "hi": hi}


GRADE_RANK = "ABCD"


def sensitivity(d, preset_key, node, fail, sev, carry=0.0):
    """Which assumption flips the verdict, given the incident at severity sev (no probability). Each candidate
    replaces one assumption by its stated alternative and reruns decide_at. weakest = the lowest-graded candidate
    that flips the verdict (ties: larger change). Other position presets are shown as comparisons (the position is the
    user's choice, not an assumption about the world) and never chosen as weakest. Mirrored by RiskModel.sensitivity."""
    base = decide_at(d, preset_key, node, fail, sev, carry)
    m = INJECTIONS[f"{node}:{fail}"]
    p = d["position_presets"][preset_key]
    E = p["collateral_usd"] - p["debt_usd"]
    o = d.get("oracle") or {}
    cands = []
    if m["type"] == "loss_model":
        if m["oracle"] == "rule" and o.get("kind") == "meta_oracle_timelock" and o.get("challenge_timelock_s"):
            h = o["challenge_timelock_s"] / 3600 / 2
            cands.append(("duration", f"the incident lasts {h:g} h, less than the oracle's {2 * h:g} h challenge timelock",
                          "D", preset_key, carry, {"hours": h}))
        if p["debt_usd"] > 0:
            cands.append(("oracle", "the lending oracle " + ("does not follow" if base["oracle_falls"] else "follows")
                          + " the shock", (o.get("evidence") or {}).get("grade", "D"), preset_key, carry,
                          {"oracle_falls": not base["oracle_falls"]}))
        cands.append(("can_hold", "the position must sell at the worst point" if p["can_hold"]
                      else "the position can hold to expiry", "D", preset_key, carry, {"can_hold": not p["can_hold"]}))
    for k, q in d["position_presets"].items():
        if k != preset_key:
            cands.append(("position", q["label"], q["evidence"]["grade"], k, carry, None))
    cands.append(("carry", f"cash after selling earns 1% less a year than the PT (carry {carry + 0.01:.2%})", "D",
                  preset_key, carry + 0.01, None))
    rows = []
    for key, alt, grade, pk, c, op in cands:
        r = decide_at(d, pk, node, fail, sev, c, op)
        Ek = d["position_presets"][pk]["collateral_usd"] - d["position_presets"][pk]["debt_usd"]
        rows.append({"key": key, "alternative": alt, "grade": grade, "verdict": r["verdict"],
                     "comparison": key == "position",
                     "sell_fraction": r["sell_fraction"], "loss_if_stay_usd": r["loss_if_stay_usd"],
                     "flips": r["verdict"] != base["verdict"],
                     "effect": abs(r["sell_fraction"] - base["sell_fraction"])
                     + abs(r["loss_if_stay_usd"] / Ek - base["loss_if_stay_usd"] / E)})
    flips = [x for x in rows if x["flips"] and not x["comparison"]]
    weakest = None
    if flips:
        g = max(x["grade"] for x in flips)          # "D" > "C" > "B" > "A": lowest grade
        weakest = max((x for x in flips if x["grade"] == g), key=lambda x: x["effect"])
    return {"verdict": base["verdict"], "candidates": rows, "weakest": weakest}


# ------------------------------------------------------------------ timeline: how long the incident lasts
DURATIONS_H = [1, 6, 12, 16, 24, 48, 72, 168, 336, 720, 1440, 2160, 4320]   # 1 h .. 6 months


def time_model(d_position, oracle, onc, generated_at):
    """What changes with time: PT price (market: implied APY; oracle: linear discount), expiry, borrow rate."""
    import datetime as dt
    f = ((oracle or {}).get("primary") or {}).get("parts", {}).get("BASE_FEED_1") or {}
    mat = f.get("maturity")
    now = dt.datetime.fromisoformat(generated_at).timestamp()
    if mat is None:
        exp = dt.datetime.fromisoformat(d_position["expiry"] + "T00:00:00+00:00").timestamp()
    else:
        exp = mat
    return {"generated_at": generated_at, "expiry": d_position["expiry"], "days_to_expiry": (exp - now) / 86400,
            "implied_apy": d_position["implied_apy"], "oracle_discount_per_year": f.get("base_discount_per_year"),
            "borrow_apr": (onc or {}).get("borrow_apr"),
            "evidence": {"implied_apy": {"grade": "A", "source": "Pendle markets API"},
                         "oracle_discount_per_year": {"grade": "A", "source": "PendleSparkLinearDiscountOracle."
                                                      "baseDiscountPerYear (eth_call)"},
                         "borrow_apr": {"grade": "A", "source": "AdaptiveCurveIrm.borrowRateView at the positions block; "
                                                                "assumed constant over the incident (D)"}}}


def pt_prices(tm, days):
    """PT price `days` from now: market (constant implied APY) and oracle (linear discount); 1 after expiry."""
    left = max(0.0, tm["days_to_expiry"] - days)
    mk = 1 / (1 + tm["implied_apy"]) ** (left / 365) if tm["implied_apy"] is not None else None
    disc = tm["oracle_discount_per_year"]
    orc = 1 - left / 365 * disc if disc is not None else None
    return mk, orc


def decide_at_duration(d, preset_key, node, fail, sev, hours, recovers=True, alt_apy=None):
    """Decision now for an incident of severity sev lasting `hours`. recovers: the shock disappears after the
    incident (holders who can wait lose nothing, liquidations during it stay). PT valued at its price: the
    position's value, collateral (oracle price) and debt (borrow APR) are taken at the end of the incident.
    Yield given up by exiting = (implied APY - alt) over the incident, at most until expiry. Mirrored by
    RiskModel.decideAtDuration."""
    import math
    tm = d["time_model"]
    m = INJECTIONS[f"{node}:{fail}"]
    p = d["position_presets"][preset_key]
    days = hours / 24
    mk0, orc0 = pt_prices(tm, 0.0)
    mkT, orcT = pt_prices(tm, days)
    alt = tm["implied_apy"] if alt_apy is None else alt_apy
    carry = max(0.0, tm["implied_apy"] - alt) * min(days, max(0.0, tm["days_to_expiry"])) / 365
    C0, D0 = p["collateral_usd"], p["debt_usd"]
    C = C0 * (orcT / orc0 if orc0 and orcT else 1.0)
    D_ = D0 * math.exp((tm["borrow_apr"] or 0.0) * days / 365) if D0 > 0 else 0.0
    opts = {"hours": hours, "collateral_usd": C, "debt_usd": D_}
    if recovers and m["type"] == "loss_model":
        opts["permanent"] = 0.0
    r = decide_at(d, preset_key, node, fail, sev, carry, opts)
    r.update(hours=hours, days=days, recovers=recovers, past_expiry=days >= tm["days_to_expiry"], carry=carry,
             pt_price_market=mkT, pt_price_oracle=orcT, position_value_usd=C0 * (mkT / mk0 if mk0 and mkT else 1.0),
             collateral_usd=C, debt_usd=D_, ltv=D_ / C if C else None)
    return r


def timeline_pt(d, preset_key, node, fail, sev, recovers=True, alt_apy=None, durations=None):
    """decide_at_duration over a grid of incident durations (1 h .. 6 months, plus expiry)."""
    tm = d["time_model"]
    hs = sorted(set((durations or DURATIONS_H) + [round(tm["days_to_expiry"] * 24, 6)]))
    return [decide_at_duration(d, preset_key, node, fail, sev, h, recovers, alt_apy) for h in hs if h > 0]


def timeline_summary(d, preset_key, rows):
    """Does the duration change the verdict? Change points with their reason, or why the timeline is flat.
    Mirrored by RiskModel.timelineSummary."""
    levered = d["position_presets"][preset_key]["debt_usd"] > 0
    changes = []
    for a, b in zip(rows, rows[1:]):
        if a["verdict"] == b["verdict"]:
            continue
        why = []
        if b.get("oracle_falls") is True and a.get("oracle_falls") is not True:
            why.append("the meta-oracle switches (challenge timelock reached)")
        if b.get("past_expiry") and not a.get("past_expiry"):
            why.append("the PT reaches expiry")
        if any(b.get("liquidated") or []) and not any(a.get("liquidated") or []):
            why.append("the debt keeps growing after expiry until the LTV crosses the liquidation line"
                       if levered and a.get("past_expiry") else "the position is liquidated")
        if not why:
            why.append("the debt keeps growing after expiry" if levered and a.get("past_expiry") else
                       "the loss or the yield given up changes with the duration")
        changes.append({"from_hours": a["hours"], "to_hours": b["hours"], "verdict_before": a["verdict"],
                        "verdict_after": b["verdict"], "reason": "; ".join(why)})
    flat = None
    if not changes:
        flat = ("no debt: nothing in this position changes with time (no oracle timer, no interest), so the verdict "
                "depends only on the severity and on whether the loss recovers" if not levered else
                "the verdict is the same at every duration on the grid")
    return {"duration_matters": bool(changes), "changes": changes,
            "verdict": rows[0]["verdict"] if rows and not changes else None, "why_flat": flat}
