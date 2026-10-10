#!/usr/bin/env python3
"""
Off-chain dependencies with their sources: who issues, holds, hedges or backs a token where the chain cannot show it.

  python3 offchain.py            # fetch every source again and check that each quote is on the page (GATE lines)
  python3 offchain.py --list     # print the relations per token, no fetching

offchain_deps.json (committed) lists, per token, relations found in the issuer's own documents (or third-party pages,
marked official = false), each with the URL and a short verbatim quote. The relations were found by reading documents
(partly with an LLM); nothing here is a number we compute. Evidence grade D: stated by the issuer, not verifiable on
chain. This script re-fetches every URL and checks that the quote is in the page text (HTML: tags stripped; PDF: text
from `pdftotext` when installed, otherwise "not checked here"). Results go to data/offchain_check.json; a quote that
is no longer on its page is a GATE FAIL.
"""
import argparse
import datetime as dt
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DEPS = os.path.join(HERE, "offchain_deps.json")
CHECK = os.path.join(HERE, "data", "offchain_check.json")
UA = "Mozilla/5.0 (belem-offchain/1.0)"
GRADE = {"grade": "D", "rule": "stated in the issuer's own documents (official = false: a third-party page), "
                                "not verifiable on chain; the quote is re-checked on the page by offchain.py"}


def load(path=DEPS):
    with open(path) as f:
        return json.load(f)


def norm(text):
    """Lower case, one kind of quote / dash / space, no soft hyphens: enough to find a quote in extracted text."""
    t = html.unescape(text)
    t = t.replace("­", "").replace(" ", " ")
    for a, b in (("’", "'"), ("‘", "'"), ("“", '"'), ("”", '"'), ("–", "-"), ("—", "-"),
                 ("‑", "-"), ("‐", "-")):
        t = t.replace(a, b)
    t = re.sub(r"-\s*\n\s*", "-", t)                  # words split at a line end by a hyphen (PDF)
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r" ([,.;:!?')])", r"\1", t)             # inline tags stripped to spaces leave "word ," / "X 's"
    return t.strip().lower()


def page_text(url, timeout=60):
    """(status, text or None, how): HTML without tags, PDF through pdftotext; None when it cannot be read here."""
    m = re.match(r"https://etherscan\.io/address/(0x[0-9a-fA-F]{40})#code$", url)
    if m:                                                 # verified source: through the Etherscan API (etherscan.py)
        try:
            import etherscan
            code = etherscan.source(m.group(1).lower()).get("SourceCode") or ""
            if code.startswith("{{"):                     # multi-file standard JSON input: {{...}}
                code = "\n".join(f.get("content", "") for f in json.loads(code[1:-1]).get("sources", {}).values())
            return 200, code, "etherscan verified source"
        except SystemExit:                                # no ETHERSCAN_API_KEY on this machine
            return None, None, "Etherscan source: no ETHERSCAN_API_KEY here, not checked"
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body, ctype, status = r.read(), r.headers.get("Content-Type", ""), r.status
    except urllib.error.HTTPError as e:
        return e.code, None, f"HTTP {e.code}"
    except Exception as e:                                # network error: reported, not hidden
        return None, None, f"{type(e).__name__}: {str(e)[:80]}"
    if "pdf" in ctype.lower() or url.lower().split("?")[0].endswith(".pdf") or body[:5] == b"%PDF-":
        exe = shutil.which("pdftotext")
        if not exe:
            return status, None, "PDF: pdftotext not installed, not checked here"
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "f.pdf")
            with open(p, "wb") as f:
                f.write(body)
            out = subprocess.run([exe, "-enc", "UTF-8", p, "-"], capture_output=True)
        return status, out.stdout.decode("utf-8", "replace"), "pdf"
    text = body.decode("utf-8", "replace")
    if "json" in ctype.lower():                           # e.g. a blog's own JSON API behind a JS-rendered page
        def strings(x):
            if isinstance(x, str):
                yield x
            elif isinstance(x, dict):
                for v in x.values():
                    yield from strings(v)
            elif isinstance(x, list):
                for v in x:
                    yield from strings(v)
        try:
            text = " ".join(strings(json.loads(text)))
        except ValueError:
            pass
        text = re.sub(r"(?s)<[^>]+>", " ", text)
        return status, text, "json"
    if "html" in ctype.lower() or text.lstrip()[:1] == "<":
        text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", text)
        text = re.sub(r"(?s)<[^>]+>", " ", text)
        return status, text, "html"
    return status, text, "text"


def verify(deps, log=print):
    pages, rows = {}, []
    for t in deps["tokens"]:
        for r in t["relations"]:
            if r["url"] not in pages:
                pages[r["url"]] = page_text(r["url"])
            status, text, how = pages[r["url"]]
            found = None if text is None else norm(r["quote"]) in norm(text)
            rows.append({"symbol": t["symbol"], "entity": r["entity"], "url": r["url"], "status": status, "read_as": how,
                         "quote_found": found})
    checked = [x for x in rows if x["quote_found"] is not None]
    bad = [x for x in checked if not x["quote_found"]]
    for x in bad:
        log(f"  not found: {x['symbol']} / {x['entity']}: {x['url']} ({x['read_as']})")
    for x in rows:
        if x["quote_found"] is None:
            log(f"  not checked: {x['symbol']} / {x['entity']}: {x['url']} ({x['read_as']})")
    return rows, bad


def relations_for(deps, address=None, symbol=None):
    """The token's entry in offchain_deps.json (by address, else by symbol), or None."""
    for t in deps["tokens"]:
        if (address and t.get("address", "").lower() == address.lower()) or \
                (symbol and t["symbol"].lower() == (symbol or "").lower()):
            return t
    return None


def evidence(r, check=None):
    """Evidence of one relation in the repo's {grade, source} shape, plus the URL, the quote and the last check."""
    src = ("issuer document" if r.get("official", True) else "third-party page") + f": {r['url']}"
    out = {"grade": GRADE["grade"], "source": src, "url": r["url"], "quote": r["quote"], "official": r.get("official", True)}
    if check:
        c = next((x for x in check.get("rows", []) if x["url"] == r["url"] and x["entity"] == r["entity"]), None)
        if c:
            out.update(quote_found=c["quote_found"], checked_at=check.get("checked_at"))
    return out


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40]


def token_block(deps, check, address=None, symbol=None):
    """What the dashboards store for one token: issuer, summary, relations with evidence, counts. None if not listed."""
    t = relations_for(deps, address, symbol)
    if not t:
        return None
    rel = [{"entity": r["entity"], "kind": r["kind"], "relation": r["relation"],
            **({"notes": r["notes"]} if r.get("notes") else {}), "evidence": evidence(r, check)} for r in t["relations"]]
    return {"symbol": t["symbol"], "address": t.get("address"), "issuer": t.get("issuer"), "summary": t.get("summary"),
            "retrieved_at": deps.get("retrieved_at"), "grade_rule": GRADE["rule"], "relations": rel,
            "counts": {"relations": len(rel), "official": sum(r["evidence"]["official"] for r in rel),
                       "third_party": sum(not r["evidence"]["official"] for r in rel),
                       "quotes_found": sum(r["evidence"].get("quote_found") is True for r in rel),
                       "quotes_checked_at": (check or {}).get("checked_at")}}


def graph_parts(block, parent_id, layer):
    """Nodes and edges for a dependency graph: one node per off-chain entity, linked to parent_id (the issuer node),
    each with the relation's evidence (grade D, URL, quote)."""
    nodes, edges = {}, []
    for r in block["relations"]:
        nid = f"{parent_id}:{slug(r['entity'])}"
        if nid in nodes:                                  # same entity, several relations: one node
            nodes[nid]["relations"].append(r["relation"])
        else:
            nodes[nid] = {"id": nid, "label": r["entity"], "kind": "offchain_entity", "role": r["kind"], "layer": layer,
                          "address": None, "contract_name": None, "relations": [r["relation"]],
                          "evidence": {"grade": r["evidence"]["grade"], "source": r["evidence"]["source"]}}
        edges.append({"from": nid, "to": parent_id, "type": r["kind"], "kind": "offchain",
                      "evidence": f"{r['evidence']['url']}: \"{r['evidence']['quote']}\""})
    return nodes, edges


def load_check(path=CHECK):
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true", help="print the relations, do not fetch")
    a = ap.parse_args()
    deps = load()
    n = sum(len(t["relations"]) for t in deps["tokens"])
    bad_shape = [(t["symbol"], r.get("entity")) for t in deps["tokens"] for r in t["relations"]
                 if not all(r.get(k) for k in ("entity", "kind", "relation", "url", "quote"))
                 or not r["url"].startswith("https://")]
    print(f"GATE {'PASS' if not bad_shape else 'FAIL'}  {n} relations on {len(deps['tokens'])} tokens have entity, kind, "
          f"relation, https URL and quote" + (f": missing in {bad_shape[:3]}" if bad_shape else ""))
    if a.list:
        for t in deps["tokens"]:
            print(f"\n{t['symbol']} ({t.get('address')}): {t.get('issuer')}")
            for r in t["relations"]:
                print(f"  [{r['kind']}] {r['entity']}: {r['relation']}")
        sys.exit(1 if bad_shape else 0)
    rows, bad = verify(deps)
    unchecked = sum(x["quote_found"] is None for x in rows)
    os.makedirs(os.path.dirname(CHECK), exist_ok=True)
    with open(CHECK, "w") as f:
        json.dump({"checked_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "rows": rows}, f,
                  indent=1)
    print(f"GATE {'PASS' if not bad else 'FAIL'}  {len(rows) - unchecked - len(bad)}/{len(rows) - unchecked} quotes found "
          f"on their page ({unchecked} not checked here, see above); saved -> {os.path.relpath(CHECK, HERE)}")
    sys.exit(1 if bad_shape or bad else 0)


if __name__ == "__main__":
    main()
