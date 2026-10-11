"""
Fields of dashboard.json that the Risk Desk front end reads (dependency graph by layer, failure types,
position presets, detector feed). Used by export_dashboard.py; contract in README "Frontend integration".
"""
import csv
from collections import Counter
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


def dependency_graph(edges_csv, nodes_json, position, lending, offchain_blocks=None):
    """Crawl output (crawl.py) arranged in the brief's five layers, plus the chain, the Pendle market (Pendle API)
    and the off-chain dependencies of USDe / sUSDe (offchain_deps.json: issuer documents with quotes, grade D).
    Returns None if the crawl files are missing."""
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
    import offchain
    blocks = offchain_blocks or {}
    off = "offchain:ethena"
    ub = blocks.get("USDe")
    nodes[off] = {"id": off, "label": f"Ethena: {ub['issuer']}" if ub else "Ethena: issuer, exchanges, custodians",
                  "kind": "offchain_issuer", "layer": 2, "address": None,
                  "evidence": {"grade": "D", "source": (f"{ub['counts']['relations']} relations from the issuer's documents, "
                                                        f"each with its URL and quote (offchain_deps.json)") if ub else
                               "not verified: off-chain, needs documents"}}
    out_edges = [{"from": e["src"], "to": e["dst"], "type": e["type"], "kind": e["kind"], "evidence": e["evidence"]}
                 for e in edges]
    usde = next((k for k, n in nodes.items() if n.get("contract_name") == "USDe"), None)
    out_edges += [{"from": pm, "to": position["pt"], "type": "liquidity", "kind": "data",
                   "evidence": "Pendle API market.pt, details.liquidity"}]
    if usde:
        out_edges.append({"from": off, "to": usde, "type": "backing", "kind": "data",
                          "evidence": f"issuer documents: {ub['summary']}" if ub else "not verified (off-chain)"})
    for sym, parent, target in (("USDe", off, None), ("sUSDe", "offchain:susde", position["underlying"])):
        b = blocks.get(sym)
        if not b:
            continue
        if parent not in nodes:
            nodes[parent] = {"id": parent, "label": f"{sym}: {b['issuer']}", "kind": "offchain_operator", "layer": 2,
                             "address": None, "evidence": {"grade": "D", "source": f"{b['counts']['relations']} relations "
                                                           f"from the issuer's documents (offchain_deps.json)"}}
            out_edges.append({"from": parent, "to": target, "type": "operator", "kind": "offchain",
                              "evidence": f"issuer documents: {b['summary']}"})
        n_, e_ = offchain.graph_parts(b, parent, 2)
        nodes.update(n_)
        out_edges += e_
    by_layer = [{"n": n, "name": nm, "nodes": [k for k, v in nodes.items() if v["layer"] == n]} for n, nm in LAYERS]
    return {"block": block, "source": os.path.basename(edges_csv), "layers": by_layer, "nodes": nodes,
            "edges": out_edges,
            "counts": {k: sum(e["kind"] == k for e in out_edges) for k in ("data", "role", "operator", "infra", "offchain")}}


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
                    "max": 40, "default_severity": 1.0, "anchors": [],
                    "model": {"type": "exit_later", "source_field": "borrowers.exit_later",
                              "oracle": "oracleFalls(oracle, 3, shock, hours): false for this market, so the PT "
                                        "price fall alone liquidates nobody here",
                              "note": "severity = oracle drop of the liquidation curve (0.5%..40%)"},
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


def size_input(notional, pt_price, onc, usd_curve, sources):
    """The PT view's position size: the manager's input (default = the size of the main quotes). A position worth
    V today holds V / pt_price_usd PT; Morpho sees them at oracle_price_usd (liquidation check only)."""
    return {"default_usd": notional, "pt_price_usd": pt_price,
            "oracle_price_usd": (onc or {}).get("oracle_price"),
            "capacity_usd": usd_curve[-1][0], "smallest_quote_usd": usd_curve[0][0],
            "note": "sizes above capacity_usd cannot be sold through the pool now (larger quotes refused); below "
                    "smallest_quote_usd the smallest quote's cost is used",
            "evidence": {"default_usd": {"grade": "D", "source": "our assumption until the manager enters a size"},
                         "pt_price_usd": {"grade": "A", "source": "Pendle GET /v1/prices/assets at quote time"},
                         "oracle_price_usd": {"grade": "A", "source": f"lending oracle price() at block {onc['block']}"}
                         if onc else {"grade": "D", "source": "no oracle read: market price used"},
                         "capacity_usd": {"grade": "A", "source": sources}}}


def sized_preset(p, size_usd, si):
    """Preset p for a position worth size_usd today: PT units from the quoted PT price, collateral at the oracle
    price, debt = the preset's LTV (on the oracle value, as Morpho computes it) x that collateral."""
    units = size_usd / si["pt_price_usd"]
    co = units * (si["oracle_price_usd"] or si["pt_price_usd"])
    return dict(p, collateral_usd=size_usd, pt_units=units, collateral_oracle_usd=co, debt_usd=p["ltv"] * co)


def borrower_preset(d, address, label=None):
    """A real Morpho borrower of this market at its real size (d.borrowers.list): None if not found.
    Mirrored by RiskModel.borrowerPreset."""
    b = next((x for x in (d.get("borrowers") or {}).get("list") or [] if x["address"] == address.lower()), None)
    if not b:
        return None
    px = d["position"]["pt_price_usd"]
    return {"label": label or f"Morpho borrower {b['address'][:10]}... (real position)", "can_hold": True,
            "sized": False, "address": b["address"], "pt_units": b["collateral_pt"],
            "collateral_usd": b["collateral_pt"] * px, "collateral_oracle_usd": b["collateral_usdc"],
            "debt_usd": b["borrow_usdc"], "ltv": b["ltv"], "lltv": d["borrowers"]["lltv"],
            "evidence": {"grade": "A", "source": f"eth_call @ block {d['borrowers']['block']}: collateral (PT) and debt; "
                                                 f"value = PT units x Pendle PT price {px:.5f}"}}


def position_presets(notional, lending, onc, oracle, pt_price):
    """Positions the front end can switch between; oracle flags are per scenario: oracleFalls(oracle, ...).
    `sized` presets follow the size input (at_size); real borrowers keep their real size."""
    si = {"pt_price_usd": pt_price, "oracle_price_usd": (onc or {}).get("oracle_price")}
    base = {"lltv": onc["lltv"] if onc else lending["lltv"] if lending else None, "can_hold": True, "sized": True}
    out = {"spot": sized_preset(dict(base, label="PT held outright", ltv=0.0,
                                     evidence={"grade": "D", "source": "position size: the manager's input"}),
                                notional, si)}
    if onc and onc.get("borrowers"):
        bs = onc["borrowers"]
        ltv = sum(x["borrow_usdc"] for x in bs) / sum(x["collateral_usdc"] for x in bs)
        out["lev_market_avg"] = sized_preset(dict(base, label="PT as collateral, LTV of the Morpho market average",
                                                  ltv=ltv,
                                                  evidence={"grade": "A", "source": f"eth_call @ block {onc['block']}: "
                                                            f"total borrow / total collateral at the oracle price x the "
                                                            f"size input"}), notional, si)
    elif lending and lending.get("aggregate_ltv"):
        out["lev_market_avg"] = sized_preset(dict(base, label="PT as collateral, LTV of the Morpho market average",
                                                  ltv=lending["aggregate_ltv"],
                                                  evidence={"grade": "A", "source": "Morpho API aggregate LTV x the size "
                                                                                    "input"}), notional, si)
    if onc and onc.get("borrowers"):
        mini = {"position": {"pt_price_usd": pt_price},
                "borrowers": {"list": onc["borrowers"], "lltv": onc["lltv"], "block": onc["block"]}}
        b = max((x for x in onc["borrowers"] if x["borrow_usdc"] > 0), key=lambda x: x["borrow_usdc"])
        out["lev_largest_borrower"] = borrower_preset(mini, b["address"], f"Largest real borrower ({b['address'][:10]}..., "
                                                                         f"real position)")
        c = max((x for x in onc["borrowers"] if x["borrow_usdc"] > 0), key=lambda x: x["ltv"])
        out["lev_closest_to_liquidation"] = borrower_preset(mini, c["address"], f"Real borrower closest to liquidation "
                                                                                f"({c['address'][:10]}..., real position)")
    for v in out.values():
        v["oracle_rule"] = "set oracle_tracks_underlying / oracle_tracks_market per scenario with oracleFalls(oracle, " \
                           "layer, shock, hours)" if oracle else "oracle unknown: leave both null (both branches)"
    return out


# ------------------------------------------------------------------ position size (the manager's input)
def size_curve(d, value_usd):
    """Exit curve of a position worth value_usd today: [(fraction sold, cost)] from the quotes by USD size
    (exit_curve_usd), and the largest sellable fraction (1 when the whole position fits under the largest quote).
    Older dashboards without exit_curve_usd: exit_curve as is. Mirrored by RiskModel.sizeCurve."""
    from decision_core import slippage_at
    if not d.get("exit_curve_usd"):
        return [(x["fraction"], x["loss"]) for x in d["exit_curve"]], d["max_exit_fraction"]
    pts = [(x["usd"], x["loss"]) for x in d["exit_curve_usd"]]
    if value_usd <= pts[-1][0]:
        out = [(u / value_usd, s) for u, s in pts if u < value_usd] + [(1.0, slippage_at(value_usd, pts))]
    else:
        out = [(u / value_usd, s) for u, s in pts]
    return out, out[-1][0]


def _gas_at(d, usd):
    from decision_core import slippage_at
    g = [(x["usd"], x["gas_usd"]) for x in d.get("exit_curve_usd") or [] if x.get("gas_usd") is not None]
    return slippage_at(usd, g) if g else 0.0


def exit_later_at(d, value_usd, drop):
    """Exit now vs after liquidations, for a position worth value_usd: liquidators first sell the PT seized at oracle
    drop `drop` (nearest row of borrowers.liquidation_curve) into the pool; our sale starts where theirs stopped on the
    same quotes (pool not refilled). incidents.exit_later in USD instead of fractions of one notional; costs include
    gas. None without borrowers or exit_curve_usd. Mirrored by RiskModel.exitLaterAt."""
    from decision_core import slippage_at
    rows = (d.get("borrowers") or {}).get("liquidation_curve") or []
    if not rows or not d.get("exit_curve_usd"):
        return None
    r = min(rows, key=lambda r: abs(r["oracle_drop"] - drop))
    pts = [(x["usd"], x["loss"]) for x in d["exit_curve_usd"]]
    cap = pts[-1][0]
    cum = lambda u: u * slippage_at(u, pts) if u > 0 else 0.0
    y = r["pt_seized"] * d["position"]["pt_price_usd"]
    now = min(value_usd, cap)
    out = {"oracle_drop": r["oracle_drop"], "pt_seized": r["pt_seized"], "seized_usd": y,
           "seized_in_position_units": y / value_usd, "sellable_now": now / value_usd,
           "avg_cost_now": (cum(now) + _gas_at(d, now)) / now}
    if y >= cap:
        out.update(sellable_later=0.0, avg_cost_later=None, market_impact_of_liquidations=None,
                   note="liquidations alone use up the pool's quoted capacity")
        return out
    z = min(value_usd, cap - y)
    h = min(0.005 * value_usd, cap - y)
    out.update(sellable_later=z / value_usd, avg_cost_later=(cum(y + z) - cum(y) + _gas_at(d, z)) / z,
               market_impact_of_liquidations=(cum(y + h) - cum(y)) / h if y > 0 else 0.0, note=None)
    return out


def wallet_presets(d, address):
    """Presets for a wallet address, read on chain at the borrowers' block: "wallet" = PT held in the wallet
    (unlevered), "wallet_morpho" = its position in this Morpho market. Looked up in borrowers.wallets (read with
    onchain_positions.py --wallet: both parts) and else in borrowers.list (Morpho part only). Returns (read, presets):
    read = the address was read on chain. Mirrored by RiskModel.walletPresets."""
    b = d.get("borrowers") or {}
    a = address.lower()
    w = next((x for x in b.get("wallets") or [] if x["address"] == a), None)
    out = {}
    if w is None:
        m = borrower_preset(d, a)
        return (m is not None), ({"wallet_morpho": m} if m else {})
    px, opx = d["position"]["pt_price_usd"], b["oracle_price"]
    src = f"eth_call @ block {b['block']} (onchain_positions.py --wallet)"
    if w["pt_in_wallet"] > 0:
        out["wallet"] = {"label": f"Wallet {a[:10]}...: PT held (real position)", "can_hold": True, "sized": False,
                         "address": a, "pt_units": w["pt_in_wallet"], "collateral_usd": w["pt_in_wallet"] * px,
                         "collateral_oracle_usd": w["pt_in_wallet"] * opx, "debt_usd": 0.0, "ltv": 0.0,
                         "lltv": b["lltv"], "evidence": {"grade": "A", "source": f"PT balanceOf: {src}; value = PT units "
                                                                                 f"x Pendle PT price {px:.5f}"}}
    if w["collateral_pt"] > 0 or w["borrow_usdc"] > 0:
        out["wallet_morpho"] = dict(borrower_preset(d, a) or {
            "can_hold": True, "sized": False, "address": a, "pt_units": w["collateral_pt"],
            "collateral_usd": w["collateral_pt"] * px, "collateral_oracle_usd": w["collateral_usdc"],
            "debt_usd": w["borrow_usdc"], "ltv": w["ltv"], "lltv": b["lltv"],
            "evidence": {"grade": "A", "source": f"Morpho position: {src}; value = PT units x Pendle PT price {px:.5f}"}},
            label=f"Wallet {a[:10]}...: PT on Morpho (real position)")
    return True, out


def at_size(d, size_usd, wallet=None):
    """The dashboard for a position worth size_usd today (the manager's input): `sized` presets resized,
    exit_curve / max_exit_fraction / position.notional_usd for that size, borrowers.exit_later recomputed. wallet = an
    address read on chain (wallet_presets): adds presets "wallet" (PT held) and / or "wallet_morpho" (Morpho position)
    at their real size; wallet_read = the address was read on chain, wallet_found = it holds something.
    Legacy fields (scenarios, incidents, decision_grid...) stay at the export size. Mirrored by RiskModel.atSize."""
    si = d["size_input"]
    out = dict(d)
    out["position_presets"] = {k: sized_preset(p, size_usd, si) if p.get("sized") else p
                               for k, p in d["position_presets"].items()}
    if wallet:
        read, ws = wallet_presets(d, wallet)
        out["wallet_read"], out["wallet_found"] = read, bool(ws)
        out["position_presets"].update(ws)
    curve, cap = size_curve(d, size_usd)
    out["exit_curve"] = [{"fraction": x, "usd": x * size_usd, "loss": s, "gas_usd": _gas_at(d, x * size_usd)}
                         for x, s in curve]
    out["max_exit_fraction"] = cap
    out["position"] = dict(d["position"], notional_usd=size_usd)
    if (d.get("borrowers") or {}).get("liquidation_curve") and d.get("exit_curve_usd"):
        out["borrowers"] = dict(d["borrowers"], exit_later=[exit_later_at(d, size_usd, r["oracle_drop"])
                                                            for r in d["borrowers"]["liquidation_curve"]])
    out["size_usd"] = size_usd
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
                   "members": ["offchain:ethena"] + [k for k in g if k.startswith("offchain:ethena:")]
                   + by_name.get("EthenaMinting", []) + by_name.get("USDeSilo", []),
                   "address": one("EthenaMinting"),
                   "note": ("minting and silo contracts read on chain; off-chain: " + ", ".join(
                       f"{n} {k}" for k, n in sorted(Counter(g[m]['role'] for m in g
                                                             if m.startswith('offchain:ethena:')).items()))
                            + " from Ethena's documents with sources (offchain.USDe)")
                   if any(k.startswith("offchain:ethena:") for k in g)
                   else "minting and silo contracts read on chain; exchanges and custodians off-chain (not verified)"},
        "usde": {"label": "USDe", "kind": "Asset", "layer": 2, "members": by_name.get("USDe", []), "address": one("USDe")},
        "susde": {"label": "sUSDe", "kind": "Asset (PT redeems to this)", "layer": 2,
                  "members": by_name.get("StakedUSDeV2", []) + by_name.get("PendleSUSDESY", [])
                  + [k for k in g if k == "offchain:susde" or k.startswith("offchain:susde:")],
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
        {"from": "ethena", "to": "usde", "type": "backing", "grade": "D",
         "evidence": next((e["evidence"] for e in graph["edges"] if e["from"] == "offchain:ethena" and e["type"] == "backing"),
                          "off-chain backing: not verified")},
        {"from": "usde", "to": "susde", "type": "staking", "grade": "A", "evidence": e_of("asset")},
        {"from": "susde", "to": "pt", "type": "redemption", "grade": "A", "evidence": e_of("SY")},
        {"from": "market", "to": "pt", "type": "liquidity", "grade": "A", "evidence": "Pendle API market.pt, details.liquidity"},
        {"from": "feeds", "to": "oracle", "type": "price", "grade": "A", "evidence": e_of("BASE_FEED_1")},
        {"from": "oracle", "to": "lending", "type": "liquidation", "grade": "A", "evidence": e_of("marketParams.oracle")},
        {"from": "pt", "to": "lending", "type": "collateral", "grade": "A", "evidence": e_of("marketParams.collateralToken")},
        {"from": "lending", "to": "market", "type": "forced selling", "grade": "B",
         "evidence": "liquidators sell seized PT into the pool: borrowers.exit_later"},
        {"from": "pt", "to": "position", "type": "holding", "grade": "D",
         "evidence": "the position holds the PT; its size is the manager's input (size_input, at_size) or a real "
                     "borrower's on-chain position (position_presets)"},
        {"from": "lending", "to": "position", "type": "liquidation", "grade": "B",
         "evidence": "Morpho liquidation rule (source, back-tested 9/9); only for levered presets",
         "applies_to": [k for k in ("lev_market_avg", "lev_largest_borrower", "lev_closest_to_liquidation")]},
    ]
    return {"nodes": nodes, "layers": lay, "edges": edges, "injections": INJECTIONS}


def inject(d, preset_key, node, fail, sev, opts=None):
    """Reference implementation of RiskModel.inject (web/risk_model.js): loss and exit effect of failing `node` with
    `fail` at severity `sev` (in the failure's unit, % or h) for position preset `preset_key` of dashboard d.
    opts (sensitivity / timeline): {"hours": incident duration, "oracle_falls": forced oracle behaviour, "can_hold": bool,
    "permanent": share of the shock left after the incident, "collateral_usd" (market value) / "collateral_oracle_usd"
    (value at the lending oracle's price, liquidation check only) / "debt_usd": position at that time,
    "sale_value_usd": value of the position today, what a sale now is sized on (default: the preset's collateral_usd)}."""
    opts = opts or {}
    from loss_model import Position, Scenario, position_loss
    from oracle_types import oracle_falls
    from decision_core import slippage_at
    m = INJECTIONS[f"{node}:{fail}"]
    p = d["position_presets"][preset_key]
    C, D_ = opts.get("collateral_usd", p["collateral_usd"]), opts.get("debt_usd", p["debt_usd"])
    Co = opts.get("collateral_oracle_usd", C * p.get("collateral_oracle_usd", p["collateral_usd"]) / p["collateral_usd"])
    V = opts.get("sale_value_usd", p["collateral_usd"])
    can_hold = opts.get("can_hold", p["can_hold"])
    equity = C - D_
    curve, cap = size_curve(d, V)
    out = {"type": m["type"], "note": m["note"], "L_low": 0.0, "L_high": 0.0, "loss_usd": 0.0, "oracle_falls": None,
           "liquidated": None, "sellable_now": cap, "sellable_later": cap, "avg_cost_later": slippage_at(cap, curve)}

    def later(drop):
        r = exit_later_at(d, V, drop)
        if r is None:
            rows = (d.get("borrowers") or {}).get("exit_later") or []      # older dashboards
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
                                      flag if m["scenario_layer"] == 3 else None, Co))
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
    The sale happens now, so it is sized and costed on today's value V (exit curve of a position worth V); the loss
    is on the equity E at the end of the incident. Costs per unit of equity: (slippage + carry) x V / E.
    Mirrored by RiskModel.decideAt."""
    from decision_core import Scenario as DS, decide, slippage_at
    r = inject(d, preset_key, node, fail, sev, opts)
    p = d["position_presets"][preset_key]
    o = opts or {}
    C = o.get("collateral_usd", p["collateral_usd"])
    E = C - o.get("debt_usd", p["debt_usd"])
    V = o.get("sale_value_usd", p["collateral_usd"])
    scale = V / E
    raw, _ = size_curve(d, V)
    L = r["L_high"]
    res = decide([DS("incident", 1.0, L)], [(x, s * scale) for x, s in raw], carry_lost=carry * scale)
    x = res["best_exit_fraction"]
    sale = x * ((slippage_at(x, raw) if x > 0 else 0.0) + carry) * V
    kept = (1 - x) * L * E
    verdict = ("STAY" if x <= 0 else "SELL_TO_CAP" if res["stuck_fraction"] > 0 else
               "EXIT" if x >= 1 - 1e-12 else "REDUCE")
    return dict(r, verdict=verdict, sell_fraction=x, sell_usd=x * V, sale_cost_usd=sale, loss_if_stay_usd=L * E,
                loss_kept_usd=kept, total_if_act_usd=sale + kept, avoided_usd=L * E - sale - kept,
                stuck_fraction=res["stuck_fraction"])


def break_even_severity(d, preset_key, node, fail, carry=0.0, lo=None, hi=None, steps=400, opts=None):
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
    sells = lambda s: decide_at(d, preset_key, node, fail, s, carry, opts)["sell_fraction"] > 0
    full = lambda s: decide_at(d, preset_key, node, fail, s, carry, opts)["verdict"] in ("SELL_TO_CAP", "EXIT")
    return {"start": first(sells), "cap": first(full), "lo": lo, "hi": hi}


GRADE_RANK = "ABCD"


def sensitivity(d, preset_key, node, fail, sev, carry=0.0, opts=None):
    """Which assumption flips the verdict, given the incident at severity sev (no probability). Each candidate
    replaces one assumption by its stated alternative and reruns decide_at. weakest = the lowest-graded candidate
    that flips the verdict (ties: larger change). Other position presets are shown as comparisons (the position is the
    user's choice, not an assumption about the world) and never chosen as weakest. opts (e.g. a past incident's
    duration and recovery) apply to the base case and to every candidate. Mirrored by RiskModel.sensitivity."""
    opts = opts or {}
    base = decide_at(d, preset_key, node, fail, sev, carry, opts)
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
    c1 = carry + 0.01 * max(0.0, d["time_model"]["days_to_expiry"]) / 365     # 1% a year, until expiry
    cands.append(("carry", f"cash after selling earns 1% a year less than assumed (carry {c1:.3%} until expiry)", "D",
                  preset_key, c1, None))
    rows = []
    for key, alt, grade, pk, c, op in cands:
        r = decide_at(d, pk, node, fail, sev, c, dict(opts, **(op or {})))
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


def carry_of(d, alt_apy=None, days=None):
    """Yield given up by selling now, as a fraction of the value sold: (PT implied APY - what cash earns) over `days`,
    at most until expiry (days None = until expiry). alt_apy = the manager's "cash earns after selling" (annual, e.g.
    0.04); None = the PT's implied APY (nothing given up). This, not the annual difference, is the `carry` that
    decide_at / break_even_severity / sensitivity take. Mirrored by RiskModel.carryOf."""
    tm = d["time_model"]
    alt = tm["implied_apy"] if alt_apy is None else alt_apy
    left = max(0.0, tm["days_to_expiry"])
    return max(0.0, tm["implied_apy"] - alt) * (left if days is None else min(days, left)) / 365


def pt_prices(tm, days):
    """PT price `days` from now: market (constant implied APY) and oracle (linear discount); 1 after expiry."""
    left = max(0.0, tm["days_to_expiry"] - days)
    mk = 1 / (1 + tm["implied_apy"]) ** (left / 365) if tm["implied_apy"] is not None else None
    disc = tm["oracle_discount_per_year"]
    orc = 1 - left / 365 * disc if disc is not None else None
    return mk, orc


def decide_at_duration(d, preset_key, node, fail, sev, hours, recovers=True, alt_apy=None):
    """Decision now for an incident of severity sev lasting `hours`. recovers: the shock disappears after the
    incident (holders who can wait lose nothing, liquidations during it stay). PT valued at its price: at the end of
    the incident the position is worth PT units x market price (implied APY; the loss is on this value), Morpho
    sees PT units x oracle price (linear discount; liquidation check only) and the debt has grown at the borrow APR.
    A sale now is costed on today's value. Yield given up by exiting = (implied APY - alt) over the incident, at most
    until expiry. Mirrored by RiskModel.decideAtDuration."""
    import math
    tm = d["time_model"]
    m = INJECTIONS[f"{node}:{fail}"]
    p = d["position_presets"][preset_key]
    days = hours / 24
    mk0, orc0 = pt_prices(tm, 0.0)
    mkT, orcT = pt_prices(tm, days)
    carry = carry_of(d, alt_apy, days)
    V0, D0 = p["collateral_usd"], p["debt_usd"]
    Co0 = p.get("collateral_oracle_usd", V0)
    VT = V0 * (mkT / mk0 if mk0 and mkT else 1.0)
    C = Co0 * (orcT / orc0 if orc0 and orcT else 1.0)
    D_ = D0 * math.exp((tm["borrow_apr"] or 0.0) * days / 365) if D0 > 0 else 0.0
    opts = {"hours": hours, "collateral_usd": VT, "collateral_oracle_usd": C, "debt_usd": D_, "sale_value_usd": V0}
    if recovers and m["type"] == "loss_model":
        opts["permanent"] = 0.0
    r = decide_at(d, preset_key, node, fail, sev, carry, opts)
    r.update(hours=hours, days=days, recovers=recovers, past_expiry=days >= tm["days_to_expiry"], carry=carry,
             pt_price_market=mkT, pt_price_oracle=orcT, position_value_usd=VT,
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


# ------------------------------------------------------------------ past incidents (replays of real events)
def past_incidents(cal=None):
    """Real past incidents as ready-made inputs for the PT view: node, failure, severity (failure's unit) and the opts
    to pass to decideAt / breakEvenSeverity / sensitivity / decisionText (duration and whether the shock is gone
    after it). Severities are the failure_types anchors (grade C: observed on this asset or by analogy). Statistics
    (median depeg losses) are not events and are not listed."""
    from loss_model import PRESETS
    pr = {s.key: s for s in PRESETS}
    u, o, h, t = pr["usde_mild"], pr["oracle_dip"], pr["issuer_half"], pr["issuer_total"]
    ev = lambda src, basis: {"grade": "C", "source": src, "basis": basis}
    return [
        {"key": "usde_feb_2026", "label": "USDe daily low, 1 Feb 2026 (recovered the next day)", "date": "2026-02-01",
         "node": "usde", "fail": "depeg", "sev": round(100 * u.shock, 2), "hours": u.hours, "recovers": True,
         "opts": {"hours": u.hours, "permanent": 0.0},
         "evidence": ev(f"{u.source}; recovery: {u.recovery_source}", "this asset's own history")},
        {"key": "pt_reusd_aug_2026", "label": "PT-reUSD oracle drop, 25 Aug 2026 (back-tested 9/9)",
         "date": "2026-08-25", "node": "oracle", "fail": "oracleLow", "sev": 2.77, "hours": o.hours, "recovers": True,
         "opts": {"hours": o.hours, "permanent": 0.0},
         "evidence": ev("PT-reUSD oracle drop, 25 Aug 2026 (HackMD, back-tested by backtest_reusd.py); market: "
                        + o.source, "another PT's oracle, by analogy")},
        {"key": "stream_xusd_nov_2025", "label": "Stream xUSD issuer failure, Nov 2025", "date": "2025-11",
         "node": "ethena", "fail": "shortfall", "sev": round(100 * h.shock, 2), "hours": None, "recovers": False,
         "opts": {}, "evidence": ev(h.source, "another stablecoin issuer, by analogy")},
        {"key": "elixir_deusd_nov_2025", "label": "Elixir deUSD collapse, Nov 2025", "date": "2025-11",
         "node": "ethena", "fail": "shortfall", "sev": round(100 * t.shock, 2), "hours": None, "recovers": False,
         "opts": {}, "evidence": ev(t.source, "another stablecoin issuer, by analogy")},
    ]


# ------------------------------------------------------------------ reasons a manager can act on (PT view)
def _round_int(v, d):
    """round(|v| x 10^d) half away from zero, as an integer (same arithmetic as RiskModel's _roundInt)."""
    import math
    a = math.floor(abs(v) * 10 ** d + 0.5)
    return -a if v < 0 else a


def _num(v, d=2):
    """v with at most d decimals (trailing zeros dropped) and thousands commas; identical in RiskModel._num."""
    n = _round_int(v, d)
    sign, n = ("-" if n < 0 else ""), abs(n)
    ip, fp = divmod(n, 10 ** d)
    out = f"{ip:,}"
    frac = str(fp).rjust(d, "0").rstrip("0") if d else ""
    return sign + out + ("." + frac if frac else "")


def decision_text(d, preset_key, node, fail, sev, carry=0.0, opts=None):
    """The PT view's reasons, built only from the model's results: verdict, a title, the headline sentence (loss if
    staying vs selling now), the propagation reasons (oracle, liquidation, recovery, exit), the break-even severity
    and the assumption the answer hinges on. `numbers` lists every number written; `unchecked` = numbers in the text
    that are not among them (must be empty). `rule` is the injection's fixed note (data, not checked). opts as in
    decide_at, e.g. a past incident's {"hours", "permanent"} (past_incidents[].opts). Mirrored by RiskModel.decisionText."""
    opts = opts or {}
    from loss_model import lif
    from reasoning import NUM
    r = decide_at(d, preset_key, node, fail, sev, carry, opts)
    be = break_even_severity(d, preset_key, node, fail, carry, opts=opts)
    sv = sensitivity(d, preset_key, node, fail, sev, carry, opts)
    m = d["ui"]["injections"][f"{node}:{fail}"]
    p = d["position_presets"][preset_key]
    ft = d["failure_types"]["types"][fail]
    o = d.get("oracle") or {}
    nl, fl = d["ui"]["nodes"][node]["label"], ft["label"]
    nums = []

    def f(s):
        nums.extend(NUM.findall(s))
        return s
    money = lambda v: f("$" + _num(v, 0))
    pct = lambda v: f(_num(v * 100, 2) + "%")
    unit = lambda v: f(_num(v, 2) + ("%" if ft["unit"] == "%" else " h"))
    D, C = p["debt_usd"], p["collateral_usd"]
    Co = p.get("collateral_oracle_usd", C)
    title = f"{fl} ({nl}), severity {unit(sev)}"
    reasons = []
    if m["type"] == "loss_model":
        loss = r["loss_if_stay_usd"]
        if loss <= 0:
            head = "STAY: doing nothing loses nothing at this severity, so there is nothing to sell for."
        elif r["verdict"] == "STAY":
            head = f"STAY: doing nothing loses {money(loss)}; selling would cost more than it saves."
        else:
            head = (f"{r['verdict']}: doing nothing loses {money(loss)}. Selling {money(r['sell_usd'])} now "
                    f"({pct(r['sell_fraction'])} of the position) costs {money(r['sale_cost_usd'])}"
                    + (f" and leaves {money(r['loss_kept_usd'])} at risk on the rest." if r["loss_kept_usd"] > 0 else ".")
                    + (f" {pct(r['stuck_fraction'])} of the position cannot be sold through the pool now."
                       if r["stuck_fraction"] > 0 else ""))
        of, meta = r["oracle_falls"], o.get("kind") == "meta_oracle_timelock" and m["oracle"] == "rule"
        if of is True:
            reasons.append(f"The lending oracle follows it: the deviation is above the meta-oracle's "
                           f"{pct(o['deviation_threshold'])} threshold for at least "
                           f"{f(_num(o['challenge_timelock_s'] / 3600, 2))} h, so it switches to its backup feed."
                           if meta else "The lending oracle reports the low price itself.")
        elif of is False:
            reasons.append(f"The lending oracle does not follow it: the meta-oracle switches only after a deviation "
                           f"above {pct(o['deviation_threshold'])} lasting "
                           f"{f(_num(o['challenge_timelock_s'] / 3600, 2))} h." if meta else
                           "The lending oracle does not follow it: no feed of the oracle prices this.")
        else:
            reasons.append(f"The oracle's behaviour is unknown: the loss is the worse of both branches "
                           f"({pct(r['L_low'])} to {pct(r['L_high'])} of equity).")
        if D <= 0:
            reasons[-1] += " This matters only for a levered position: this one has no debt."
        if D > 0:
            thr = 1 - D / (Co * p["lltv"])
            if any(r["liquidated"] or []):
                reasons.append(f"The position is liquidated: the oracle falls {unit(sev)} while the liquidation line is "
                               f"{pct(thr)} away; Morpho seizes collateral worth the debt plus a "
                               f"{pct(lif(p['lltv']) - 1)} bonus.")
            elif thr > 0:
                reasons.append(f"Not liquidated: the oracle would have to fall {pct(thr)} before this position can be "
                               f"liquidated.")
            else:
                reasons.append("The position is already above the liquidation line.")
        perm = opts.get("permanent", m["permanent"])
        if m["permanent"] == 0 and p["can_hold"]:
            reasons.append("The price recovers (the PT redeems at expiry), so a holder who can wait loses nothing on "
                           "the value" + ("; liquidations during the incident stay." if D > 0 else "."))
        elif perm == 0 and p["can_hold"]:
            reasons.append("The shock is over after the incident" + (f" ({f(_num(opts['hours'], 2))} h)"
                                                                     if opts.get("hours") is not None else "")
                           + ", so a holder who can wait loses nothing on the value"
                           + ("; liquidations during the incident stay." if D > 0 else "."))
        elif perm == 1:
            reasons.append("The loss is permanent: no recovery is assumed.")
    elif m["type"] in ("exit_later", "exit_only"):
        head = ("STAY: no direct loss on this position; " + (
            f"the part that can be sold falls from {pct(r['sellable_now'])} to {pct(r['sellable_later'])}."
            if r["sellable_later"] < r["sellable_now"] - 1e-12 else
            f"{pct(r['sellable_now'])} of the position can still be sold."))
    else:
        head = "STAY: no direct loss is modelled for this failure."
    later = r["sellable_later"] < r["sellable_now"] - 1e-12 and m["type"] != "not_modelled"
    reasons.append(f"Today the pool takes {pct(r['sellable_now'])} of this position "
                   f"({money(r['sellable_now'] * C)})"
                   + (("; after the failure nothing can be sold." if r["sellable_later"] <= 0 else
                       f"; after the failure only {pct(r['sellable_later'])}.") if later else "."))
    if m["type"] != "loss_model":
        brk = "No break-even severity: this failure causes no direct loss."
    elif be["start"] is None:
        brk = f"Selling does not pay at any severity from {unit(be['lo'])} to {unit(be['hi'])}."
    elif be["start"] <= be["lo"]:
        brk = (f"Selling pays from the lowest severity tested ({unit(be['lo'])})"
               + ("." if be["cap"] is None else " up to all the pool takes." if be["cap"] <= be["lo"]
                  else f"; it sells all the pool takes above {unit(be['cap'])}."))
    else:
        brk = (f"Selling starts to pay above {unit(be['start'])}"
               + (f" and sells all the pool takes above {unit(be['cap'])}." if be["cap"] is not None else "."))
    w = sv["weakest"]
    if w:
        f(w["alternative"])
        hinge = f"The answer hinges on: {w['alternative']} (grade {w['grade']}): the verdict would be {w['verdict']}."
    else:
        hinge = "No tested assumption changes the answer."
    text = " ".join([title, head] + reasons + [brk, hinge]).replace(nl, "").replace(fl, "")
    bad = [x for x in NUM.findall(text) if x not in nums]
    return {"verdict": r["verdict"], "title": title, "headline": head, "rule": m["note"], "reasons": reasons,
            "break_even": brk, "hinges_on": hinge, "numbers": nums, "unchecked": bad}


# ------------------------------------------------------------------ how an incident travels through the five layers
# what the origin node does, per injection ({sev} = the severity in the failure's unit); same strings in RiskModel
PROPAGATION_ORIGIN = {
    "eth:halt": "Ethereum stops producing blocks for {sev}: no exit and no liquidation while it lasts.",
    "ethena:shortfall": "Ethena cannot fully back USDe (off-chain reserves, custodians and hedges): USDe falls {sev}.",
    "usde:depeg": "USDe falls {sev} against USD.",
    "susde:navLoss": "sUSDe's NAV (USDe per sUSDe) falls {sev}.",
    "susde:discount": "sUSDe trades {sev} below its NAV; the NAV itself is unchanged.",
    "feeds:oracleLow": "An upstream feed of the lending oracle reports a price {sev} too low; the price recovers "
                       "afterwards, the PT itself is unchanged.",
    "feeds:stale": "An upstream feed of the lending oracle stops updating for {sev}.",
    "oracle:oracleLow": "The Morpho market oracle reports a PT price {sev} too low; the price recovers afterwards, the "
                        "PT itself is unchanged.",
    "oracle:stale": "The Morpho market oracle stops updating for {sev}.",
    "market:drain": "{sev} of the Pendle pool's liquidity leaves.",
    "pt:depeg": "The PT's market price on Pendle falls {sev}; the PT still redeems at expiry, so holding to expiry "
                "recovers it.",
    "lending:cascade": "Other borrowers of the Morpho market are liquidated at a {sev} oracle drop and their PT is sold "
                       "into the Pendle pool first.",
}
_GRADES = "ABCD"


def propagation(d, preset_key, node, fail, sev, carry=0.0, opts=None):
    """How the incident travels through the five layers to this position, step by step in causal order (origin ->
    PT value -> lending oracle -> liquidation -> exit liquidity -> loss on the position -> verdict), built only from
    decide_at's results. steps[i] = {layer (None for the position / result), node, state: origin | hit | unchanged |
    unknown | not_applicable, text, grade (None = the manager's input), edges (ui.edges crossed)}; layers = the five
    rows with their state and text. `numbers` / `unchecked` as in decision_text. Mirrored by RiskModel.propagation."""
    opts = opts or {}
    from loss_model import lif
    from reasoning import NUM
    r = decide_at(d, preset_key, node, fail, sev, carry, opts)
    m = d["ui"]["injections"][f"{node}:{fail}"]
    p = d["position_presets"][preset_key]
    ft = d["failure_types"]["types"][fail]
    o = d.get("oracle") or {}
    nodes = d["ui"]["nodes"]
    nums = []

    def f(s):
        nums.extend(NUM.findall(s))
        return s
    money = lambda v: f("$" + _num(v, 0))
    pct = lambda v: f(_num(v * 100, 2) + "%")
    unit = lambda v: f(_num(v, 2) + ("%" if ft["unit"] == "%" else " h"))
    hrs = lambda v: f(_num(v, 2) + " h")

    def edges(*pairs):
        out = []
        for a, b in pairs:
            e = next((e for e in d["ui"]["edges"] if e["from"] == a and e["to"] == b), None)
            if e:
                out.append({"from": a, "to": b, "type": e["type"], "grade": e["grade"]})
        return out

    def worst(gs):
        gs = [g for g in gs if g]
        return max(gs, key=_GRADES.index) if gs else None

    C = opts.get("collateral_usd", p["collateral_usd"])
    D = opts.get("debt_usd", p["debt_usd"])
    Co = opts.get("collateral_oracle_usd", C * p.get("collateral_oracle_usd", p["collateral_usd"]) / p["collateral_usd"])
    V = opts.get("sale_value_usd", p["collateral_usd"])
    E = C - D
    hours = opts.get("hours", m.get("hours"))
    perm = opts.get("permanent", m.get("permanent"))
    can_hold = opts.get("can_hold", p["can_hold"])
    of = r["oracle_falls"]
    liq = any(r["liquidated"] or [])
    lm = m["type"] == "loss_model"
    o_grade = (o.get("evidence") or {}).get("grade") or "D"
    s = sev / 100
    steps = []

    def step(layer, nd, state, text, grade, edg=()):
        steps.append({"layer": layer, "node": nd, "state": state, "text": text, "grade": grade, "edges": list(edg)})

    # 1. origin
    origin_layer = nodes[node]["layer"]
    text = PROPAGATION_ORIGIN[f"{node}:{fail}"].replace("{sev}", unit(sev))
    if node == "market":
        text += (f" The pool takes {pct(r['sellable_now'])} of this position today, "
                 + ("nothing after." if r["sellable_later"] <= 0 else f"{pct(r['sellable_later'])} after."))
    step(origin_layer, node, "origin", text, None,
         edges(("ethena", "usde")) if node == "ethena" else edges(("feeds", "oracle")) if node == "feeds" else ())

    # 2. the PT's value (layer 4), for failures upstream of the PT
    if lm and origin_layer == 2:
        if fail == "discount":
            step(4, "pt", "unchanged", "The PT redeems at the NAV-based rate, not at sUSDe's market price: its "
                                       "redemption value does not fall, and holding to expiry recovers the discount.",
                 "A", edges(("susde", "pt")))
        else:
            if node == "susde":
                t = (f"The SY exchange rate falls with the NAV and the PT index never decreases: the PT's value falls "
                     f"{unit(sev)}")
                e = edges(("susde", "pt"))
            else:
                t = f"The PT redeems to sUSDe, which is staked USDe: the PT's value falls {unit(sev)}"
                e = edges(("usde", "susde"), ("susde", "pt"))
            if perm >= 1:
                t += "; the loss is permanent (no recovery assumed)."
            elif perm <= 0:
                t += ("; the shock is over after the incident" + (f" ({hrs(hours)})" if hours is not None else "")
                      + ", so a holder who can wait gets it back.")
            else:
                t += f"; {pct(perm)} of it remains after the incident."
            if not can_hold:
                t += " This position must sell at the worst point."
            step(4, "pt", "hit", t, worst([x["grade"] for x in e]) or "A", e)

    # 3. the lending oracle (layer 3)
    if lm and node not in ("oracle",):
        meta = o.get("kind") == "meta_oracle_timelock" and m["oracle"] == "rule"
        thr, tl = o.get("deviation_threshold"), o.get("challenge_timelock_s")
        if node == "feeds":
            st, t = "hit", f"The Morpho market oracle reads this feed: it falls {unit(sev)} too."
        elif of is True and meta:
            st, t = "hit", (f"The meta-oracle sees a deviation above {pct(thr)} for at least {hrs(tl / 3600)} and "
                            f"switches to its backup feed with USDe / USD: the lending oracle falls {unit(sev)}.")
        elif of is True:
            st, t = "hit", f"The lending oracle follows: it falls {unit(sev)}."
        elif of is False and meta and thr is not None and s <= thr:
            st, t = "unchanged", (f"The deviation ({unit(sev)}) is not above the meta-oracle's {pct(thr)} threshold: "
                                  f"the lending oracle does not move.")
        elif of is False and meta:
            st, t = "unchanged", (f"The meta-oracle switches only after a deviation above {pct(thr)} lasting "
                                  f"{hrs(tl / 3600)}; this incident lasts {hrs(hours)}: the lending oracle does not move.")
        elif of is False:
            st, t = "unchanged", ("No feed of the lending oracle prices this (the PT is priced by a linear discount, "
                                  "no market input): the lending oracle does not move.")
        else:
            st, t = "unknown", (f"The lending oracle's behaviour is unknown: the loss is the worse of both branches "
                                f"({pct(r['L_low'])} to {pct(r['L_high'])} of equity).")
        if D <= 0:
            t += " This matters only for a levered position: this one has no debt."
        step(3, "oracle", st, t, o_grade)

    # 4. liquidation (layer 5)
    if lm:
        if D <= 0:
            step(5, "lending", "not_applicable", "This position has no debt: nothing to liquidate.", None)
        else:
            line = 1 - D / (Co * p["lltv"])
            bonus = pct(lif(p["lltv"]) - 1)
            e = edges(("oracle", "lending"), ("pt", "lending"))
            if liq and line <= 0:
                st, t = "hit", (f"The position is already above the liquidation line: Morpho can liquidate it, the "
                                f"liquidator taking collateral worth the debt plus a {bonus} bonus.")
            elif liq and of is None:
                st, t = "hit", (f"If the oracle follows, the position is liquidated (the liquidation line is "
                                f"{pct(line)} away); the liquidator takes collateral worth the debt plus a {bonus} bonus.")
            elif liq:
                st, t = "hit", (f"The lending oracle falls {unit(sev)} while the liquidation line is {pct(line)} away: "
                                f"Morpho liquidates this position, the liquidator taking collateral worth the debt plus "
                                f"a {bonus} bonus.")
            elif of is True:
                st, t = "unchanged", (f"The lending oracle falls {unit(sev)} but the liquidation line is {pct(line)} "
                                      f"away: not liquidated.")
            else:
                st, t = "unchanged", (f"The lending oracle does not move: not liquidated (the liquidation line is "
                                      f"{pct(line)} away).")
            step(5, "lending", st, t, worst(["B"] + [x["grade"] for x in e]), e)

    # 5. exit liquidity (layer 4)
    if m["type"] != "not_modelled" and node != "market":
        if r["sellable_later"] < r["sellable_now"] - 1e-12:
            t = ("Liquidators sell the seized PT into the Pendle pool first: "
                 + (f"the pool takes {pct(r['sellable_now'])} of this position today, nothing after."
                    if r["sellable_later"] <= 0 else
                    f"the pool takes {pct(r['sellable_now'])} of this position today, only "
                    f"{pct(r['sellable_later'])} after."))
            e = edges(("lending", "market"))
            step(4, "market", "hit", t, worst(["B"] + [x["grade"] for x in e]), e)
        else:
            step(4, "market", "unchanged", f"The Pendle pool still takes {pct(r['sellable_now'])} of this position "
                                           f"({money(r['sellable_now'] * V)}).", "A")

    # 6. the position and 7. the verdict
    hit_grades = [x["grade"] for x in steps if x["state"] in ("hit", "unknown")]
    pe = edges(("pt", "position")) + (edges(("lending", "position")) if D > 0 else [])
    loss = r["loss_if_stay_usd"]
    if lm:
        t = (f"Loss if staying: {money(loss)} ({pct(r['L_high'])} of the position's equity of {money(E)})."
             if loss > 0 else "No loss on this position at this severity.")
    elif m["type"] in ("exit_later", "exit_only"):
        t = "No direct loss on this position: only how much of it can be sold changes."
    else:
        t = "No loss is modelled for this failure."
    step(None, "position", "hit" if loss > 0 else "unchanged", t, worst(hit_grades) or "A", pe)
    if lm and loss > 0 and r["verdict"] != "STAY":
        res = (f"{r['verdict']}: sell {money(r['sell_usd'])} now ({pct(r['sell_fraction'])} of the position) for "
               f"{money(r['sale_cost_usd'])}; acting costs {money(r['total_if_act_usd'])} in all instead of "
               f"{money(loss)}." + (f" {pct(r['stuck_fraction'])} cannot be sold through the pool now."
                                    if r["stuck_fraction"] > 0 else ""))
    elif lm and loss > 0:
        res = f"STAY: selling would cost more than it saves (doing nothing loses {money(loss)})."
    else:
        res = "STAY: nothing to sell for."
    step(None, "result", "result", res, None)

    rows = []
    for lay in d["ui"]["layers"]:
        mine = [x for x in steps if x["layer"] == lay["n"]]
        if lay["n"] == origin_layer:
            st = "origin"
        elif any(x["state"] == "hit" for x in mine):
            st = "hit"
        elif any(x["state"] == "unknown" for x in mine):
            st = "unknown"
        elif mine and all(x["state"] == "not_applicable" for x in mine):
            st = "not_applicable"
        elif mine:
            st = "unchanged"
        else:                                       # no step here: upstream of a loss, or outside the failure's model
            st = "unchanged" if lay["n"] < origin_layer and (lm or lay["n"] == 1) else "not_modelled"
        txt = " ".join(x["text"] for x in mine) or ("Upstream of the failure: not affected." if st == "unchanged"
                                                    else "Not part of how this failure is modelled.")
        rows.append({"n": lay["n"], "name": lay["name"], "nodes": lay["nodes"], "state": st, "text": txt})
    text = " ".join(x["text"] for x in steps)
    bad = [x for x in NUM.findall(text) if x not in nums]
    return {"verdict": r["verdict"], "origin": {"node": node, "layer": origin_layer}, "steps": steps, "layers": rows,
            "numbers": nums, "unchecked": bad}


def _duration_inputs(d, preset_key, r, hours, recovers):
    """The opts that make decide_at (and every function taking opts) equal decide_at_duration's result r (guide 5b)."""
    o = {"hours": hours, "collateral_usd": r["position_value_usd"], "collateral_oracle_usd": r["collateral_usd"],
         "debt_usd": r["debt_usd"], "sale_value_usd": d["position_presets"][preset_key]["collateral_usd"]}
    if recovers:
        o["permanent"] = 0
    return o


def propagation_at_duration(d, preset_key, node, fail, sev, hours, recovers=True, alt_apy=None):
    """propagation for an incident lasting `hours`, with decide_at_duration's inputs (what the duration slider shows)."""
    r = decide_at_duration(d, preset_key, node, fail, sev, hours, recovers, alt_apy)
    return propagation(d, preset_key, node, fail, sev, r["carry"], _duration_inputs(d, preset_key, r, hours, recovers))


def propagation_events(d, preset_key, node, fail, sev, recovers=True, alt_apy=None, h_min=1.0, h_max=4320.0,
                       steps=200):
    """Where the propagation changes along the duration slider: the exact durations (hours, between h_min and h_max)
    at which a step's state or the verdict changes, found by a log-spaced scan and bisection on
    propagation_at_duration. Each event lists the changed layers (state before / after, the layer's text after) and
    steps (node, state before / after, text after). The texts come from propagation (numbers checked there).
    Mirrored by RiskModel.propagationEvents."""
    import math

    def at(h):
        return propagation_at_duration(d, preset_key, node, fail, sev, h, recovers, alt_apy)

    def sig(pg):
        return [(x["node"], x["state"]) for x in pg["steps"]] + [("verdict", pg["verdict"])]
    hs = [h_min * math.exp(math.log(h_max / h_min) * i / steps) for i in range(steps + 1)]
    pgs = [at(h) for h in hs]
    events, nums, bad = [], [], []
    for i in range(steps):
        a, b, pa = hs[i], hs[i + 1], pgs[i]
        if sig(pa) == sig(pgs[i + 1]):
            continue
        sa = sig(pa)
        for _ in range(50):                           # smallest duration whose propagation differs from a's
            m = (a + b) / 2
            if sig(at(m)) == sa:
                a = m
            else:
                b = m
        before, after = at(a), at(b)
        lay = [{"n": y["n"], "name": y["name"], "from": x["state"], "to": y["state"], "text": y["text"]}
               for x, y in zip(before["layers"], after["layers"]) if x["state"] != y["state"]]
        stp_b = {x["node"]: x for x in before["steps"]}
        stp = [{"layer": y["layer"], "node": y["node"], "from": stp_b[y["node"]]["state"] if y["node"] in stp_b else None,
                "to": y["state"], "text": y["text"]}
               for y in after["steps"] if y["node"] not in stp_b or stp_b[y["node"]]["state"] != y["state"]
               or (y["node"] == "result" and before["verdict"] != after["verdict"])]
        nums += after["numbers"]
        bad += after["unchecked"]
        events.append({"hours": math.floor(b * 1e6 + 0.5) / 1e6, "verdict_before": before["verdict"],
                       "verdict_after": after["verdict"], "layers": lay, "steps": stp})
    first = pgs[0]
    return {"h_min": h_min, "h_max": h_max, "recovers": recovers,
            "start": {"verdict": first["verdict"], "layers": [{"n": x["n"], "state": x["state"]} for x in first["layers"]]},
            "events": events, "numbers": nums, "unchecked": bad}


# ------------------------------------------------------------------ the "recovers / stays" toggle: only where the cause is off-chain
RECOVERY_REASON = {
    "usde:depeg": "Whether USDe returns to $1 depends on Ethena's off-chain backing and redemptions: your assumption "
                  "(grade D).",
    "ethena:shortfall": "Whether the shortfall is covered depends on Ethena's Reserve Fund, custodians and exchanges "
                        "(off-chain): your assumption (grade D).",
    "susde:navLoss": "Whether sUSDe's NAV is restored depends on Ethena topping it up from its Reserve Fund "
                     "(off-chain): your assumption (grade D).",
    "susde:discount": "Recovers by contract: the PT redeems at sUSDe's NAV at expiry, not at its market price.",
    "pt:depeg": "Recovers by contract: the PT redeems at expiry, whatever its market price before.",
    "feeds:oracleLow": "The reported price recovers after the incident; liquidations during it stay (Morpho).",
    "oracle:oracleLow": "The reported price recovers after the incident; liquidations during it stay (Morpho).",
}


def recovery_toggle(d, node, fail):
    """Whether the page shows the "recovers / stays" toggle for this failure: only when the loss can be permanent and
    whether it comes back is decided off-chain (injection type loss_model with permanent > 0). Elsewhere the toggle
    changes nothing (the contracts already make the loss recover, or no loss is modelled) and is hidden; `reason`
    says why. Mirrored by RiskModel.recoveryToggle."""
    k = f"{node}:{fail}"
    m = d["ui"]["injections"][k]
    show = m["type"] == "loss_model" and (m.get("permanent") or 0) > 0
    if k in RECOVERY_REASON:
        reason = RECOVERY_REASON[k]
    elif show:
        reason = "Whether the loss comes back is not decided by any contract: your assumption (grade D)."
    elif m["type"] == "loss_model":
        reason = "This loss recovers by the contracts' rules."
    else:
        reason = "No loss on the position is modelled for this failure, so recovery does not change the answer."
    return {"show": show, "reason": reason}
