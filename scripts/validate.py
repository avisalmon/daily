"""Machine-enforced subset of docs/SPEC.md.

Every rule here exists because something went wrong once. Prose in a doc
regresses silently; this does not — build_site.py refuses to publish an
edition that fails validation.

Adding a rule is the *last step* of fixing any editorial bug:

    python scripts\\validate.py            # check everything
    python scripts\\validate.py 2026-08-30 # check one edition
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

import ledger
import style

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "editions"
TOPIC_DIR = ROOT / "data" / "topics"
PLAN_DIR = ROOT / "data" / "plans"
CLAIMS_DIR = ROOT / "data" / "research" / "claims"
RESEARCH_OUT = ROOT / "research"

# UTF-8 Hebrew bytes decoded as cp1252 always start with these. If this shows
# up in a data file, PowerShell mangled it (see docs/BKM.md §5).
MOJIBAKE = re.compile(r"×[\u0080-\u00BF\u2018-\u201D\u0090\u009D]")

PLACEHOLDERS = ("PLACEHOLDER", "TODO", "FIXME", "Lorem ipsum", "לורם איפסום")

HTTP = re.compile(r"^https?://", re.I)

HEBREW = re.compile(r"[\u0590-\u05FF]")

# BKM §6: sources that have proven unusable. Never cite them again.
BLOCKED_DOMAINS = {
    "calcalist.co.il": "returns 403 even with a browser UA - cannot be fact-checked",
    "calcalistech.com": "returns 403 even with a browser UA - cannot be fact-checked",
}

# BKM §2: hedge words required when a story is a report rather than a fact.
UNCONFIRMED_MARKERS = ("דיווח", "לפי הדיווח", "נטען", "על פי", "לכאורה", "מדווח")

MIN_SUMMARY_CHARS = 80


class Problem(Exception):
    pass


def _fail(errors: list[str], where: str, msg: str) -> None:
    errors.append(f"{where}: {msg}")


def check_edition(ed: dict, path: Path, seen_urls: dict[str, str], errors: list[str]) -> None:
    where = path.name

    for field in ("date", "number", "lead", "grid", "compiled_at"):
        if field not in ed:
            _fail(errors, where, f"missing required field '{field}'")
    if errors and "date" not in ed:
        return

    try:
        date.fromisoformat(ed["date"])
    except (ValueError, TypeError):
        _fail(errors, where, f"date {ed.get('date')!r} is not an ISO date")

    if ed["date"] != path.stem:
        _fail(errors, where, f"date {ed['date']!r} does not match filename")

    # ---- lead -------------------------------------------------------------
    lead = ed.get("lead") or {}
    for field in ("headline", "source", "url"):
        if not lead.get(field):
            _fail(errors, where, f"lead is missing '{field}'")

    url = lead.get("url", "")
    if url and not HTTP.match(url) and not url.startswith("#"):
        # A relative lead URL means a published research PDF; it must exist.
        if not (ROOT / url).exists():
            _fail(errors, where, f"lead links to {url!r} which does not exist on disk")

    fig = lead.get("figure")
    if fig:
        if not fig.get("source"):
            _fail(errors, where, "lead.figure has no 'source' - figures must cite real data")
        for bar in fig.get("bars") or []:
            if not isinstance(bar.get("value"), (int, float)):
                _fail(errors, where, f"figure bar {bar.get('label')!r} has a non-numeric value")
        if not fig.get("bars"):
            _fail(errors, where, "lead.figure has no bars")

    # ---- briefs -----------------------------------------------------------
    briefs = [s for section in ed.get("grid", []) for s in section.get("stories", [])]
    for s in briefs:
        tag = (s.get("headline") or "?")[:40]
        for field in ("headline", "summary", "source", "url"):
            if not s.get(field):
                _fail(errors, where, f"brief {tag!r} is missing '{field}'")
        if s.get("url") and not HTTP.match(s["url"]):
            _fail(errors, where, f"brief {tag!r} has a non-absolute url {s['url']!r}")

        # BKM §6 - a source we cannot fetch is a source we cannot fact-check.
        host = urlsplit(s.get("url") or "").netloc.lower().removeprefix("www.")
        for blocked, why in BLOCKED_DOMAINS.items():
            if host == blocked or host.endswith("." + blocked):
                _fail(errors, where, f"brief {tag!r} cites blocked source {blocked} ({why})")

        # BKM §3 - briefs are written fresh in Hebrew, never pasted.
        summary = s.get("summary") or ""
        if summary:
            if not HEBREW.search(summary):
                _fail(errors, where, f"brief {tag!r} summary is not in Hebrew")
            if len(summary) < MIN_SUMMARY_CHARS:
                _fail(errors, where,
                      f"brief {tag!r} summary is {len(summary)} chars - too short to be a written brief")
            if summary.strip() == (s.get("headline") or "").strip():
                _fail(errors, where, f"brief {tag!r} summary just repeats the headline")

    # BKM §3 - two briefs sharing prose means something was pasted.
    summaries: dict[str, str] = {}
    for s in briefs:
        key = (s.get("summary") or "").strip()
        if key and key in summaries:
            _fail(errors, where, f"briefs {summaries[key]!r} and {(s.get('headline') or '')[:40]!r} share the same summary")
        summaries[key] = (s.get("headline") or "")[:40]

    # ---- no story printed twice, ever -------------------------------------
    for s in briefs:
        u = (s.get("url") or "").rstrip("/").lower()
        if not u:
            continue
        if u in seen_urls and seen_urls[u] != ed["date"]:
            _fail(errors, where, f"url already printed in {seen_urls[u]}: {u}")
        seen_urls.setdefault(u, ed["date"])

    dupes = [u for u in {s.get("url") for s in briefs} if u and
             sum(1 for s in briefs if s.get("url") == u) > 1]
    for u in dupes:
        _fail(errors, where, f"url appears twice in the same edition: {u}")

    # ---- weather is measured, never invented ------------------------------
    alm = ed.get("almanac")
    if alm and not alm.get("source"):
        _fail(errors, where, "almanac has no 'source' - weather must be fetched, never written by hand")

    # ---- learning topic ---------------------------------------------------
    learn = ed.get("learning")
    if learn:
        for field in ("title", "summary"):
            if not learn.get(field):
                _fail(errors, where, f"learning is missing '{field}'")
        slug = learn.get("slug")
        # Without a slug (or an explicit url) the template has nothing to link
        # to and silently drops the link - this actually shipped once.
        if not slug and not learn.get("url"):
            _fail(errors, where, "learning has neither 'slug' nor 'url' - the paper would not link to the topic page")
        if slug and not (TOPIC_DIR / f"{slug}.json").exists():
            _fail(errors, where, f"learning.slug {slug!r} has no data/topics/{slug}.json")

    # ---- nothing half-written, nothing mangled ----------------------------
    blob = json.dumps(ed, ensure_ascii=False)
    for marker in PLACEHOLDERS:
        if marker.lower() in blob.lower():
            _fail(errors, where, f"contains placeholder text {marker!r}")
    if MOJIBAKE.search(blob):
        _fail(errors, where, "contains mojibake - a tool wrote UTF-8 as cp1252 (docs/BKM.md §5)")


def check_plan(ed: dict, path: Path, errors: list[str]) -> None:
    """BKM §1 and §2 - decisions are persisted, and facts are checked.

    The plan is the audit trail: it says what you chose and what was verified
    before printing. An edition without one cannot be traced back to a decision.
    """
    where = path.name
    plan_path = PLAN_DIR / f"{ed['date']}.plan.json"
    if not plan_path.exists():
        _fail(errors, where, f"no editorial plan at data/plans/{ed['date']}.plan.json (BKM §1)")
        return

    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except Exception as exc:
        _fail(errors, plan_path.name, f"unreadable: {exc}")
        return

    if plan.get("edition_date") != ed["date"]:
        _fail(errors, plan_path.name, f"edition_date {plan.get('edition_date')!r} does not match filename")

    # Every printed brief must trace back to a plan item that was verified.
    verified = {
        ledger.normalize_url(b.get("url", "")): b.get("verified")
        for b in plan.get("briefs", [])
        if b.get("url")
    }
    for section in ed.get("grid", []):
        for s in section.get("stories", []):
            key = ledger.normalize_url(s.get("url", ""))
            if key not in verified:
                _fail(errors, where,
                      f"brief {(s.get('headline') or '?')[:40]!r} is not in the plan - it was never chosen")
            elif not verified[key]:
                _fail(errors, where,
                      f"brief {(s.get('headline') or '?')[:40]!r} has no 'verified' note in the plan (BKM §2)")


def check_ledger_closed(ed: dict, path: Path, errors: list[str]) -> None:
    """BKM §4 - the ledger is what stops a story printing twice.

    If record_edition.py was not run, the story stays in the proposed pool and
    the next editorial meeting will cheerfully offer it again.
    """
    where = path.name
    printed = ledger.published_urls()
    pool = set(ledger.proposed_counts())

    for section in ed.get("grid", []):
        for s in section.get("stories", []):
            key = ledger.normalize_url(s.get("url", ""))
            if not key:
                continue
            tag = (s.get("headline") or "?")[:40]
            if key not in printed:
                _fail(errors, where,
                      f"brief {tag!r} is not in the ledger - run record_edition.py {ed['date']} (BKM §4)")
            if key in pool:
                _fail(errors, where, f"brief {tag!r} is still in the proposed pool after being printed")


def check_encoding(path: Path, errors: list[str]) -> None:
    """BKM §5 - the ways Windows tooling silently corrupts a UTF-8 file."""
    raw = path.read_bytes()
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        _fail(errors, path.name, "is UTF-16 - '>' redirection was used instead of Out-File -Encoding utf8")
    if raw.startswith(b"\xef\xbb\xbf"):
        _fail(errors, path.name, "has a UTF-8 BOM - rewrite it without one")
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        _fail(errors, path.name, f"is not valid UTF-8: {exc}")


def check_topic(topic: dict, path: Path, errors: list[str]) -> None:
    where = path.name
    for field in ("slug", "title", "summary", "sections"):
        if not topic.get(field):
            _fail(errors, where, f"missing required field '{field}'")

    if topic.get("slug") and topic["slug"] != path.stem:
        _fail(errors, where, f"slug {topic['slug']!r} does not match filename")

    quiz = topic.get("quiz") or []
    if len(quiz) < 3:
        _fail(errors, where, f"quiz has {len(quiz)} questions, needs at least 3")
    for i, q in enumerate(quiz, 1):
        opts = q.get("options") or []
        if len(opts) < 2:
            _fail(errors, where, f"quiz Q{i} has fewer than 2 options")
        ans = q.get("answer")
        if not isinstance(ans, int) or not (0 <= ans < len(opts)):
            _fail(errors, where, f"quiz Q{i} answer {ans!r} is out of range")
        if not q.get("why"):
            _fail(errors, where, f"quiz Q{i} has no 'why' - every answer must be explained")

    blob = json.dumps(topic, ensure_ascii=False)
    if MOJIBAKE.search(blob):
        _fail(errors, where, "contains mojibake (docs/BKM.md §5)")


def check_research_sealed(ed: dict, path: Path, errors: list[str]) -> None:
    """An edition may only lean on deep research that survived two checkers.

    BKM §9. Deep research writes with a citation on every sentence and is wrong
    anyway: the first real run reproduced the Catherine de Medici legend while
    citing, 18 times, the article that debunks it. So a research document is
    printable only once `verify_research.py seal` has passed on it.
    """
    research = ed.get("research")
    if not research:
        return
    if isinstance(research, str):
        research = {"id": research}
    doc_id = research.get("id") or research.get("doc")
    if not doc_id:
        return

    ledger = CLAIMS_DIR / f"{doc_id}.json"
    if not ledger.exists():
        _fail(errors, path.name,
              f"research '{doc_id}' has no claim ledger. "
              f"Run: python scripts\\verify_research.py extract {doc_id}")
        return
    try:
        data = json.loads(ledger.read_text(encoding="utf-8"))
    except Exception as exc:
        _fail(errors, path.name, f"claim ledger for '{doc_id}' unreadable: {exc}")
        return
    if not data.get("sealed_at"):
        unchecked = sum(1 for c in data.get("claims", [])
                        if c.get("verdict") in ("unchecked", "single-check"))
        _fail(errors, path.name,
              f"research '{doc_id}' is not sealed ({unchecked} claims not checked "
              f"twice). Deep research is a map, not a source: see BKM §9.")


def validate(only: str | None = None) -> list[str]:
    errors: list[str] = []
    seen_urls: dict[str, str] = {}

    paths = sorted(DATA_DIR.glob("*.json"))
    if only:
        paths = [p for p in paths if p.stem == only]
        if not paths:
            raise SystemExit(f"No edition found for {only}")

    for path in paths:
        check_encoding(path, errors)
        try:
            ed = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            _fail(errors, path.name, f"unreadable: {exc}")
            continue
        check_edition(ed, path, seen_urls, errors)
        check_plan(ed, path, errors)
        check_ledger_closed(ed, path, errors)
        check_research_sealed(ed, path, errors)

    for path in sorted(TOPIC_DIR.glob("*.json")):
        check_encoding(path, errors)
        try:
            topic = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            _fail(errors, path.name, f"unreadable: {exc}")
            continue
        check_topic(topic, path, errors)

    # The paper must not read as machine-written (docs/SPEC.md).
    errors += style.check_content()

    return errors


def main() -> int:
    only = sys.argv[1] if len(sys.argv) > 1 else None
    errors = validate(only)
    if errors:
        print(f"VALIDATION FAILED - {len(errors)} problem(s):")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("Validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
