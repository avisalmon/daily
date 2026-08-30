"""Turn a raw deep research document into a verified one, claim by claim.

Deep research is not a source. It is a research *map*: it tells you what to go
and check. The ice cream run proved the failure mode. It carried 91 citations
across only 7 domains, and it reproduced the Catherine de' Medici legend as
fact while citing, 18 times, the very Wikipedia article that debunks it.

So the pipeline is:

    1. research   scripts/deep_research.py         -> a raw document
    2. extract    verify_research.py extract       -> a claim ledger
    3. check      two independent passes           -> a verdict per claim
    4. seal       verify_research.py seal          -> printable, or not

**The two passes must be source-anchored, not model-anchored.** A second model
asked "is this true?" from memory will happily confirm the Medici myth, because
that myth is everywhere in training data. That is the same failure, twice, and
it feels like corroboration. So a check is only counted here if it carries a
URL *and* a verbatim quote from that URL. No quote, no check. The value of the
second model is that it fails differently, and it only fails differently if it
is made to go and read something.

A claim is printable only when two different checkers agree and both showed
their evidence. Anything else is cut, or printed explicitly as a legend, which
is often the better story anyway.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BANK_DIR = ROOT / "data" / "research" / "bank"
CLAIMS_DIR = ROOT / "data" / "research" / "claims"
BANK_INDEX = ROOT / "data" / "research" / "bank.json"

VERDICTS = {"confirmed", "false", "disputed", "unsupported"}
DISPOSITIONS = {"print", "label-as-legend", "cut"}

# A sentence carrying one of these is a factual claim rather than connective
# prose: a year, a quantity, a superlative, or an attribution.
CLAIMY = re.compile(
    r"\b(1[0-9]{3}|20[0-2][0-9]|[0-9]{1,4}\s*(BC|AD|BCE|CE)\b"
    r"|first\b|earliest\b|invented\b|patented\b|introduced\b|credited\b"
    r"|\$[0-9,]+|[0-9][0-9,\.]*\s*(percent|%|million|billion))",
    re.I,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _strip_citations(text: str) -> str:
    """Inline citations are noise for claim extraction and their anchor text
    is often a chunk of the quote itself, which would corrupt the claim."""
    text = re.sub(r"\(\[[^\]]*\]\([^)]*\)\)", "", text)
    text = re.sub(r"\[[^\]]*\]\([^)]*\)", "", text)
    return text


def _sentences(text: str) -> list[str]:
    body = text.split("## מקורות")[0]
    body = _strip_citations(body)
    body = re.sub(r"[*_`#>]", "", body)
    body = re.sub(r"[ \t]+", " ", body)
    out = []
    for para in body.split("\n"):
        para = para.strip()
        if not para or para.lower().startswith(("deep research,", "question asked:")):
            continue
        if re.match(r"^\d+ web searches,", para):
            continue
        for s in re.split(r"(?<=[.!?])\s+", para):
            s = s.strip(" -–—•\t")
            if len(s) > 30:
                out.append(s)
    return out


def doc_path(doc_id: str) -> Path:
    hits = sorted(BANK_DIR.glob("*.md"))
    for h in hits:
        if h.stem == doc_id:
            return h
    # allow the bank id, which may differ from the filename
    if BANK_INDEX.exists():
        idx = json.loads(BANK_INDEX.read_text(encoding="utf-8"))
        for item in idx.get("items", []):
            if item.get("id") == doc_id:
                return BANK_DIR / item["file"]
    raise SystemExit(f"No research document '{doc_id}' in the bank.")


def ledger_path(doc_id: str) -> Path:
    return CLAIMS_DIR / f"{doc_id}.json"


def load(doc_id: str) -> dict:
    p = ledger_path(doc_id)
    if not p.exists():
        raise SystemExit(f"No claim ledger for '{doc_id}'. Run: extract {doc_id}")
    return json.loads(p.read_text(encoding="utf-8"))


def save(ledger: dict) -> None:
    """Write the ledger atomically.

    A direct write failed mid-import with OSError 22 on Windows, most likely a
    scanner or another process holding the file. Writing in place means such a
    failure can leave a truncated ledger, destroying verification work that
    cost real money and hours to produce. So write a temporary file alongside
    and replace, which is atomic on Windows and POSIX alike: the ledger is
    either the old one or the new one, never a half-written one.
    """
    CLAIMS_DIR.mkdir(parents=True, exist_ok=True)
    p = ledger_path(ledger["doc"])
    body = json.dumps(ledger, ensure_ascii=False, indent=2) + "\n"

    last: Exception | None = None
    for attempt in range(5):
        tmp = p.with_suffix(f".tmp{os.getpid()}-{attempt}")
        try:
            tmp.write_text(body, encoding="utf-8", newline="\n")
            os.replace(tmp, p)
            return
        except OSError as exc:
            last = exc
            tmp.unlink(missing_ok=True)
            time.sleep(0.3 * (attempt + 1))
    raise SystemExit(f"Could not write {p}: {last}")


# ---------------------------------------------------------------------------
# extract
# ---------------------------------------------------------------------------

def _claim_id(text: str) -> str:
    """Content-derived, never positional.

    Positional ids look fine until the extractor changes and every sentence
    shifts by one. Checks recorded earlier then reattach to the *wrong* claim
    silently: a check quoting Charles I ended up filed against the Catherine
    de' Medici claim, which is the exact failure this whole tool exists to
    prevent. Hashing the claim text means a claim keeps its identity, and a
    claim whose wording changes correctly becomes a new, unchecked claim.
    """
    return "c" + hashlib.sha1(
        re.sub(r"\s+", " ", text).strip().encode("utf-8")).hexdigest()[:8]


def extract(doc_id: str) -> dict:
    path = doc_path(doc_id)
    text = path.read_text(encoding="utf-8-sig")
    claims = []
    seen = set()
    for s in _sentences(text):
        if not CLAIMY.search(s):
            continue
        cid = _claim_id(s)
        if cid in seen:
            continue
        seen.add(cid)
        claims.append({
            "id": cid,
            "text": s,
            "checks": [],
            "verdict": "unchecked",
            "disposition": None,
        })

    existing = ledger_path(doc_id)
    if existing.exists():
        old = {c["id"]: c for c in json.loads(
            existing.read_text(encoding="utf-8")).get("claims", [])}
        for c in claims:
            prev = old.get(c["id"])
            if prev and prev.get("text") == c["text"]:
                c["checks"] = prev["checks"]
                c["verdict"] = prev["verdict"]
                c["disposition"] = prev["disposition"]

    ledger = {
        "doc": doc_id,
        "file": path.name,
        "extracted_at": _now(),
        "claims": claims,
    }
    save(ledger)
    return ledger


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------

def add_check(doc_id: str, claim_id: str, by: str, verdict: str,
              url: str, quote: str) -> None:
    """Record one checker's finding. The quote is mandatory and is the whole
    point: it makes the check auditable by a human later, and it forces the
    checker to actually open the source instead of answering from memory."""
    if verdict not in VERDICTS:
        raise SystemExit(f"verdict must be one of {sorted(VERDICTS)}")
    if not url.startswith("http"):
        raise SystemExit("a check needs a real source URL")
    if len(quote.strip()) < 20:
        raise SystemExit(
            "a check needs a verbatim quote (20+ chars) from that URL.\n"
            "Without it this is a model answering from memory, which is how "
            "the Medici myth survives review.")

    ledger = load(doc_id)
    for c in ledger["claims"]:
        if c["id"] == claim_id:
            prior = next((k for k in c["checks"] if k["by"] == by), None)
            new = {"by": by, "verdict": verdict, "url": url,
                   "quote": quote.strip()[:600], "at": _now()}

            if prior and prior["verdict"] != verdict:
                # A checker reversing itself is a red flag, not a correction to
                # apply quietly. It usually means the second pass fetched the
                # wrong document: a different survey by the same pollster, or
                # the previous year's edition of the same annual report. That
                # happened here, and silently overwriting the earlier, correct
                # check would have destroyed good work while looking like
                # progress. Keep the old check and make the reversal visible.
                new["reversed"] = prior["verdict"]
                new["superseded"] = {k: prior[k] for k in ("verdict", "url",
                                                           "quote", "at")}
                c.setdefault("reversals", []).append(
                    {"by": by, "from": prior["verdict"], "to": verdict,
                     "at": new["at"]})
                print(f"  ! {by} reversed itself on {claim_id}: "
                      f"{prior['verdict']} -> {verdict}. Old source "
                      f"{prior['url']}, new source {url}. Check which "
                      f"document is actually the right one.")

            c["checks"] = [k for k in c["checks"] if k["by"] != by]
            c["checks"].append(new)
            c["verdict"] = _settle(c["checks"])
            save(ledger)
            return
    raise SystemExit(f"no claim {claim_id} in {doc_id}")


def _settle(checks: list[dict]) -> str:
    """Two different checkers must agree. One check is never enough, and two
    checks from the same checker are one check."""
    by_checker = {k["by"]: k["verdict"] for k in checks}
    if len(by_checker) < 2:
        return "unchecked" if not by_checker else "single-check"
    verdicts = set(by_checker.values())
    if len(verdicts) == 1:
        return verdicts.pop()
    return "disputed"


def set_disposition(doc_id: str, claim_id: str, disposition: str) -> None:
    if disposition not in DISPOSITIONS:
        raise SystemExit(f"disposition must be one of {sorted(DISPOSITIONS)}")
    ledger = load(doc_id)
    for c in ledger["claims"]:
        if c["id"] == claim_id:
            c["disposition"] = disposition
            save(ledger)
            return
    raise SystemExit(f"no claim {claim_id} in {doc_id}")


# ---------------------------------------------------------------------------
# seal
# ---------------------------------------------------------------------------

def brief(doc_id: str, checker: str | None = None) -> str:
    """Generate the adversarial prompt for a checking pass.

    Typing checks by hand does not survive a daily paper, and a neutral
    "please review this" prompt gets a neutral rubber stamp. This bakes in the
    framing that actually worked: name the document's weaknesses up front, ban
    answering from memory, and demand a quote per claim.
    """
    ledger = load(doc_id)
    path = doc_path(doc_id)
    text = path.read_text(encoding="utf-8-sig")
    domains = sorted({m for m in re.findall(r"https?://(?:www\.)?([^/)#\s]+)", text)})

    todo = [c for c in ledger["claims"]
            if checker is None or checker not in {k["by"] for k in c["checks"]}]

    lines = [
        "You are an ADVERSARIAL fact-checker. Your job is not to agree with this "
        "document. Your job is to try to FALSIFY each claim.",
        "",
        f"The document was produced by an AI deep-research model. It made many web "
        f"searches but cited only {len(domains)} unique domains: "
        f"{', '.join(domains)}.",
        "Treat trade associations, industry bodies, and content farms as "
        "promotional sources, not scholarship. Assume this document repeats "
        "widely-circulated myths, because that is what such sources recycle.",
        "",
        "ABSOLUTE REQUIREMENT: for every claim you MUST actually fetch a web page "
        "and paste a VERBATIM QUOTE from it. Do not answer from memory. A "
        "confident answer from memory is worthless here: common myths saturate "
        "training data, so you would simply repeat them. If you cannot fetch a "
        "source, answer 'unsupported' rather than guessing.",
        "Prefer sources independent of the ones listed above. Primary sources, "
        "academic and museum pages are best.",
        "",
        "Also flag any place where the document contradicts ITSELF.",
        "",
        f"Return one JSON array. Each element: "
        f'{{"id": "<claim id>", "verdict": "confirmed|false|disputed|unsupported", '
        f'"url": "<url you fetched>", "quote": "<verbatim quote>", '
        f'"why": "<one sentence>"}}',
        "",
        f"CLAIMS ({len(todo)}):",
    ]
    for c in todo:
        lines.append(f'  {c["id"]}: {c["text"]}')
    return "\n".join(lines)


def import_findings(doc_id: str, by: str, findings: list[dict]) -> tuple[int, list[str]]:
    """Record a whole pass at once. Rejects the bad ones individually rather
    than failing the batch, so one sloppy entry does not lose the good work."""
    ok, rejected = 0, []
    for f in findings:
        try:
            add_check(doc_id, f["id"], by, f["verdict"], f["url"], f["quote"])
            ok += 1
        except SystemExit as exc:
            rejected.append(f"{f.get('id', '?')}: {exc}")
        except KeyError as exc:
            rejected.append(f"{f.get('id', '?')}: missing field {exc}")
    return ok, rejected


def auto_disposition(doc_id: str) -> dict[str, int]:
    """Apply the obvious dispositions so a human only decides the real ones.

    confirmed -> print. false and unsupported -> cut, because printing a myth
    as a myth is a deliberate editorial choice, never a default. disputed is
    left alone: that is exactly the call a person must make.
    """
    ledger = load(doc_id)
    counts: dict[str, int] = {}
    for c in ledger["claims"]:
        if c["disposition"] is not None:
            continue
        if c["verdict"] == "confirmed":
            c["disposition"] = "print"
        elif c["verdict"] in ("false", "unsupported"):
            c["disposition"] = "cut"
        else:
            continue
        counts[c["disposition"]] = counts.get(c["disposition"], 0) + 1
    save(ledger)
    return counts


def status(doc_id: str) -> dict:
    """What still blocks a seal.

    A claim marked `cut` is not going to appear in print, so it does not need
    verifying. Demanding two checks on every sentence in a 66-claim document
    made sealing so expensive that the temptation was to skip the gate
    entirely, which is the one outcome worth avoiding. The rule is therefore:
    verify what you print, cut the rest.
    """
    ledger = load(doc_id)
    claims = ledger["claims"]
    tally: dict[str, int] = {}
    blocking = []
    for c in claims:
        tally[c["verdict"]] = tally.get(c["verdict"], 0) + 1
        if c["disposition"] == "cut":
            continue
        if c["verdict"] in ("unchecked", "single-check"):
            blocking.append((c, "not checked twice, and not cut"))
        elif c["verdict"] == "confirmed":
            if c["disposition"] not in (None, "print", "cut"):
                blocking.append((c, "confirmed but dispositioned oddly"))
        elif c["disposition"] is None:
            blocking.append((c, f"{c['verdict']} and no disposition"))
        elif c["verdict"] in ("false", "disputed") and c["disposition"] == "print":
            blocking.append((c, f"{c['verdict']} cannot be printed as fact"))
    return {"ledger": ledger, "tally": tally, "blocking": blocking}


def cut_unverified(doc_id: str) -> int:
    """Cut every claim that never got a second check.

    This is the honest way to close a document: it does not pretend those
    claims were verified, it removes them from what may be printed. Claims
    already dispositioned by a human are left alone.
    """
    ledger = load(doc_id)
    n = 0
    for c in ledger["claims"]:
        if c["disposition"] is None and c["verdict"] in ("unchecked",
                                                         "single-check"):
            c["disposition"] = "cut"
            n += 1
    save(ledger)
    return n


def printable(doc_id: str) -> list[dict]:
    """The claims an article may actually rest on."""
    return [c for c in load(doc_id)["claims"]
            if c["verdict"] == "confirmed" and c["disposition"] != "cut"]


def seal(doc_id: str) -> bool:
    st = status(doc_id)
    ledger = st["ledger"]
    print(f"{doc_id}: {len(ledger['claims'])} claims")
    for k in sorted(st["tally"]):
        print(f"  {st['tally'][k]:3}  {k}")

    if st["blocking"]:
        print(f"\nNOT SEALED. {len(st['blocking'])} claims block it:")
        for c, why in st["blocking"][:15]:
            print(f"  {c['id']}  {why}")
            print(f"        {c['text'][:100]}")
        if len(st["blocking"]) > 15:
            print(f"  ... and {len(st['blocking']) - 15} more")
        return False

    keep = [c for c in ledger["claims"] if c["disposition"] != "cut"]
    ledger["sealed_at"] = _now()
    ledger["printable"] = len(keep)
    save(ledger)
    _mark_bank(doc_id, "verified")
    print(f"\nSEALED. {len(keep)} claims verified twice and cleared for print; "
          f"{len(ledger['claims']) - len(keep)} cut. Write only from the "
          f"cleared claims.")
    return True


def _mark_bank(doc_id: str, verdict: str) -> None:
    if not BANK_INDEX.exists():
        return
    idx = json.loads(BANK_INDEX.read_text(encoding="utf-8"))
    for item in idx.get("items", []):
        if item.get("id") == doc_id or Path(item.get("file", "")).stem == doc_id:
            item.setdefault("audit", {})["verdict"] = verdict
            item["audit"]["date"] = _now()[:10]
    BANK_INDEX.write_text(json.dumps(idx, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8", newline="\n")


def show(doc_id: str, only: str | None = None) -> None:
    ledger = load(doc_id)
    for c in ledger["claims"]:
        if only and c["verdict"] != only:
            continue
        print(f"{c['id']}  [{c['verdict']}]"
              f"{'  ->' + c['disposition'] if c['disposition'] else ''}")
        print(f"      {c['text'][:160]}")
        for k in c["checks"]:
            print(f"      - {k['by']}: {k['verdict']}  {k['url'][:70]}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("extract", help="pull claims out of a research document")
    p.add_argument("doc")

    p = sub.add_parser("check", help="record one checker's finding")
    p.add_argument("doc")
    p.add_argument("claim")
    p.add_argument("--by", required=True)
    p.add_argument("--verdict", required=True, choices=sorted(VERDICTS))
    p.add_argument("--url", required=True)
    p.add_argument("--quote", required=True)

    p = sub.add_parser("disposition", help="decide what to do with a claim")
    p.add_argument("doc")
    p.add_argument("claim")
    p.add_argument("disposition", choices=sorted(DISPOSITIONS))

    p = sub.add_parser("show", help="list claims")
    p.add_argument("doc")
    p.add_argument("--only")

    p = sub.add_parser("brief", help="generate the adversarial prompt for a pass")
    p.add_argument("doc")
    p.add_argument("--for", dest="checker",
                   help="only claims this checker has not seen yet")

    p = sub.add_parser("import", help="record a whole pass from a JSON file")
    p.add_argument("doc")
    p.add_argument("--by", required=True)
    p.add_argument("--file", required=True)

    p = sub.add_parser("auto-disposition",
                       help="print the confirmed, cut the false; leave disputed to a human")
    p.add_argument("doc")

    p = sub.add_parser("cut-unverified",
                       help="cut every claim that never got a second check")
    p.add_argument("doc")

    p = sub.add_parser("printable",
                       help="the claims an article may actually rest on")
    p.add_argument("doc")

    p = sub.add_parser("seal", help="can this be printed?")
    p.add_argument("doc")

    a = ap.parse_args(argv)
    if a.cmd == "extract":
        led = extract(a.doc)
        print(f"{len(led['claims'])} claims extracted -> {ledger_path(a.doc)}")
    elif a.cmd == "check":
        add_check(a.doc, a.claim, a.by, a.verdict, a.url, a.quote)
        print(f"{a.claim}: {a.by} says {a.verdict}")
    elif a.cmd == "disposition":
        set_disposition(a.doc, a.claim, a.disposition)
        print(f"{a.claim} -> {a.disposition}")
    elif a.cmd == "show":
        show(a.doc, a.only)
    elif a.cmd == "brief":
        print(brief(a.doc, a.checker))
    elif a.cmd == "import":
        data = json.loads(Path(a.file).read_text(encoding="utf-8-sig"))
        ok, rejected = import_findings(a.doc, a.by, data)
        print(f"{ok} checks recorded from {a.by}")
        for r in rejected:
            print(f"  REJECTED {r}")
    elif a.cmd == "auto-disposition":
        counts = auto_disposition(a.doc)
        print(counts or "nothing to auto-dispose; disputed claims need you")
    elif a.cmd == "cut-unverified":
        n = cut_unverified(a.doc)
        print(f"{n} unverified claims cut. They may not be used in writing.")
    elif a.cmd == "printable":
        keep = printable(a.doc)
        print(f"{len(keep)} claims cleared for print:\n")
        for c in keep:
            print(f"  {c['id']}  {' '.join(c['text'].split())[:150]}")
    elif a.cmd == "seal":
        return 0 if seal(a.doc) else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
