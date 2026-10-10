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
            elif L == 2 and cn in ("USDe", "StakedUSDeV2", "PendleSUSDESY"):
                by_node[k] = ["depeg"]
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
                   "note": "USDe / USD is priced only by the backup oracle: falls after the meta-oracle switch"},
    "susde:depeg": {"type": "loss_model", "scenario_layer": 2, "permanent": 1.0, "hours": None, "oracle": False,
                    "note": "no feed of this oracle prices sUSDe (linear discount x USDe / USD), so a sUSDe-only fall "
                            "liquidates nobody; holders still lose the value"},
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
    ]
    return {"nodes": nodes, "layers": lay, "edges": edges, "injections": INJECTIONS}


def inject(d, preset_key, node, fail, sev):
    """Reference implementation of RiskModel.inject (web/risk_model.js): loss and exit effect of failing `node` with
    `fail` at severity `sev` (in the failure's unit, % or h) for position preset `preset_key` of dashboard d."""
    from loss_model import Position, Scenario, position_loss
    from oracle_types import oracle_falls
    from decision_core import slippage_at
    m = INJECTIONS[f"{node}:{fail}"]
    p = d["position_presets"][preset_key]
    C, D_ = p["collateral_usd"], p["debt_usd"]
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
        flag = oracle_falls(d["oracle"], m["scenario_layer"], shock, m["hours"]) if m["oracle"] == "rule" else m["oracle"]
        s = Scenario("inject", m["scenario_layer"], shock, m["permanent"], m["hours"], "", False)
        r = position_loss(s, Position("p", C, D_, p["lltv"] or 0.915, p["can_hold"],
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
