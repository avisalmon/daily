"""Regression tests for the newspaper.

Every test here exists because something actually went wrong. Adding one is the
last step of fixing an editorial or rendering bug — see docs/RUNBOOK.md §5.

    pytest -q
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import ledger  # noqa: E402
import validate  # noqa: E402
import weather  # noqa: E402

CSS = ROOT / "assets" / "css" / "newspaper.css"

ALL_EDITIONS = sorted((ROOT / "data" / "editions").glob("*.json"))
TOPICS = sorted((ROOT / "data" / "topics").glob("*.json"))


def paper_today() -> date:
    """The paper's day, in Asia/Jerusalem. Must match build_site.paper_today()."""
    return datetime.now(ZoneInfo("Asia/Jerusalem")).date()


# An edition may be written the evening before it runs. Until its date arrives it
# has no rendered page and is absent from the front page, archive, search and
# catalog. So checks about *rendered output* use EDITIONS, while checks about
# *content quality* use ALL_EDITIONS: tomorrow's paper is held to the same
# standard tonight, which is the only time left to fix it.
EDITIONS = [p for p in ALL_EDITIONS if date.fromisoformat(p.stem) <= paper_today()]
PENDING_EDITIONS = [p for p in ALL_EDITIONS if date.fromisoformat(p.stem) > paper_today()]


# --------------------------------------------------------------------------
# The contract in docs/SPEC.md holds for real data.
# --------------------------------------------------------------------------

def test_all_published_data_validates():
    assert validate.validate() == []


def test_there_is_at_least_one_edition():
    assert EDITIONS, "no published editions - every edition on disk is dated ahead"


# --------------------------------------------------------------------------
# Encoding. PowerShell silently rewrote docs/SPEC.md as cp1252 once and turned
# every Hebrew word into mojibake. Nothing shipped may contain it again.
# --------------------------------------------------------------------------

TEXT_FILES = [
    *ALL_EDITIONS,
    *TOPICS,
    *(ROOT / "templates").glob("*.j2"),
    *(ROOT / "docs").glob("*.md"),
    CSS,
]


@pytest.mark.parametrize("path", TEXT_FILES, ids=lambda p: p.name)
def test_no_mojibake_and_no_bom(path: Path):
    raw = path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), f"{path.name} has a UTF-8 BOM"
    text = raw.decode("utf-8")
    assert not validate.MOJIBAKE.search(text), f"{path.name} contains mojibake"


# --------------------------------------------------------------------------
# Hebrew search. A substring match for "מים" (water) also hit "אלגוריתמים"
# (algorithms), because Hebrew plurals end in "-ים".
# --------------------------------------------------------------------------

PREFIXES = "והבכלמש"


def _words(s: str) -> list[str]:
    s = re.sub(r"[\u0591-\u05C7]", "", (s or "").lower())
    s = re.sub(r"[\u201C\u201D\u2018\u2019\u05F3\u05F4\"']", "", s)
    return [w for w in re.split(r"[^0-9a-z\u0590-\u05FF]+", s) if w]


def _has_term(words: list[str], term: str) -> bool:
    for w in words:
        if w.startswith(term):
            return True
        if len(w) > 1 and w[0] in PREFIXES and w[1:].startswith(term):
            return True
    return False


def test_hebrew_plural_suffix_is_not_a_match():
    words = _words("אלגוריתמים מתקדמים")
    assert not _has_term(words, "מים"), "'מים' must not match inside a plural"


def test_hebrew_prefix_letter_still_matches():
    assert _has_term(_words("כמה המים נצרכים"), "מים")


def test_prefix_search_matches_word_start():
    assert _has_term(_words("הרופא משנה תפקיד"), "רופ")


def test_latin_terms_still_match():
    assert _has_term(_words("דיווח: Nvidia רוכשת"), "nvidia")


def test_search_index_is_built_from_real_editions():
    index = json.loads((ROOT / "assets" / "search-index.json").read_text(encoding="utf-8"))
    assert index, "search index is empty"
    dates = {d["date"] for d in index}
    assert dates <= {e.stem for e in EDITIONS}, "index references a non-existent edition"


# --------------------------------------------------------------------------
# The ledger is what stops a story printing twice.
# --------------------------------------------------------------------------

def test_url_normalization_collapses_tracking_variants():
    a = ledger.normalize_url("https://www.Example.com/a-story/?utm_source=rss&utm_medium=x")
    b = ledger.normalize_url("https://example.com/a-story")
    assert a == b


def test_url_normalization_keeps_different_stories_apart():
    assert ledger.normalize_url("https://example.com/a") != ledger.normalize_url("https://example.com/b")


def test_no_url_is_printed_in_two_editions():
    seen: dict[str, str] = {}
    for path in ALL_EDITIONS:
        ed = json.loads(path.read_text(encoding="utf-8"))
        for section in ed.get("grid", []):
            for story in section.get("stories", []):
                url = ledger.normalize_url(story["url"])
                assert url not in seen, f"{url} printed in {seen.get(url)} and {ed['date']}"
                seen[url] = ed["date"]


# --------------------------------------------------------------------------
# Weather is measured, never invented.
# --------------------------------------------------------------------------

def test_weather_codes_cover_the_documented_range():
    for code in (0, 1, 2, 3, 45, 61, 80, 95, 99):
        assert weather.describe(code) != "לא ידוע"


def test_unknown_weather_code_is_not_guessed():
    assert weather.describe(4242) == "לא ידוע"


def test_stored_weather_declares_its_source():
    for path in ALL_EDITIONS:
        alm = json.loads(path.read_text(encoding="utf-8")).get("almanac")
        if alm:
            assert alm.get("source"), f"{path.name} almanac has no source"


# --------------------------------------------------------------------------
# Learning topics.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("path", TOPICS, ids=lambda p: p.stem)
def test_quiz_answers_are_in_range(path: Path):
    topic = json.loads(path.read_text(encoding="utf-8"))
    for i, q in enumerate(topic.get("quiz", []), 1):
        assert 0 <= q["answer"] < len(q["options"]), f"Q{i} answer out of range"
        assert q.get("why"), f"Q{i} has no explanation"


PENDING_DATES = {p.stem for p in PENDING_EDITIONS}


@pytest.mark.parametrize("path", TOPICS, ids=lambda p: p.stem)
def test_every_topic_has_a_rendered_page(path: Path):
    """Every topic gets a page, except one belonging to an edition that has not
    run yet: publishing it early would reveal tomorrow's learning topic while the
    edition itself is still held back."""
    topic = json.loads(path.read_text(encoding="utf-8"))
    page = ROOT / "learn" / f"{topic['slug']}.html"

    if topic.get("edition") in PENDING_DATES:
        assert not page.exists(), (
            f"{topic['slug']} belongs to the unpublished edition {topic['edition']} "
            f"but its page is live - run build_site.py"
        )
        return

    assert page.exists(), f"{topic['slug']} has no rendered page - run build_site.py"


@pytest.mark.parametrize("path", EDITIONS, ids=lambda p: p.stem)
def test_edition_links_to_its_topic_page_and_the_catalog(path: Path):
    """The learning block silently dropped its link once: the template asked for
    `learning.url` while the data carried `learning.slug`.

    The guard here used to be `if ed["date"] not in html: continue`, which broke
    as soon as a second edition existed: the front page's archive rail links to
    every date, so an older edition matched index.html and the test demanded that
    the front page link to *that* edition's topic page.
    """
    ed = json.loads(path.read_text(encoding="utf-8"))
    slug = (ed.get("learning") or {}).get("slug")
    if not slug:
        pytest.skip("edition has no learning topic")

    pages = [ROOT / "editions" / f"{ed['date']}.html"]
    if path == EDITIONS[-1]:  # the newest edition is also the front page
        pages.append(ROOT / "index.html")

    for page in pages:
        html = page.read_text(encoding="utf-8")
        assert f"{slug}.html" in html, f"{page.name} does not link to the topic page"
        assert "learn.html" in html, f"{page.name} does not link to the catalog"


def test_the_front_page_is_the_newest_edition():
    """index.html is the paper of the day. Building a new edition must promote it
    to the front page and push the previous one into the archive; a stale front
    page shipped once and nothing caught it.

    "Newest" means newest *due*, not newest on disk: an edition dated ahead is
    written the evening before and must not reach the front page until its day."""
    newest = json.loads(EDITIONS[-1].read_text(encoding="utf-8"))
    index = (ROOT / "index.html").read_text(encoding="utf-8")

    assert newest["date_long"] in index, (
        f"index.html does not carry {newest['date']} - run build_site.py"
    )
    assert newest["lead"]["headline"] in index, "front page shows a different lead"

    for older in EDITIONS[:-1]:
        prev = json.loads(older.read_text(encoding="utf-8"))
        assert prev["lead"]["headline"] not in index, (
            f"index.html still shows the lead from {prev['date']}"
        )
        assert f"editions/{prev['date']}.html" in index, (
            f"{prev['date']} is not reachable from the front page archive rail"
        )


@pytest.mark.parametrize("path", PENDING_EDITIONS, ids=lambda p: p.stem)
def test_an_edition_dated_ahead_is_not_published_anywhere(path: Path):
    """The site is world-readable the moment it is committed, so an edition written
    tonight for tomorrow must leave no trace: no page, no headline on the front,
    no archive link, no search hit, no research PDF."""
    ed = json.loads(path.read_text(encoding="utf-8"))
    date_str = ed["date"]

    page = ROOT / "editions" / f"{date_str}.html"
    assert not page.exists(), f"{page.name} is published before {date_str}"

    # research/<date>.pdf is intentionally present: it is the only copy of the
    # PDF in the repository, and the cloud build needs it to publish the edition
    # on its day. It must stay unreachable - no page may link to it.
    for page_name in ("index.html", "archive.html", "learn.html"):
        html = (ROOT / page_name).read_text(encoding="utf-8")
        assert ed["lead"]["headline"] not in html, f"{page_name} leaks the {date_str} lead"
        assert f"editions/{date_str}.html" not in html, f"{page_name} links to the held-back {date_str}"
        assert f"research/{date_str}.pdf" not in html, f"{page_name} links to the held-back research"

    index = json.loads((ROOT / "assets" / "search-index.json").read_text(encoding="utf-8"))
    dates = {d.get("date") for d in (index if isinstance(index, list) else index.get("docs", []))}
    assert date_str not in dates, f"search index exposes the held-back {date_str}"


@pytest.mark.parametrize("path", PENDING_EDITIONS, ids=lambda p: p.stem)
def test_a_held_back_edition_keeps_its_research_pdf_in_the_repo(path: Path):
    """The source PDF under data/research/ is gitignored, so research/<date>.pdf
    is the only copy committed. Withdrawing it left the cloud build with nothing
    to publish at midnight, and CI failed on exactly this."""
    ed = json.loads(path.read_text(encoding="utf-8"))
    url = (ed.get("lead") or {}).get("url", "")
    if not url.startswith("research/"):
        pytest.skip("lead does not link to a research PDF")
    assert (ROOT / url).exists(), (
        f"{url} is missing - the edition cannot be published on its day"
    )


def test_compound_interest_matches_the_numbers_in_the_article():
    """The prose quotes 2,594 and 17,449. The simulator must agree."""
    P, r = 1000, 0.10
    assert round(P * (1 + r) ** 10) == 2594
    assert round(P * (1 + r) ** 30) == 17449
    assert round(P * (1 + r * 10)) == 2000
    assert round(P * (1 + r * 30)) == 4000


# --------------------------------------------------------------------------
# Rendering. The CSS broke once from overlapping edits and shipped unnoticed.
# --------------------------------------------------------------------------

def _render_story(story: dict) -> str:
    """Render one grid story through the real edition template."""
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    import build_site

    env = Environment(
        loader=FileSystemLoader(build_site.TEMPLATE_DIR),
        autoescape=select_autoescape(["html", "j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    src = (build_site.TEMPLATE_DIR / "edition.html.j2").read_text(encoding="utf-8")
    start = src.index("{% for story in section.stories %}")
    end = src.index("{% endfor %}", start) + len("{% endfor %}")
    fragment = src[start:end].replace("section.stories", "stories")
    return env.from_string(fragment).render(stories=[story])


BARE_STORY = {
    "headline": "כותרת",
    "summary": "תקציר",
    "source": "מקור",
    "time": "10:00",
    "url": "https://example.com",
}


def test_a_story_without_video_renders_no_iframe():
    html = _render_story(dict(BARE_STORY))
    assert "<iframe" not in html
    assert "story__video" not in html


def test_a_video_story_embeds_through_the_nocookie_host():
    """We never hand the reader's visit to youtube.com directly, and the frame
    must be lazy so a video can't hold up the front page."""
    html = _render_story({**BARE_STORY, "video": {
        "youtube_id": "CHjdtTROPZg",
        "caption": "כיתוב",
        "credit": "Associated Press",
    }})
    assert "youtube-nocookie.com/embed/CHjdtTROPZg" in html
    assert "www.youtube.com/embed" not in html
    assert 'loading="lazy"' in html
    assert "כיתוב" in html
    assert "Associated Press" in html


def test_a_video_without_an_id_is_ignored_rather_than_rendered_broken():
    html = _render_story({**BARE_STORY, "video": {"caption": "אין מזהה"}})
    assert "<iframe" not in html
    assert "אין מזהה" not in html


def test_every_video_in_every_edition_declares_a_credit():
    """An embed is a quotation. It carries its publisher, like any other source.
    Checked across every edition on disk, including ones not yet due: tonight is
    the last chance to catch it."""
    for path in ALL_EDITIONS:
        edition = json.loads(path.read_text(encoding="utf-8"))
        for section in edition.get("grid", []):
            for story in section.get("stories", []):
                video = story.get("video")
                if not video:
                    continue
                assert video.get("youtube_id"), f"{path.name}: video with no id"
                assert video.get("credit"), (
                    f"{path.name}: video {video['youtube_id']} has no credit"
                )


# --------------------------------------------------------------------------
# The research bank: a pool of undated deep researches.
# --------------------------------------------------------------------------

# The bank PDFs and the dated source PDFs are gitignored inputs: they exist only
# on the machine where the paper is written. The tests below guard that
# workspace's bookkeeping, not the published site, so a checkout that never had
# the inputs - the cloud publish job - skips them instead of failing on files it
# was never given.
BANK_DIR = ROOT / "data" / "research" / "bank"
HAS_RESEARCH_INPUTS = any(BANK_DIR.glob("*.pdf")) or any((ROOT / "data" / "research").glob("*.pdf"))
needs_research_inputs = pytest.mark.skipif(
    not HAS_RESEARCH_INPUTS,
    reason="no research inputs in this checkout - they are gitignored editorial inputs",
)


@needs_research_inputs
def test_bank_index_matches_the_files_on_disk():
    import research_bank

    data = research_bank.load()
    for item in data["items"]:
        pdf = research_bank.BANK_DIR / item["file"]
        assert item.get("missing") == (not pdf.exists()), (
            f"{item['id']} 'missing' flag is stale - run research_bank.py scan"
        )


def test_bank_ids_are_unique():
    import research_bank

    ids = [i["id"] for i in research_bank.load()["items"]]
    assert len(ids) == len(set(ids))


def test_a_bank_research_is_never_used_twice():
    import research_bank

    used = [i["used_in"] for i in research_bank.load()["items"] if i.get("used_in")]
    assert len(used) == len(set(used)), "two bank items claim the same edition"


@needs_research_inputs
def test_claimed_bank_research_is_on_disk_for_its_edition():
    import research_bank

    for item in research_bank.load()["items"]:
        if not item.get("used_in"):
            continue
        expected = list((ROOT / "data" / "research").glob(f"{item['used_in']}-{item['id']}.*"))
        assert expected, f"{item['id']} claims {item['used_in']} but no research file is present"


# --------------------------------------------------------------------------
# Voice. The paper must not read as machine-written.
# --------------------------------------------------------------------------

def test_published_content_has_no_ai_tells():
    import style

    assert style.check_content() == []


def test_style_checker_catches_an_em_dash():
    import style

    assert style.check_string("הרופא לא נעלם — הוא משנה תפקיד", "x")


def test_style_checker_allows_a_tight_range():
    """2023-2026 is correct typography, not a tell."""
    import style

    assert style.check_string("ראיות 2023–2026 ובפברואר–מרץ", "x") == []


def test_style_checker_catches_emoji_and_filler():
    import style

    assert style.check_string("נהדר 🚀", "x")
    assert style.check_string("חשוב לציין שהמגמה נמשכת", "x")
    assert style.check_string("It's worth noting the trend", "x")


def test_rendered_pages_have_no_em_dashes_or_emoji():
    import style

    pages = [ROOT / "index.html", ROOT / "learn.html", ROOT / "archive.html",
             *(ROOT / "editions").glob("*.html"), *(ROOT / "learn").glob("*.html")]
    for page in pages:
        html = page.read_text(encoding="utf-8")
        text = re.sub(r"<script.*?</script>|<style.*?</style>|<!--.*?-->", "", html, flags=re.S)
        text = re.sub(r"<[^>]+>", " ", text)
        assert "—" not in text, f"{page.name} renders an em dash"
        assert not style.EMOJI.search(text), f"{page.name} renders an emoji"


def test_no_card_styling_in_css():
    """It is a newspaper, not an app: no rounded corners on content."""
    css = CSS.read_text(encoding="utf-8")
    radii = re.findall(r"border-radius:\s*([^;]+);", css)
    for value in radii:
        assert value.strip() in ("0", "0px", "50%"), f"card-style border-radius: {value}"


def test_css_braces_are_balanced():
    css = re.sub(r"/\*.*?\*/", "", CSS.read_text(encoding="utf-8"), flags=re.S)
    assert css.count("{") == css.count("}")


def test_css_has_no_rules_for_deleted_classes():
    css = CSS.read_text(encoding="utf-8")
    for dead in ("lead__figure", "story__figure", "opinion__avatar", "lead__caption"):
        assert dead not in css, f"CSS still styles removed class .{dead}"


def test_no_page_references_a_missing_local_asset():
    for page in [ROOT / "index.html", *(ROOT / "editions").glob("*.html"),
                 *(ROOT / "learn").glob("*.html")]:
        html = page.read_text(encoding="utf-8")
        base = page.parent
        for ref in re.findall(r'(?:href|src)="((?!https?:|#|mailto:)[^"]+)"', html):
            assert (base / ref).resolve().exists(), f"{page.name} -> missing {ref}"


def _site_fingerprint() -> dict[str, str]:
    files = [
        ROOT / "index.html", ROOT / "archive.html", ROOT / "learn.html",
        ROOT / "assets" / "search-index.json",
        *(ROOT / "editions").glob("*.html"),
        *(ROOT / "learn").glob("*.html"),
        *(ROOT / "data" / "editions").glob("*.json"),
    ]
    return {
        str(f.relative_to(ROOT)): hashlib.sha256(f.read_bytes()).hexdigest()
        for f in files if f.exists()
    }


def test_build_is_reproducible():
    """Building twice must succeed and produce byte-identical output.

    The exit code alone is not enough. The hourly publish job commits whatever
    the build changed, so anything that varies run to run becomes a commit every
    hour: the live weather fetch did exactly that until the reading was pinned to
    press time. If this fails, find what moved before letting CI near it."""
    before = _site_fingerprint()
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build_site.py")],
        capture_output=True, text=True, encoding="utf-8", cwd=ROOT,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr

    after = _site_fingerprint()
    moved = sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))
    assert not moved, f"rebuilding changed {moved} - CI would commit this every hour"


def _load_bank():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        'research_bank', ROOT / 'scripts' / 'research_bank.py')
    rb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rb)
    return rb


def test_bank_title_prefers_the_h1_not_the_provenance_line():
    """A deep-research document titles itself with the whole question, which can
    run past the length guard. When it did, the guard silently skipped it and the
    title became 'Deep research, o3-deep-research, <date>.'"""
    rb = _load_bank()
    long_h1 = '# The history of ice cream: ' + 'x' * 200
    doc = long_h1 + '\n\nDeep research, o3-deep-research, 2026-08-30T06:59:41+00:00.\n'
    title = rb._guess_title(doc, 'fallback')
    assert not title.lower().startswith('deep research,'), \
        'title fell through to the provenance line: ' + repr(title)
    assert title.startswith('The history of ice cream')
    assert len(title) <= 140


def test_bank_language_is_majority_script_not_mere_presence():
    """Deep-research documents are written in English but carry a Hebrew
    sources heading, which must not flip the whole document to Hebrew."""
    rb = _load_bank()
    assert rb._language('The history of ice cream is long.\n\n## מקורות\n') == 'en'
    assert rb._language('ההיסטוריה של הגלידה ארוכה.\n\n## Sources\n') == 'he'


# --- מקורות והבאת חדשות -------------------------------------------------

def test_fetch_news_writes_the_cache_it_documents():
    """RUNBOOK §4 tells you to pass data/_news_cache.json to record_edition.py,
    but nothing ever wrote that file. An editorial meeting was run off a stale
    snapshot from a previous day, and five items had already been printed."""
    src = (ROOT / "scripts" / "fetch_news.py").read_text(encoding="utf-8")
    assert re.search(r'CACHE\s*=.*"_news_cache\.json"', src), \
        "fetch_news.py must define the cache path it documents"
    # the write must happen before the --json early return, or piping the
    # output silently skips persisting the meeting's candidate list
    body = src[src.index("def main("):]
    assert body.index("CACHE.write_text") < body.index("if args.json:"), \
        "the cache is written after the --json return: piping skips it"


def test_fetch_news_retries_a_failing_feed():
    """A single transient failure used to drop a whole source from the meeting,
    which quietly narrows the paper without anyone noticing."""
    src = (ROOT / "scripts" / "fetch_news.py").read_text(encoding="utf-8")
    fn = src[src.index("def fetch_one("):]
    fn = fn[:fn.index("\ndef ")]
    assert "range(" in fn and "time.sleep" in fn, \
        "fetch_one must retry with a pause between attempts"


def test_sources_are_not_only_ai():
    """The catalog once held ten AI feeds and nothing else, so no Israeli or
    scientific story could ever be proposed at a meeting. The user had to ask
    for it twice before the cause was found."""
    import yaml
    cfg = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))
    feeds = cfg["sources"] if isinstance(cfg, dict) else cfg
    topics = {t for s in feeds for t in (s.get("topics") or [])}
    assert len(feeds) >= 20, f"only {len(feeds)} feeds - the paper will be thin"
    for needed in ("israel", "science"):
        assert any(needed in t for t in topics), \
            f"no '{needed}' source in the catalog: {sorted(topics)}"


def test_no_published_item_is_proposed_again():
    """Dedup lives on the ledger's `published` key. Reading `printed` instead
    returns nothing and silently disables duplicate detection."""
    ledger = json.loads((ROOT / "data" / "ledger.json").read_text(encoding="utf-8-sig"))
    assert "published" in ledger and "proposed" in ledger, \
        f"ledger keys changed: {sorted(ledger)}"
    urls = [i.get("url") for i in ledger["published"] if i.get("url")]
    assert len(urls) == len(set(urls)), "the same URL was published twice"
