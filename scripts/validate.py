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
CLAIMS_DIR = ROOT / "data" / "research" / "claims"  # verify_research.py, kept but no longer gating
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
    "nature.com": "returns 406 for the article, the PDF and Wayback - cannot be fact-checked",
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
        # A relative lead URL means a published research PDF, and the published
        # copy must exist. The source in data/research/ is gitignored, so
        # research/<date>.pdf is the only copy in the repository; accepting the
        # source instead let validation pass on this machine and fail in CI,
        # which had never seen the input file.
        if not (ROOT / url).exists():
            _fail(
                errors,
                where,
                f"lead links to {url!r} but that file does not exist. "
                f"Run build_site.py to publish it from data/research/{ed['date']}-*.pdf",
            )

    fig = lead.get("figure")
    if fig:
        if not fig.get("source"):
            _fail(errors, where, "lead.figure has no 'source' - figures must cite real data")
        for bar in fig.get("bars") or []:
            if not isinstance(bar.get("value"), (int, float)):
                _fail(errors, where, f"figure bar {bar.get('label')!r} has a non-numeric value")
        if not fig.get("bars"):
            _fail(errors, where, "lead.figure has no bars")

    # ---- lead art --------------------------------------------------------
    # The paper draws its own diagrams. A raster image is always somebody
    # else's work, so it may not be printed without saying whose it is, and it
    # must be served from this repository: VISUAL_SPEC forbids fetching art
    # from another site, which would leak readers and rot when the host moves.
    art = lead.get("image")
    if art:
        for field in ("src", "alt", "caption", "credit", "width", "height"):
            if not art.get(field):
                _fail(errors, where, f"lead.image is missing '{field}'")
        src = art.get("src") or ""
        if src:
            if HTTP.match(src) or src.startswith("//"):
                _fail(errors, where,
                      f"lead.image src {src!r} is remote - art is served from this "
                      f"repository, never hotlinked (docs/VISUAL_SPEC.md §3)")
            elif not (ROOT / src).exists():
                _fail(errors, where, f"lead.image src {src!r} is not on disk")
        for field in ("width", "height"):
            if art.get(field) is not None and not isinstance(art[field], int):
                _fail(errors, where, f"lead.image {field} must be an integer")

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

    # ---- podcast ----------------------------------------------------------
    # The player is rendered from this block alone, so a block pointing at a
    # file that is not there produces a control that loads nothing and reports
    # no error to the reader. Better to refuse to publish.
    #
    # An episode is either hosted here (`file`, written by podcast.py) or on
    # someone else's site (`link`). They render differently and cannot both be
    # set: an <audio> element cannot play a web page.
    pod = ed.get("podcast")
    if pod:
        if not pod.get("duration"):
            _fail(errors, where, "podcast is missing 'duration'")
        rel, link = pod.get("file"), pod.get("link")
        if rel and link:
            _fail(errors, where,
                  "podcast has both 'file' and 'link'. An episode is either hosted "
                  "here or elsewhere, and the two render as different things")
        elif not rel and not link:
            _fail(errors, where, "podcast has neither 'file' nor 'link' - nothing would render")
        if link and not HTTP.match(link):
            _fail(errors, where, f"podcast link {link!r} is not an absolute http(s) URL")
        if rel:
            if rel != f"audio/{ed['date']}.mp3":
                _fail(errors, where,
                      f"podcast file is '{rel}', expected 'audio/{ed['date']}.mp3'")
            # An episode past the retention window is pruned from the repository
            # and served from the release archive instead, so a missing file is
            # only an error when there is no archived copy to fall back to. This
            # is the rule that stops --prune from breaking every old edition
            # thirty days after the first episode.
            if not (ROOT / rel).exists() and not pod.get("archive_url"):
                _fail(errors, where,
                      f"podcast points at {rel}, which is not on disk, and has "
                      f"no 'archive_url' to fall back to. Record it, or upload "
                      f"it:  python scripts\\podcast.py --date {ed['date']} --upload")

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

    # The lead gets the same treatment as a brief. It is the longest piece in
    # the paper and the one built on a research document rather than on an
    # article that can be re-read in a minute, so it is the easiest place for
    # an unchecked claim to hide, and the most damaging.
    if (ed.get("lead") or {}).get("url") and not (plan.get("lead") or {}).get("verified"):
        _fail(errors, plan_path.name,
              "the lead cites research but the plan has no 'lead.verified' note. "
              "Say which claims were read at their own source before printing "
              "(BKM §2 and §9)")


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
