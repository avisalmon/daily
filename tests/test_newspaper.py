"""Regression tests for the newspaper.

Every test here exists because something actually went wrong. Adding one is the
last step of fixing an editorial or rendering bug — see docs/RUNBOOK.md §5.

    pytest -q
"""

from __future__ import annotations

import cmath
import hashlib
import json
import math
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_site  # noqa: E402
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


def test_two_research_pdfs_for_one_date_is_refused(tmp_path, monkeypatch):
    """An edition has one lead. When a supporting document was dropped next to
    the lead under the same date prefix, publish_research picked whichever name
    sorted first and the paper linked to a document nobody chose. Silent."""
    src = tmp_path / "src"
    src.mkdir()
    monkeypatch.setattr(build_site, "RESEARCH_SRC", src)
    monkeypatch.setattr(build_site, "RESEARCH_OUT", tmp_path / "out")

    (src / "2026-01-01-lead.pdf").write_bytes(b"%PDF-1.4 lead")
    assert build_site.publish_research([{"date": "2026-01-01"}]) == ["2026-01-01.pdf"]

    (src / "2026-01-01-companion.pdf").write_bytes(b"%PDF-1.4 companion")
    with pytest.raises(SystemExit) as exc:
        build_site.publish_research([{"date": "2026-01-01"}])
    assert "more than one research PDF" in str(exc.value)


def test_a_source_that_blocks_fetching_cannot_be_cited():
    """BKM §6 - a source we cannot fetch is a source we cannot fact-check.
    Calcalist returns 403 to everything, so a Calcalist link in a brief is a
    claim nobody in this pipeline can check.

    nature.com used to be the example here. It was removed from the list on
    2026-10-14 once the browser canvas turned out to read it fine, so the test
    moved to a domain that is still genuinely unreachable. A guard has to keep
    describing reality or it is just pushing the paper to a weaker source."""
    edition = {
        "date": "2026-01-01",
        "number": 1,
        "compiled_at": "07:00",
        "lead": {"headline": "כותרת", "source": "מקור", "url": "https://example.com/a"},
        "grid": [{"name": "מדע", "stories": [{
            "headline": "כותרת הידיעה",
            "summary": "טקסט בעברית שארוך מספיק כדי לעבור את סף התקציר שנקבע בוולידטור, ולכן הבדיקה תיפול על המקור ולא על האורך.",
            "source": "כלכליסט",
            "url": "https://www.calcalist.co.il/local_news/article/abc123",
        }]}],
    }
    errors: list[str] = []
    validate.check_edition(edition, Path("2026-01-01.json"), {}, errors)
    assert any("calcalist.co.il" in e for e in errors), errors


def test_no_published_brief_cites_a_blocked_source():
    """The fixture above proves the rule fires. This one walks the real
    editions, because a guard that only ever sees a hand-made dictionary is
    looking nowhere."""
    for path in sorted((ROOT / "data" / "editions").glob("*.json")):
        ed = json.loads(path.read_text(encoding="utf-8"))
        urls = [(ed.get("lead") or {}).get("url", "")]
        urls += [s.get("url", "") for sec in ed.get("grid", []) for s in sec.get("stories", [])]
        for url in urls:
            host = urlsplit(url).netloc.lower().removeprefix("www.")
            for blocked in validate.BLOCKED_DOMAINS:
                assert not (host == blocked or host.endswith("." + blocked)), \
                    f"{path.name} cites {blocked}, which cannot be fact-checked"


def test_crispr_simulator_teaches_all_three_rules():
    """The page claims three things: a PAM is required, mismatch count matters,
    and a mismatch next to the PAM stops the cut. The planted sequence has to
    contain one example of each, or the simulator quietly argues the opposite."""
    topic = json.loads((ROOT / "data" / "topics" / "crispr.json").read_text(encoding="utf-8"))
    sim = topic["sim"]
    guide, genome = sim["guide"], sim["genome"]
    G, SEED = len(guide), 10

    sites = []
    for i in range(len(genome) - G - 2):
        seq, pam = genome[i:i + G], genome[i + G:i + G + 3]
        has_pam = pam[1] == "G" and pam[2] == "G"
        bad = [G - j for j, (a, b) in enumerate(zip(seq, guide)) if a != b]
        if (has_pam and len(bad) <= 4) or not bad:
            sites.append({"at": i, "pam": has_pam, "mm": len(bad),
                          "near": min(bad) if bad else None})

    on_target = [s for s in sites if s["mm"] == 0 and s["pam"]]
    no_pam = [s for s in sites if s["mm"] == 0 and not s["pam"]]
    far = [s for s in sites if s["mm"] and s["pam"] and s["near"] > SEED]
    near = [s for s in sites if s["mm"] and s["pam"] and s["near"] <= SEED]

    assert len(on_target) == 1, "there must be exactly one intended site"
    assert no_pam, "a perfect match with no PAM is the whole point of the first slide"
    assert far, "an off-target that does get cut is what makes the risk concrete"
    assert near, "a near-PAM mismatch that is refused is what the seed rule teaches"


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


def _render_lead_video(lead: dict) -> str:
    """Render the lead's video block through the real edition template."""
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    import build_site

    env = Environment(
        loader=FileSystemLoader(build_site.TEMPLATE_DIR),
        autoescape=select_autoescape(["html", "j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    src = (build_site.TEMPLATE_DIR / "edition.html.j2").read_text(encoding="utf-8")
    start = src.index("{% if edition.lead.video")
    end = src.index("</figure>", start)
    end = src.index("{% endif %}", end) + len("{% endif %}")
    return env.from_string(src[start:end]).render(edition={"lead": lead})


def test_a_lead_without_video_renders_no_iframe():
    html = _render_lead_video({"headline": "כותרת"})
    assert "<iframe" not in html


def test_a_lead_video_embeds_through_the_nocookie_host():
    """The lead got its own video block after the grid had one for months. It
    must obey the same two rules, or the privacy and performance guarantees hold
    only on the half of the page nobody looks at first."""
    html = _render_lead_video({
        "headline": "כותרת",
        "video": {
            "youtube_id": "CHjdtTROPZg",
            "caption": "כיתוב",
            "credit": "NotebookLM",
        },
    })
    assert "youtube-nocookie.com/embed/CHjdtTROPZg" in html
    assert "www.youtube.com/embed" not in html
    assert 'loading="lazy"' in html
    assert "כיתוב" in html and "NotebookLM" in html


def test_a_lead_video_without_an_id_is_ignored_rather_than_rendered_broken():
    html = _render_lead_video({"headline": "כותרת",
                               "video": {"caption": "אין מזהה"}})
    assert "<iframe" not in html
    assert "אין מזהה" not in html


def test_every_video_in_every_edition_declares_a_credit():
    """An embed is a quotation. It carries its publisher, like any other source.
    Checked across every edition on disk, including ones not yet due: tonight is
    the last chance to catch it. The lead is walked too, because a video there is
    the most prominent thing on the page and the easiest place to forget."""
    for path in ALL_EDITIONS:
        edition = json.loads(path.read_text(encoding="utf-8"))
        carriers = [edition.get("lead") or {}]
        for section in edition.get("grid", []):
            carriers.extend(section.get("stories", []))
        for carrier in carriers:
            video = carrier.get("video")
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
    """The reader sees the built page, not the data file.

    This used to strip <script> blocks before looking, which is precisely where
    the one real offender was hiding: a simulator wrote an em dash straight into
    an output cell on every topic page, and both the data check and this test
    reported clean. style.check_rendered reads script string literals too,
    because a literal that lands in textContent is prose."""
    import style

    problems = []
    for page in style.rendered_pages():
        problems += style.check_rendered(page)
    assert problems == [], problems


def test_rendered_check_reads_inside_script_literals(tmp_path):
    """The guard above is only worth having if it looks where the bug was."""
    import style

    page = tmp_path / "sim.html"
    page.write_text(
        "<p>טקסט תקין</p><script>\n"
        "  // הערה עם — שאיש אינו רואה\n"
        "  el.textContent = lambda === 193 ? '\u2014' : '\u00d7' + passes;\n"
        "</script>",
        encoding="utf-8",
    )
    problems = style.check_rendered(page)
    assert any("em dash" in p for p in problems), problems
    assert all("הערה" not in p for p in problems), "a comment is not prose"


def test_rendered_check_allows_rtl_navigation_and_chart_ranges():
    """Arrows and en dashes are correct typography here, not tells."""
    import style

    assert style.check_string("למהדורה של היום \u2190", "nav", style.RENDERED_SKIP) == []
    assert style.check_string("0 \u2013 ", "axis", style.RENDERED_SKIP) == []


# ---------------------------------------------------------------------------
# Simulator wiring
#
# The simulators are hand-written JavaScript that reaches into the page by id.
# document.getElementById returns null for a name that does not exist, and the
# usual next line is el.textContent = ..., which throws and kills the rest of
# that simulator. Nothing in the build notices: validate.py reads data, style.py
# reads prose, and the page still renders with a dead control panel on it.
#
# This is the BKM section 11 trap wearing different clothes. The check runs
# against the template rather than the built pages on purpose, so a simulator
# belonging to an edition that has not been published yet is covered too.
_SCRIPT_RE = re.compile(r"<script\b[^>]*>(.*?)</script>", re.S | re.I)
_IIFE_OPEN = re.compile(r"\(function\s*\(\s*\)\s*\{")
_GET_BY_ID = re.compile(r"getElementById\(\s*'([^']+)'\s*\)")
_QUERY_CLASS = re.compile(r"querySelectorAll?\(\s*'\.([A-Za-z0-9_-]+)'")
_ID_ATTR = re.compile(r'\bid="([^"]+)"')
_CLASS_ATTR = re.compile(r'\bclass="([^"]+)"')
_JINJA = re.compile(r"\{\{.*?\}\}|\{%.*?%\}", re.S)
_JS_LINE_COMMENT = re.compile(r"(?<![:'\"])//[^\n]*")
_JS_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_JS_STRING = re.compile(r"'(?:[^'\\\n]|\\.)*'|\"(?:[^\"\\\n]|\\.)*\"")


def _iife_bodies(js):
    """Yield each (function () { ... }) body by matching braces.

    Comments and string literals are blanked first, so a brace inside Hebrew
    prose cannot throw the depth count off."""
    clean = _JS_BLOCK_COMMENT.sub(lambda m: " " * len(m.group(0)), js)
    clean = _JS_LINE_COMMENT.sub(lambda m: " " * len(m.group(0)), clean)
    clean = _JS_STRING.sub(lambda m: "'" + " " * (len(m.group(0)) - 2) + "'", clean)
    for m in _IIFE_OPEN.finditer(clean):
        depth = 0
        for i in range(m.end() - 1, len(clean)):
            if clean[i] == "{":
                depth += 1
            elif clean[i] == "}":
                depth -= 1
                if depth == 0:
                    yield js[m.end():i]
                    break


def _declared_targets(template_text):
    """Ids and classes the markup declares, with Jinja holes as wildcards.

    An id written id="in-{{ c.key }}" really does exist at run time under every
    key the data supplies, so it becomes the pattern in-.+ rather than a literal."""
    markup = _SCRIPT_RE.sub(" ", template_text)
    ids, patterns, classes = set(), [], set()
    for value in _ID_ATTR.findall(markup):
        if _JINJA.search(value):
            patterns.append(re.compile("^" + ".+".join(
                re.escape(part) for part in _JINJA.split(value)) + "$"))
        else:
            ids.add(value)
    for value in _CLASS_ATTR.findall(markup):
        classes.update(_JINJA.sub(" ", value).split())
    return ids, patterns, classes


def _unresolved_references(template_text):
    ids, patterns, classes = _declared_targets(template_text)
    problems, checked = [], 0
    for block in _SCRIPT_RE.findall(template_text):
        for body in _iife_bodies(block):
            for ref in sorted(set(_GET_BY_ID.findall(body))):
                checked += 1
                if ref not in ids and not any(p.match(ref) for p in patterns):
                    problems.append(f"getElementById('{ref}') matches no id in the markup")
            for cls in sorted(set(_QUERY_CLASS.findall(body))):
                checked += 1
                if cls not in classes:
                    problems.append(f"querySelector('.{cls}') matches no class in the markup")
    return checked, problems


def test_every_simulator_element_reference_resolves():
    """A simulator that reaches for an element that is not there dies silently."""
    text = (ROOT / "templates" / "topic.html.j2").read_text(encoding="utf-8")
    checked, problems = _unresolved_references(text)
    assert checked > 50, f"only {checked} references found; this guard looks nowhere"
    assert problems == [], problems


def test_simulator_reference_check_catches_a_renamed_element():
    """The guard above passes on real data, so prove it can fail."""
    text = (ROOT / "templates" / "topic.html.j2").read_text(encoding="utf-8")
    broken = text.replace("getElementById('op-channel-state')",
                          "getElementById('op-channel-stat')")
    assert broken != text, "the element this fixture renames is gone; repoint it"
    _, problems = _unresolved_references(broken)
    assert any("op-channel-stat'" in p for p in problems), problems


def test_simulator_reference_check_accepts_jinja_built_ids():
    """id="in-{{ c.key }}" is a real element, not a missing one."""
    markup = '<input id="in-{{ c.key }}"><b class="euv-source-btn{% if x %} is-active{% endif %}">'
    script = ("<script>(function () { var a = document.getElementById('in-mag');"
              " var b = document.querySelectorAll('.euv-source-btn'); }());</script>")
    checked, problems = _unresolved_references(markup + script)
    assert checked == 2
    assert problems == [], problems


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


COUNTER_SRC = "https://babook.co.il/counter/c.js"
COUNTER_KEY = 'data-site="c6b824abd1"'


def _served_pages() -> list[Path]:
    return [p for p in [
        ROOT / "index.html", ROOT / "archive.html",
        ROOT / "learn.html", ROOT / "search.html",
        *(ROOT / "editions").glob("*.html"),
        *(ROOT / "learn").glob("*.html"),
    ] if p.exists()]


def test_every_served_page_carries_the_visitor_tracking_script():
    pages = _served_pages()
    assert len(pages) > 5, "site does not look built"
    for page in pages:
        html = page.read_text(encoding="utf-8")
        where = page.relative_to(ROOT)
        assert COUNTER_SRC in html, f"{where} has no tracking script"
        assert COUNTER_KEY in html, f"{where} carries the script without a site key"
        # The script fills the counter elements the moment it runs, so it has
        # to run after the document is parsed. async would race the DOM.
        assert f'<script defer src="{COUNTER_SRC}"' in html, (
            f"{where} must load the counter with defer, not async")


def test_the_visible_counter_appears_once_and_only_on_the_front_page():
    front = (ROOT / "index.html").read_text(encoding="utf-8")
    assert front.count('id="site-counter"') == 1, "front page counter is missing or duplicated"
    assert front.count('data-counter-scope="site"') == 1, (
        "the printed number must be the site-wide total, asked for exactly once")
    assert 'id="site-counter-box" hidden' in front, (
        "the counter line must start hidden so an unreachable counter prints nothing")
    assert "MutationObserver" in front, (
        "something has to reveal the line once a real number lands in it")
    # Checking only for the word is not enough: it survives in the capability
    # test even when the reveal is gone. Assert the three parts that do the work.
    assert "new MutationObserver" in front, "the observer is never constructed"
    assert ".observe(out" in front, "the observer never watches the counter element"
    assert "box.hidden = false" in front, "nothing ever unhides the line"
    for page in _served_pages():
        if page.name == "index.html":
            continue
        html = page.read_text(encoding="utf-8")
        assert "data-counter" not in html, (
            f"{page.relative_to(ROOT)} shows a visible count; it belongs only on the front page")


def test_research_pdf_source_is_not_tracked():
    # research.html.j2 is printed to PDF by headless Chromium, never served.
    text = (ROOT / "templates" / "research.html.j2").read_text(encoding="utf-8")
    assert "babook" not in text and "_analytics" not in text, (
        "the research document is a PDF source; a remote tracker there blocks printing")


def test_no_trace_of_the_retired_counter_remains():
    """GoatCounter was replaced. A second tracker left wired into the templates
    would keep sending pageviews to an account nobody reads, and the stale
    visible counter would print a number from the wrong source."""
    for path in sorted((ROOT / "templates").glob("*.j2")):
        text = path.read_text(encoding="utf-8")
        assert "goatcounter" not in text.lower(), f"{path.name} still loads GoatCounter"
        assert "gc.zgo.at" not in text, f"{path.name} still loads the GoatCounter library"
    for page in _served_pages():
        html = page.read_text(encoding="utf-8")
        assert "goatcounter" not in html.lower(), (
            f"{page.relative_to(ROOT)} is stale; rebuild the site")


def _site_fingerprint() -> dict[str, str]:    files = [        ROOT / "index.html", ROOT / "archive.html", ROOT / "learn.html",
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


# --------------------------------------------------------------------------
# פודקאסט
# --------------------------------------------------------------------------

import podcast  # noqa: E402


def _script(*lines: str) -> list[tuple[str, str]]:
    return [(s, t) for s, t in (ln.split(": ", 1) for ln in lines)]


def test_podcast_script_parses_both_hosts(tmp_path):
    """A turn is 'NAME: text'. Anything else is a stage direction the model was
    told not to write, and speaking it aloud would be absurd."""
    p = tmp_path / "2026-01-01.script.md"
    p.write_text(
        "<!-- draft header -->\n\n"
        f"{podcast.HOST_A}: שאלה ראשונה.\n\n"
        f"{podcast.HOST_B}: תשובה ראשונה.\n",
        encoding="utf-8")
    turns = podcast.parse_script(p)
    assert [s for s, _ in turns] == [podcast.HOST_A, podcast.HOST_B]
    assert turns[0][1] == "שאלה ראשונה."


def test_podcast_wrapped_line_joins_the_turn_above(tmp_path):
    """An editor rewrapping the script by hand must not silently drop half a
    sentence. A line with no speaker belongs to the turn before it."""
    p = tmp_path / "2026-01-01.script.md"
    p.write_text(f"{podcast.HOST_A}: התחלה\nוההמשך.\n\n{podcast.HOST_B}: כן.\n",
                 encoding="utf-8")
    turns = podcast.parse_script(p)
    assert turns[0][1] == "התחלה וההמשך."
    assert len(turns) == 2


def test_podcast_rejects_a_single_speaker(tmp_path):
    p = tmp_path / "2026-01-01.script.md"
    p.write_text(f"{podcast.HOST_A}: לבד.\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        podcast.parse_script(p)


def test_podcast_chunks_never_split_a_turn():
    """Chunks are separate TTS calls joined end to end. Splitting mid-turn would
    put an audio seam inside a sentence."""
    turns = _script(*[f"{podcast.HOST_A if i % 2 else podcast.HOST_B}: "
                      + "מילה " * 40 for i in range(12)])
    blocks = podcast.chunk(turns, limit=600)
    assert len(blocks) > 1, "the fixture is too small to exercise chunking"
    rejoined = "\n".join(blocks)
    for speaker, text in turns:
        assert f"{speaker}: {text}" in rejoined, "a turn was cut in half"


def test_podcast_oversized_turn_is_passed_through_whole():
    """A single turn longer than the limit must still be spoken, not dropped."""
    long_turn = _script(f"{podcast.HOST_A}: " + "מילה " * 500)
    blocks = podcast.chunk(long_turn, limit=100)
    assert len(blocks) == 1 and blocks[0].startswith(podcast.HOST_A)


def test_podcast_script_obeys_the_paper_voice(tmp_path):
    """The style rules are enforced before recording, not after. A voice tell is
    worse spoken than written, and re-rendering audio costs money."""
    p = tmp_path / "2026-01-01.script.md"
    p.write_text(f"{podcast.HOST_A}: חשוב לציין שזה נכון.\n\n"
                 f"{podcast.HOST_B}: כן.\n", encoding="utf-8")
    turns = podcast.parse_script(p)
    with pytest.raises(SystemExit):
        podcast.check_voice(turns, p)


def test_podcast_audio_reader_survives_a_reshaped_response():
    """The REST response shape is not contractual, so the audio is found by
    walking the document. Both known shapes must work."""
    blob = "QUJDRA==" * 100
    flat = {"output_audio": {"data": blob}}
    nested = {"steps": [{"content": [{"type": "audio", "data": blob}]}]}
    assert podcast._collect_audio(flat) == [blob]
    assert podcast._collect_audio(nested) == [blob]
    assert podcast._collect_audio({"id": "resp_1", "status": "completed"}) == []


def test_podcast_brief_has_its_markers():
    """podcast.py reads only what sits between the markers, and a brief without
    them would silently send an empty instruction."""
    text = (ROOT / "prompts" / "podcast.md").read_text(encoding="utf-8-sig")
    assert "---BRIEF---" in text and "---END BRIEF---" in text
    body = text.split("---BRIEF---", 1)[1].split("---END BRIEF---", 1)[0]
    assert podcast.HOST_A in body and podcast.HOST_B in body, \
        "the brief must name the same two hosts podcast.py parses"


@pytest.mark.parametrize("path", ALL_EDITIONS, ids=lambda p: p.stem)
def test_declared_podcast_is_reachable(path):
    """A podcast block renders a player. It must point at something that plays:
    the local file while the episode is recent, the release archive once it has
    been pruned. Requiring the local file unconditionally would have broken
    every old edition thirty days after the first episode.

    An episode hosted on someone else's site is a link instead, because an
    <audio> element cannot play a web page."""
    ed = json.loads(path.read_text(encoding="utf-8-sig"))
    pod = ed.get("podcast")
    if not pod:
        pytest.skip("no podcast for this edition")
    assert bool(pod.get("file")) != bool(pod.get("link")), \
        "a podcast is either hosted here or elsewhere, never both and never neither"
    if pod.get("link"):
        assert pod["link"].startswith("https://")
        assert pod.get("duration"), "a linked episode still states its length"
        return
    assert pod["file"] == f"audio/{ed['date']}.mp3"
    assert (ROOT / pod["file"]).exists() or pod.get("archive_url"), \
        f"{pod['file']} is gone and there is no archive_url to fall back to"


def test_podcast_key_matches_what_the_recorder_writes():
    """The player read `podcast.src` for two editions while podcast.py wrote
    `podcast.file`, so a recorded episode would have rendered no player at all
    and said nothing about it. The three places that touch this block have to
    agree on the key, and only a test keeps them agreeing."""
    template = (ROOT / "templates" / "edition.html.j2").read_text(encoding="utf-8")
    recorder = (ROOT / "scripts" / "podcast.py").read_text(encoding="utf-8")
    assert '"file"' in recorder, "podcast.py no longer writes a 'file' key"
    assert "pod.src" not in template and "podcast.src" not in template, \
        "the template reads a podcast key that nothing writes"
    assert "pod.file" in template, "the template no longer renders the hosted episode"
    assert "pod.link" in template, "the template no longer renders a linked episode"


def test_linked_episode_validates_and_exclusivity_is_enforced(tmp_path):
    """An episode hosted elsewhere is legal. Both forms at once is not."""
    base = {"date": "2020-01-01", "number": 1, "compiled_at": "2020-01-01T00:00:00"}

    ed = dict(base, podcast={"link": "https://notebook.google.com/x", "duration": "44:25"})
    errors: list[str] = []
    validate.check_edition(ed, tmp_path / "2020-01-01.json", {}, errors)
    assert not [e for e in errors if "podcast" in e], f"a linked episode was rejected: {errors}"

    ed = dict(base, podcast={"link": "https://notebook.google.com/x",
                             "file": "audio/2020-01-01.mp3", "duration": "44:25"})
    errors = []
    validate.check_edition(ed, tmp_path / "2020-01-01.json", {}, errors)
    assert [e for e in errors if "podcast" in e], "file and link together must be rejected"

    ed = dict(base, podcast={"link": "notebook.google.com/x", "duration": "44:25"})
    errors = []
    validate.check_edition(ed, tmp_path / "2020-01-01.json", {}, errors)
    assert [e for e in errors if "podcast" in e], "a relative podcast link must be rejected"


def test_placeholder_check_matches_whole_words_only(tmp_path):
    """A substring scan for 'TODO' rejects 'Mathstodon', which is the real
    name of the server a brief about Terence Tao had to cite. The guard has to
    catch a half-written edition without censoring an ordinary proper noun."""
    base = {"date": "2020-01-01", "number": 1, "compiled_at": "2020-01-01T00:00:00"}

    ed = dict(base, grid=[{"name": "n", "stories": [{
        "headline": "h", "summary": "s", "source": "טרנס טאו, Mathstodon",
        "time": "10:00", "url": "https://mathstodon.xyz/@tao/1"}]}])
    errors: list[str] = []
    validate.check_edition(ed, tmp_path / "2020-01-01.json", {}, errors)
    assert not [e for e in errors if "placeholder" in e], \
        f"'Mathstodon' was read as a TODO marker: {errors}"

    ed = dict(base, grid=[{"name": "n", "stories": [{
        "headline": "TODO: write this", "summary": "s", "source": "x",
        "time": "10:00", "url": "https://example.com/"}]}])
    errors = []
    validate.check_edition(ed, tmp_path / "2020-01-01.json", {}, errors)
    assert [e for e in errors if "placeholder" in e], \
        "a real TODO marker slipped through the relaxed check"


def test_lead_art_is_credited_and_local(tmp_path):
    """The paper draws its own diagrams, so a raster image is always somebody
    else's work. Printing one without a credit, or hotlinking it from another
    site, are both failures the validator has to catch rather than the reader."""
    base = {"date": "2020-01-01", "number": 1, "compiled_at": "2020-01-01T00:00:00"}
    good = {"src": "assets/img/2026-09-06-metacognition.webp", "alt": "a",
            "caption": "b", "credit": "c", "width": 2000, "height": 1116}

    errors: list[str] = []
    validate.check_edition(dict(base, lead=dict(good, image=dict(good))),
                           tmp_path / "x.json", {}, errors)
    assert not [e for e in errors if "lead.image" in e], errors

    for missing in ("alt", "caption", "credit", "width", "height"):
        art = {k: v for k, v in good.items() if k != missing}
        errors = []
        validate.check_edition(dict(base, lead={"image": art}), tmp_path / "x.json", {}, errors)
        assert [e for e in errors if missing in e], f"a lead image with no {missing} was accepted"

    errors = []
    validate.check_edition(
        dict(base, lead={"image": dict(good, src="https://example.com/a.png")}),
        tmp_path / "x.json", {}, errors)
    assert [e for e in errors if "remote" in e], "a hotlinked lead image was accepted"


def test_e_topic_matches_the_numbers_it_prints():
    """The `e` page states values for the limit and the series. They are easy to
    mistype and impossible for a reader to catch, so they are checked here
    against the arithmetic rather than trusted."""
    topic = json.loads((ROOT / "data" / "topics" / "e.json").read_text(encoding="utf-8"))
    text = json.dumps(topic, ensure_ascii=False)

    assert f"{math.e:.7f}" == "2.7182818"
    for n, shown in ((2, "2.25"), (12, "2.6130"), (365, "2.7146")):
        assert f"{(1 + 1 / n) ** n:.4f}".startswith(shown[:6]), n
        assert shown in text, f"the page no longer prints {shown} for n={n}"

    series = sum(1 / math.factorial(k) for k in range(10))
    assert f"{series:.7f}" == "2.7182815"
    assert "2.7182815" in text, "the ten-term series value is printed"
    assert f"{(1 + 1 / 10 ** 6) ** 10 ** 6:.7f}" == "2.7182805"
    assert "2.7182805" in text, "the million-division limit value is printed"

    assert f"{1 / math.e * 100:.1f}" == "36.8" and "36.8%" in text
    assert f"{(1 - 1 / math.e) * 100:.1f}" == "63.2" and "63.2%" in text
    assert f"{math.log(2):.3f}" == "0.693" and "0.693" in text


def test_e_topic_simulator_and_diagrams_are_rendered():
    """A topic can name a sim or diagram type the template has never heard of,
    and the page then renders a heading with nothing under it. Every type a
    topic asks for must have a branch in the template."""
    template = (ROOT / "templates" / "topic.html.j2").read_text(encoding="utf-8")
    for path in sorted((ROOT / "data" / "topics").glob("*.json")):
        topic = json.loads(path.read_text(encoding="utf-8"))
        sim = (topic.get("sim") or {}).get("type")
        if sim:
            assert f"'{sim}'" in template, f"{path.stem}: no template branch for sim '{sim}'"
        for sec in topic.get("sections") or []:
            dia = (sec.get("diagram") or {}).get("type")
            if dia:
                assert f"'{dia}'" in template, \
                    f"{path.stem}: no template branch for diagram '{dia}'"


def test_complex_numbers_topic_matches_the_numbers_it_prints():
    """Every value on the complex-numbers page is recomputed here rather than
    trusted, per BKM 13. The page argues that multiplication adds angles and
    multiplies magnitudes, so a mistyped angle would not just be a typo, it
    would refute the paragraph around it."""
    topic = json.loads(
        (ROOT / "data" / "topics" / "complex-numbers.json").read_text(encoding="utf-8"))
    text = json.dumps(topic, ensure_ascii=False)

    a, b = complex(3, 2), complex(1, 1)
    assert f"{abs(a):.3f}" == "3.606" and "3.606" in text
    assert f"{math.degrees(cmath.phase(a)):.2f}" == "33.69" and "33.69" in text
    assert f"{abs(b):.3f}" == "1.414" and "1.414" in text
    assert a * b == complex(1, 5) and "1+5i" in text
    assert f"{abs(a * b):.3f}" == "5.099" and "5.099" in text
    assert f"{math.degrees(cmath.phase(a * b)):.2f}" == "78.69" and "78.69" in text

    # The angles really do add and the magnitudes really do multiply. If this
    # ever fails the page is not wrong, arithmetic is.
    assert math.isclose(math.degrees(cmath.phase(a)) + 45.0,
                        math.degrees(cmath.phase(a * b)))
    assert math.isclose(abs(a) * abs(b), abs(a * b))

    rotated = complex(0, 1) * a
    assert rotated == complex(-2, 3), "multiplying 3+2i by i gives -2+3i"
    assert f"{math.degrees(cmath.phase(rotated)):.2f}" == "123.69" and "123.69" in text
    assert math.isclose(abs(rotated), abs(a)), "a pure rotation must not change size"

    # x³ = 15x + 4 is the example that forced the issue in 1572. Both halves of
    # the claim are checked: that 4 solves it, and that (2+i)³ is 2+11i.
    assert 4 ** 3 == 15 * 4 + 4
    assert complex(2, 1) ** 3 == complex(2, 11)
    assert complex(2, 1) + complex(2, -1) == 4

    # The impedance worked example, shared with the lead article.
    w = 2 * math.pi * 100
    z = 100 + 1 / (1j * w * 10e-6)
    assert f"{z.imag:.1f}" == "-159.2" and "159.2" in text
    assert f"{abs(z):.1f}" == "188.0" and "188.0" in text
    assert f"{math.degrees(cmath.phase(z)):.1f}" == "-57.9" and "57.9" in text
    assert f"{w:.1f}" == "628.3" and "628.3" in text

    # The Nyquist peak of a parallel RC sits at R/2 - jR/2, at f = 1/(2 pi RC).
    peak = 1 / (2 * math.pi * 100 * 10e-6)
    assert f"{peak:.2f}" == "159.15" and "159.15" in text
    zp = 100 / (1 + 1j * 2 * math.pi * peak * 100 * 10e-6)
    assert (round(zp.real), round(zp.imag)) == (50, -50) and "50 מינוס 50i" in text

    assert 1000 / 50 / 4 == 5, "a quarter cycle at 50 Hz is 5 ms"


def test_agent_cost_lead_matches_the_numbers_it_derives():
    """BKM 13. The 2026-10-09 lead quotes figures from arXiv:2604.22750v3, but
    several numbers on the page are the paper's own arithmetic rather than
    anything the paper prints. No reader can catch a wrong one, because the
    page is the only place they appear. They are recomputed here.

    The 50x correction is the point of the article's seventh paragraph: the
    paper says output tokens are priced about 80x cache reads, and Anthropic's
    list price for the model the paper says it used gives 50x."""
    ed = json.loads(
        (ROOT / "data" / "editions" / "2026-10-09.json").read_text(encoding="utf-8"))
    text = json.dumps(ed, ensure_ascii=False)

    # Tokens per task, figure 1: reasoning query, chat turn, agent task.
    reasoning, chat, agent = 1190, 3390, 4_170_000
    assert round(agent / reasoning) == 3504 and "3,504" in text
    assert round(agent / chat) == 1230 and "1,230" in text

    # The paper's abstract rounds both of those to "1000x". The page says so,
    # and the claim is only honest if the two ratios really do straddle it.
    assert agent / chat < 1000 * 2 < agent / reasoning

    # Output price vs cache-read price, Claude Sonnet 4.5 list price.
    assert 15.0 / 0.30 == 50 and "הוא 50" in text

    # Phase shares, figure 8. They are a partition, so they must sum to 100,
    # and the figure rounds each one.
    phases = [9.98, 30.37, 33.53, 16.59, 9.53]
    assert round(sum(phases), 2) == 100.00
    assert round(phases[1] + phases[2], 2) == 63.90 and "63.9" in text

    bars = [b["value"] for b in ed["lead"]["figure"]["bars"]]
    assert bars == [round(p) for p in phases], \
        "the figure must round the paper's phase shares, not restate them"
    assert ed["lead"]["figure"]["max"] >= max(bars)

    # "About 150 read for every one written" paraphrases the 153.85 ratio.
    assert round(153.85 / 10) * 10 == 150 and "כ-150" in text

    # Prediction overhead, figure 11b: both Sonnet 3.7 and Sonnet 4 charge more
    # than the task itself merely to guess what the task will cost.
    assert 2.29 > 1 and 2.09 > 1 and "2.29" in text and "2.09" in text


def test_credit_spread_lead_matches_the_numbers_it_derives():
    """BKM 13. The 2026-10-16 lead quotes two anchor percentages from FRED and
    then does arithmetic on them. The gap, the ratio, the three-month rise and
    its percentage are the paper's own, and so is the CPI rate in the inflation
    brief, which is computed from two index levels rather than quoted. A reader
    cannot catch a wrong one, because the paper is where they first appear."""
    ed = json.loads(
        (ROOT / "data" / "editions" / "2026-10-16.json").read_text(encoding="utf-8"))
    text = json.dumps(ed, ensure_ascii=False)

    # The two quoted anchors, 13 October 2026, and their basis-point form.
    broad_pct, ccc_pct = 3.16, 12.67
    broad, ccc = round(broad_pct * 100), round(ccc_pct * 100)
    assert (broad, ccc) == (316, 1267)
    assert "3.16" in text and "12.67" in text
    assert "316 נקודות בסיס" in text and "1,267 נקודות בסיס" in text

    # The gap, printed as a round number of basis points.
    assert ccc - broad == 951 and "951 נקודות" in text

    # "כמעט פי ארבעה" is a ratio the paper never prints as a figure, so the
    # word has to keep being true: just over four, and under four and a half.
    assert 4.0 < ccc / broad < 4.5
    assert round(ccc / broad, 2) == 4.01 and "כמעט פי ארבעה" in text

    # End of June to 13 October: the rise, and the percentage of it.
    june = 970
    assert "970 נקודות" in text
    assert ccc - june == 297 and "297 נקודות" in text
    assert round(100 * (ccc - june) / june, 1) == 30.6, "the rise is 30.6%"
    assert "כ-31 אחוזים" in text, "which the paper rounds to about 31"

    # The figure restates the three spreads it was built from, and nothing else.
    bars = [b["value"] for b in ed["lead"]["figure"]["bars"]]
    assert bars == [ccc, june, broad]
    assert ed["lead"]["figure"]["max"] >= max(bars)

    # The broad spread is far below both reference crises the paper names.
    assert broad < 1000 < 2000

    # CPI, computed from the BLS index levels the brief prints rather than
    # quoted from a report. The headline rounds to one decimal, the body to two.
    sep26, sep25 = 336.940, 324.800
    assert round(100 * (sep26 / sep25 - 1), 2) == 3.74 and "3.74 אחוזים" in text
    assert round(100 * (sep26 / sep25 - 1), 1) == 3.7 and "3.7 אחוזים" in text
    assert "336.940" in text and "324.800" in text


def test_human_economic_value_lead_matches_the_numbers_it_derives():
    """BKM 13. The 2026-10-13 lead's headline number, 42.4, is not quoted from
    anywhere. It is the output of a three-factor model that the research
    document states in prose, and the paper is the only place a reader sees it.
    So the whole scenario table is recomputed here from the stated assumptions.

    The one deliberate mismatch is in the record: the source document prints
    81.2 for almost-full automation in 2030 where the arithmetic gives 81.25,
    rounding down instead of up. The paper does not print that cell, but the
    recomputation has to keep reproducing it or the model has drifted."""
    ed = json.loads(
        (ROOT / "data" / "editions" / "2026-10-13.json").read_text(encoding="utf-8"))
    text = json.dumps(ed, ensure_ascii=False)

    def remaining(exposed, saved, returned):
        """Paid human labour demand, as a percent of a world without AI."""
        return 100 * (1 - exposed * saved * (1 - returned))

    # exposure, share saved, share returned by new demand -> printed result
    scenarios = {
        ("historical", 2030): (0.35, 0.20, 0.70, 97.9),
        ("historical", 2040): (0.55, 0.40, 0.65, 92.3),
        ("historical", 2055): (0.70, 0.55, 0.60, 84.6),
        ("ninety", 2030): (0.40, 0.35, 0.40, 91.6),
        ("ninety", 2040): (0.65, 0.70, 0.30, 68.2),
        ("ninety", 2055): (0.80, 0.90, 0.20, 42.4),
        ("near-total", 2030): (0.50, 0.50, 0.25, 81.2),
        ("near-total", 2040): (0.80, 0.90, 0.15, 38.8),
        ("near-total", 2055): (0.95, 0.98, 0.05, 11.6),
    }
    for key, (exposed, saved, returned, printed) in scenarios.items():
        got = remaining(exposed, saved, returned)
        if key == ("near-total", 2030):
            assert round(got, 2) == 81.25, "the source rounds 81.25 down to 81.2"
            continue
        assert round(got, 1) == printed, f"{key}: computed {got}, table says {printed}"

    # The headline. The point of the article is the gap between the assumption
    # people hear, 90% taken, and what the model actually yields.
    assert round(remaining(0.80, 0.90, 0.20), 1) == 42.4 and "42.4" in text
    assert round(100 - 42.4, 1) == 57.6 and "57.6" in text
    assert remaining(0.80, 0.90, 0.20) > 4 * 10, \
        "the lead's whole claim is that 90% assumed does not give 10% remaining"

    # The figure shows the three 2055 columns, and must not restate them.
    bars = [b["value"] for b in ed["lead"]["figure"]["bars"]]
    assert bars == [84.6, 42.4, 11.6]
    assert ed["lead"]["figure"]["max"] >= max(bars)

    # The scenarios have to be ordered, or the table is not a spectrum.
    by_2055 = [scenarios[(k, 2055)][3] for k in ("historical", "ninety", "near-total")]
    assert by_2055 == sorted(by_2055, reverse=True)

    # The demand arithmetic the article states in words: tenfold productivity
    # needs tenfold demand merely to hold employment flat.
    assert 1 / (1 / 10) == 10, "productivity x10 requires demand x10 to hold headcount"

    # ILO Working Paper 140. Quoted, not derived, but 3.3 was printed as 3.4 in
    # a first draft and nothing caught it.
    assert "3.3 אחוזים" in text and "3.4 אחוזים" not in text


def test_complex_plane_diagram_uses_one_scale_on_both_axes():
    """A diagram that labels an angle has to be drawn to scale, or it prints a
    number the picture contradicts. The first draft of this figure used 70
    pixels per unit across and 45 down, which drew 33.69 degrees as 27, and
    nothing in the build noticed. Geometry that carries a claim gets pinned."""
    template = (ROOT / "templates" / "topic.html.j2").read_text(encoding="utf-8")
    block = template.split("'complex-plane-point'")[1].split("{% endif %}")[0]

    ox, oy = 120.0, 220.0
    m = re.search(r'<circle cx="([\d.]+)" cy="([\d.]+)" r="5"', block)
    assert m, "the point marking 3+2i is gone from the diagram"
    px, py = float(m.group(1)), float(m.group(2))

    across, down = (px - ox) / 3.0, (oy - py) / 2.0
    assert math.isclose(across, down), \
        f"the axes are drawn at different scales ({across} vs {down} px per unit)"

    drawn = math.degrees(math.atan2(oy - py, px - ox))
    assert abs(drawn - 33.69) < 0.05, \
        f"the figure draws {drawn:.2f} degrees but labels it 33.69"


def test_a_lead_that_cites_research_needs_a_verification_note(tmp_path, monkeypatch):
    """Deep research is trusted as a source, but not blindly: whatever the lead
    prints from it must have been read at its own source first, and that reading
    has to be written down.

    This replaced `check_research_sealed`, a two-model adversarial seal that was
    gated on an edition key no edition ever set, so it never once ran. A rule
    that cannot fire is worse than no rule, because it reads as enforcement. The
    day this one was added it caught two real plans, including the edition that
    had shipped the night before."""
    monkeypatch.setattr(validate, "PLAN_DIR", tmp_path)
    ed = {"date": "2020-01-01", "number": 1, "compiled_at": "2020-01-01T00:00:00",
          "lead": {"url": "research/2020-01-01.pdf"}, "grid": []}
    plan = {"edition_date": "2020-01-01", "briefs": [],
            "lead": {"topic": "t", "question": "q"}}

    def run():
        (tmp_path / "2020-01-01.plan.json").write_text(
            json.dumps(plan, ensure_ascii=False), encoding="utf-8")
        errors: list[str] = []
        validate.check_plan(ed, tmp_path / "2020-01-01.json", errors)
        return [e for e in errors if "lead.verified" in e]

    assert run(), "a lead citing research with no verification note was accepted"

    plan["lead"]["verified"] = ""
    assert run(), "an empty verification note must not count as a check"

    plan["lead"]["verified"] = "read the three claims at their own sources"
    assert not run(), "a verified lead was rejected"

    # A lead with no research PDF is an ordinary piece and needs no note.
    ed["lead"] = {"headline": "x"}
    plan["lead"].pop("verified")
    assert not run(), "a lead that cites no research must not require a note"


def test_every_lead_citing_research_records_what_was_checked():
    """The rule above, applied to the real plans rather than a fixture."""
    for path in sorted((ROOT / "data" / "editions").glob("*.json")):
        ed = json.loads(path.read_text(encoding="utf-8-sig"))
        if not (ed.get("lead") or {}).get("url"):
            continue
        plan = json.loads(
            (ROOT / "data" / "plans" / f"{ed['date']}.plan.json").read_text(encoding="utf-8"))
        note = (plan.get("lead") or {}).get("verified") or ""
        assert len(note.strip()) > 80, \
            f"{ed['date']}: lead.verified is missing or too thin to be a real record"


def test_the_dead_seal_gate_is_gone():
    """`check_research_sealed` never ran, because nothing ever set the edition
    key it was gated on. It was removed rather than left in place looking like a
    guarantee. If it comes back it must come back wired up."""
    src = (ROOT / "scripts" / "validate.py").read_text(encoding="utf-8")
    assert "def check_research_sealed" not in src, \
        "the seal gate is back. Wire it to a key editions actually set, or drop it"


def test_bkm_cross_references_point_at_sections_that_exist():
    """The docs lean on each other by number: "BKM §10", "RUNBOOK section 7".
    Numbered references rot the first time a section is inserted or renumbered,
    and a reader chasing a wrong pointer trusts the docs a little less every
    time. Cheap to check, so it is checked."""
    bkm = (ROOT / "docs" / "BKM.md").read_text(encoding="utf-8")
    runbook = (ROOT / "docs" / "RUNBOOK.md").read_text(encoding="utf-8")
    sections = {
        "BKM": {int(n) for n in re.findall(r"^## (\d+)\.", bkm, re.M)},
        "RUNBOOK": {int(n) for n in re.findall(r"^## (\d+)\.", runbook, re.M)},
    }
    assert sections["BKM"] and sections["RUNBOOK"], "no numbered sections found"

    pattern = re.compile(r"\b(BKM|RUNBOOK)[^.\n]{0,20}?(?:§|section )\s*(\d+)", re.I)
    docs = [ROOT / "AGENTS.md", ROOT / "docs" / "BKM.md",
            ROOT / "docs" / "RUNBOOK.md", ROOT / "docs" / "SPEC.md",
            ROOT / "docs" / "VISUAL_SPEC.md"]
    for path in docs:
        if not path.exists():
            continue
        for doc, num in pattern.findall(path.read_text(encoding="utf-8")):
            key = doc.upper()
            assert int(num) in sections[key], \
                f"{path.name} points at {key} §{num}, which does not exist"


def test_jekyll_is_disabled_and_markdown_cannot_break_the_deploy():
    """GitHub Pages ran Jekyll over this repository, and Jekyll expands Liquid
    in every markdown file it finds. BKM section 11 quoted a Jinja tag, Liquid
    read it as its own, and the deploy went red while every other check stayed
    green. The site is pre-built HTML, so Jekyll should never run at all."""
    assert (ROOT / ".nojekyll").exists(), \
        ".nojekyll is missing: Pages will run Jekyll over the repo again"

    stray = []
    for path in ROOT.rglob("*.md"):
        if any(p in {".git", ".venv", "node_modules"} for p in path.parts):
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"\{%.*?%\}", line):
                stray.append(f"{path.relative_to(ROOT)}:{n}")
    assert not stray, (
        "markdown contains Liquid/Jinja tags that Jekyll would try to execute: "
        + ", ".join(stray)
    )


def test_pruned_episode_still_validates(tmp_path, monkeypatch):
    """The retention window deletes local audio on purpose. validate.py must
    accept that, or the first prune takes the whole site down."""
    ed = {
        "date": "2020-01-01", "number": 1, "compiled_at": "2020-01-01T00:00:00",
        "podcast": {"file": "audio/2020-01-01.mp3", "duration": "9:12",
                    "archive_url": "https://github.com/o/r/releases/download/podcasts/2020-01-01.mp3"},
    }
    errors: list[str] = []
    validate.check_edition(ed, tmp_path / "2020-01-01.json", {}, errors)
    assert not [e for e in errors if "podcast" in e], \
        f"an archived episode was rejected: {errors}"

    ed["podcast"].pop("archive_url")
    errors = []
    validate.check_edition(ed, tmp_path / "2020-01-01.json", {}, errors)
    assert [e for e in errors if "podcast" in e], \
        "an episode with no local file and no archive URL must be rejected"


def test_local_audio_is_pruned_to_the_retention_window():
    """Audio is the only thing in this repository that grows without bound.
    Recent episodes live here; the rest live in the release archive."""
    files = list((ROOT / "audio").glob("*.mp3")) if (ROOT / "audio").exists() else []
    assert len(files) <= podcast.KEEP_LOCAL, (
        f"{len(files)} episodes in audio/, over the {podcast.KEEP_LOCAL} kept. "
        "Run: python scripts\\podcast.py --prune")


@pytest.mark.parametrize("path", EDITIONS, ids=lambda p: p.stem)
def test_a_published_correction_reaches_the_page(path: Path):
    """BKM 11: Jinja renders nothing for a key the template does not read, so a
    correction could sit in the data and never appear in print. This walks the
    real editions rather than a fixture, because a fixture would still pass if
    the template block were deleted tomorrow."""
    edition = json.loads(path.read_text(encoding="utf-8"))
    correction = edition.get("lead", {}).get("correction")
    if not correction:
        return

    page = (ROOT / "editions" / f"{path.stem}.html").read_text(encoding="utf-8")
    for para in correction["body"]:
        assert para[:40] in page, (
            f"{path.stem} carries a correction whose text never reached the page - "
            "the template is not rendering lead.correction"
        )
    assert correction["date"] in page, "the correction is printed without its date"


def test_the_correction_template_block_still_exists():
    """The sibling of the walking test above: it would fall silent the day the
    last correction is removed from the data, so the block is asserted directly."""
    template = (ROOT / "templates" / "edition.html.j2").read_text(encoding="utf-8")
    assert "lead.correction" in template, "the template no longer renders a correction"
    assert "correction__text" in template, "the correction body is no longer printed"


def test_the_alga_really_is_twenty_times_faster_than_the_eye():
    """BKM 13: 'פי עשרים' is the paper's own arithmetic, not a quoted figure.

    The Nobel background gives two measurements and never multiplies them: the
    impulse in Chlamydomonas appeared 0.5 ms after the light, and the chemical
    chain in the human eye takes at least 10 ms. The ratio is ours, it is printed
    three times across the topic page and the edition, and no reader can check
    it. If either source number is ever corrected, this fails rather than the
    paper quietly keeping a wrong multiple."""
    alga_ms, eye_ms = 0.5, 10.0
    assert eye_ms / alga_ms == 20

    topic = (ROOT / "data" / "topics" / "optogenetics.json").read_text(encoding="utf-8")
    edition = (ROOT / "data" / "editions" / "2026-10-08.json").read_text(encoding="utf-8")

    assert "חצי אלפית שנייה" in topic, "the 0.5 ms measurement is no longer printed"
    assert "עשר אלפיות שנייה" in topic, "the 10 ms comparison is no longer printed"
    for name, text in (("topic", topic), ("edition", edition)):
        assert "פי עשרים" in text, f"the {name} no longer prints the derived multiple"
        assert "פי עשר" not in text.replace("פי עשרים", ""), (
            f"the {name} prints a different multiple than 10 / 0.5"
        )


def test_the_lowest_frequency_costs_the_time_the_article_claims():
    """BKM 13: the paper derives this one rather than quoting it, so no reader
    can catch it. One cycle at the bottom of the window is 1/f seconds."""
    seconds = 1 / 1e-3
    assert seconds == 1000
    minutes = seconds / 60
    assert 16.6 < minutes < 16.7, minutes

    edition = json.loads(
        (ROOT / "data" / "editions" / "2026-09-07.json").read_text(encoding="utf-8")
    )
    body = " ".join(edition["lead"]["body"])
    assert "אלף שניות" in body, "the article no longer prints the period it derives"
    assert "שבע עשרה דקות" in body, (
        "the article prints a different figure than 1000 s rounds to"
    )


import research_doc  # noqa: E402


def _own_documents() -> list[Path]:
    return sorted((ROOT / "data" / "research").glob("*.doc.json"))


@pytest.mark.parametrize("path", _own_documents(), ids=lambda p: p.stem)
def test_the_papers_own_document_is_what_gets_published(path: Path):
    """BKM 16: the received deep-research PDF is an input, not the reference.
    build_site.publish_research copies data/research/<date>-*.pdf into research/,
    and before this guard existed it would have silently overwritten the paper's
    own document on the very next build. The received file is still on disk, so
    this walks the real state rather than a fixture."""
    edition_date = path.stem.replace(".doc", "")
    published = ROOT / "research" / f"{edition_date}.pdf"
    assert published.exists(), (
        f"{edition_date} has its own reference document but nothing is published. "
        f"Run: python scripts/research_doc.py {edition_date}"
    )

    received = sorted((ROOT / "data" / "research").glob(f"{edition_date}-*.pdf"))
    if not received:
        return
    assert published.read_bytes() != received[0].read_bytes(), (
        f"research/{edition_date}.pdf is byte-identical to the received "
        f"{received[0].name}. The received PDF has overwritten the paper's own "
        f"reference document - see build_site.publish_research"
    )


@pytest.mark.parametrize("path", _own_documents(), ids=lambda p: p.stem)
def test_the_byline_counts_match_the_document_it_describes(path: Path):
    """BKM 13: pages and words are derived, printed, and unfalsifiable by a
    reader. They were hand-typed once and went stale the moment the document was
    rewritten. Recompute both from the artifacts themselves."""
    edition_date = path.stem.replace(".doc", "")
    edition_file = ROOT / "data" / "editions" / f"{edition_date}.json"
    if not edition_file.exists():
        return

    doc = json.loads(path.read_text(encoding="utf-8"))
    words = research_doc.count_words(doc)
    pages = research_doc.page_count(ROOT / "research" / f"{edition_date}.pdf")

    source = json.loads(edition_file.read_text(encoding="utf-8"))["lead"]["source"]
    assert f"{pages} עמודים" in source, (
        f"byline claims something other than the {pages} pages actually in "
        f"research/{edition_date}.pdf: {source!r}"
    )
    assert f"{words:,} מילים" in source, (
        f"byline claims something other than the {words:,} words actually in "
        f"{path.name}: {source!r}"
    )


def test_the_reference_document_says_what_it_rejected():
    """A document that corrects its source has to show its working, or the
    correction is just an assertion. Every own-document carries a provenance
    block and a section listing what was dropped."""
    for path in _own_documents():
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert doc.get("provenance", {}).get("body"), (
            f"{path.name} has no provenance block - a reader cannot tell what "
            f"this document is or how it relates to what was handed in"
        )
        headings = " ".join(s["heading"] for s in doc["sections"])
        assert "נדחה" in headings or "גבולות" in headings, (
            f"{path.name} never says what it rejected or what it could not "
            f"verify. Both belong in the document, not only in the plan."
        )


def test_every_diagram_and_sim_type_has_a_template_branch():
    """Jinja does not raise on a value it has no branch for. A topic naming a
    diagram or a simulator the template never dispatches on renders an empty
    space, and the page ships looking fine. BKM section 11."""
    tpl = (ROOT / "templates" / "topic.html.j2").read_text(encoding="utf-8")
    diagram_branches = set(re.findall(r"sec\.diagram\.type == '([a-z0-9-]+)'", tpl))
    sim_branches = set(re.findall(r"topic\.sim\.type == '([a-z0-9-]+)'", tpl))

    assert diagram_branches, "the diagram dispatch is gone; this guard looks nowhere"
    assert sim_branches, "the simulator dispatch is gone; this guard looks nowhere"

    for path in TOPICS:
        topic = json.loads(path.read_text(encoding="utf-8"))
        sim = topic.get("sim")
        if sim:
            assert sim["type"] in sim_branches, (
                f"{path.name} asks for simulator {sim['type']!r}, which the template "
                f"has no branch for, so it would render nothing. "
                f"Known: {sorted(sim_branches)}"
            )
        for sec in topic["sections"]:
            diagram = sec.get("diagram")
            if diagram:
                assert diagram["type"] in diagram_branches, (
                    f"{path.name} asks for diagram {diagram['type']!r}, which the "
                    f"template has no branch for. Known: {sorted(diagram_branches)}"
                )


def test_radiocarbon_topic_matches_the_numbers_it_derives():
    """BKM 13. Nothing in the radiocarbon learning page is quoted. Every
    percentage on it is the output of 0.5 ** (t / 5730), computed here and
    printed there, which means the page is the only place a reader meets the
    number and no reader can catch a wrong one. So they get recomputed.

    The page's whole argument rests on one of these: that the same hundred
    years of real age produce a measurable signal at two thousand years and
    almost none at twenty thousand. If the ratio drifts, the argument is
    wrong even when every sentence around it still reads fine."""
    HALF_LIFE = 5730

    def left(t):
        """Fraction of the original carbon 14 still present after t years."""
        return 100 * 0.5 ** (t / HALF_LIFE)

    topic = json.loads(
        (ROOT / "data" / "topics" / "radiocarbon-dating.json").read_text(encoding="utf-8"))
    text = json.dumps(topic, ensure_ascii=False)

    # The practical floor. Nine half-lives is where the page says the method
    # stops, and the "under two per mille" phrasing depends on this value.
    assert 9 * HALF_LIFE == 51570 and "51,570" in text
    assert round(left(51570), 3) == 0.195 and "0.195" in text
    assert left(51570) < 0.2, "the page calls this under two per mille"

    # The signal-shrink comparison, which is the section's entire point.
    young, young_older = left(2000), left(2100)
    old, old_older = left(20000), left(20100)
    assert round(young, 1) == 78.5 and "78.5" in text
    assert round(young_older, 1) == 77.6 and "77.6" in text
    assert round(old, 2) == 8.90 and "8.90" in text
    assert round(old_older, 2) == 8.79 and "8.79" in text

    young_drop = young - young_older
    old_drop = old - old_older
    assert round(young_drop, 2) == 0.94
    assert round(old_drop, 2) == 0.11
    assert round(young_drop / old_drop) == 9 and "פי תשעה" in text, \
        "the page says the same hundred years move the reading nine times less"

    # The decay curve in the template is plotted, not stated, so the mapping
    # that drew it is pinned too: x = 470 - 430 * (t / 57300), y = 250 - 2*pct.
    svg = (ROOT / "templates" / "topic.html.j2").read_text(encoding="utf-8")
    curve = re.search(
        r"carbon14-decay-curve.*?<polyline class=\"diagram__curve\" points=\"([^\"]+)\"",
        svg, re.S)
    assert curve, "the decay-curve branch lost its polyline"
    points = [tuple(float(v) for v in p.split(",")) for p in curve.group(1).split()]
    assert len(points) == 101
    for i, (x, y) in enumerate(points):
        t = 57300 * i / 100
        assert x == round(470 - 430 * (t / 57300), 1), f"point {i} x drifted"
        assert y == round(250 - 2 * left(t), 1), f"point {i} y drifted"

    # The half-life tick marks under the axis are multiples, not guesses.
    for n, label in ((1, "5,730"), (3, "17,190"), (5, "28,650"), (7, "40,110")):
        assert str(f"{n * HALF_LIFE:,}") == label and label in svg


def _sound_absorption_db_per_m(f_hz, temp_k=293.15, rel_humidity=50.0, pressure_pa=101325.0):
    """Atmospheric absorption of sound, ISO 9613-1. Returns dB per metre.

    The bat page quotes no absorption figure from anywhere. It prints the
    output of this function, so the function lives here as well and the two
    have to agree."""
    t0, t01 = 293.15, 273.16
    pr = 101325.0
    psat = pr * 10 ** (-6.8346 * (t01 / temp_k) ** 1.261 + 4.6151)
    h = rel_humidity * (psat / pressure_pa)
    fr_o = (pressure_pa / pr) * (24 + 4.04e4 * h * (0.02 + h) / (0.391 + h))
    fr_n = (pressure_pa / pr) * (temp_k / t0) ** -0.5 * (
        9 + 280 * h * math.exp(-4.170 * ((temp_k / t0) ** (-1 / 3) - 1)))
    f2 = f_hz * f_hz
    return 8.686 * f2 * (
        1.84e-11 * (pr / pressure_pa) * (temp_k / t0) ** 0.5
        + (temp_k / t0) ** -2.5 * (
            0.01275 * math.exp(-2239.1 / temp_k) / (fr_o + f2 / fr_o)
            + 0.1068 * math.exp(-3352.0 / temp_k) / (fr_n + f2 / fr_n)))


def test_bat_echolocation_topic_matches_the_numbers_it_derives():
    """BKM 13. Almost nothing on the bat page is quoted from anywhere.

    The distances, the wavelengths, the attenuation percentages, the call
    intervals and the Doppler shift are all outputs of three formulas run
    against one constant, the speed of sound at 20 C. A reader meets those
    numbers only on this page, so no reader can catch a wrong one. They get
    recomputed here, including the coordinates of the plotted curve, because a
    polyline that drifts away from the prose it illustrates still looks like a
    graph."""
    C = 343.0  # m/s at 20 C, the figure the page states it computes from

    def distance(t_ms):
        """Round trip: the wave covered the gap twice."""
        return C * (t_ms / 1000.0) / 2

    def echo_ms(d_m):
        return 2 * d_m / C * 1000.0

    def wavelength_mm(f_khz):
        return C / (f_khz * 1000.0) * 1000.0

    topic = json.loads(
        (ROOT / "data" / "topics" / "bat-echolocation.json").read_text(encoding="utf-8"))
    text = json.dumps(topic, ensure_ascii=False)
    svg = (ROOT / "templates" / "topic.html.j2").read_text(encoding="utf-8")
    roundtrip = re.search(r"bat-echo-roundtrip.*?</svg>", svg, re.S).group(0)
    waves = re.search(r"sonar-wavelength-resolution.*?</svg>", svg, re.S).group(0)
    attenuation = re.search(r"sonar-attenuation-range.*?</svg>", svg, re.S).group(0)
    hunt = re.search(r"bat-hunt-call-rate.*?</svg>", svg, re.S).group(0)

    assert "343 מטר לשנייה" in text, "the page has to state the constant it computes from"
    assert text.count("343 מטר לשנייה") == 4
    assert roundtrip.count("343") == 1

    # d = c * t / 2. Every pair the page prints, in both directions. The counts
    # matter: these numbers appear more than once, and one stale copy is enough
    # to make the page wrong while every other sentence still reads fine.
    assert round(distance(6), 3) == 1.029
    assert text.count("1.029 מטר") == 2 and text.count("1.029 m") == 1
    assert roundtrip.count("1.029 מטר") == 1 and roundtrip.count("0.006") == 1
    assert round(distance(12), 3) == 2.058 and text.count("2.058 מטר") == 2
    assert round(distance(30), 3) == 5.145 and text.count("5.145 מטר") == 1
    assert round(distance(12), 3) == round(2 * distance(6), 3), \
        "double the time is double the distance, and the quiz leans on it"
    assert round(C * 0.012, 3) == 4.116 and text.count("4.116 מטר") == 2, \
        "the quiz offers the undivided answer as the trap"
    assert round(echo_ms(1), 2) == 5.83 and text.count("5.83 אלפיות") == 1
    assert round(echo_ms(5), 2) == 29.15 and text.count("29.15 אלפיות") == 1

    # lambda = c / f. The resolution argument is nothing but this.
    assert round(wavelength_mm(20), 2) == 17.15
    assert text.count("17.15 מילימטר") == 2 and waves.count("17.15 מילימטר") == 1
    assert round(wavelength_mm(50), 2) == 6.86
    assert text.count("6.86 מילימטר") == 4 and waves.count("6.86 מילימטר") == 1
    assert round(wavelength_mm(100), 2) == 3.43
    assert text.count("3.43 מילימטר") == 1 and waves.count("3.43 מילימטר") == 1
    assert round(wavelength_mm(12.7), 2) == 27.01 and text.count("27.01 מילימטר") == 1, \
        "the low-frequency bat pays in wavelength, and the page says how much"
    assert round(wavelength_mm(50)) == 7, "the page calls this about seven millimetres"
    assert round(wavelength_mm(20) / 7, 2) == 2.45
    assert text.count("פי 2.45") == 2 and waves.count("פי 2.45") == 1

    # The drawn waves are scaled at 6 px per millimetre, half-period per arc,
    # alternating sweep flags. Every arc is counted, not just the first.
    for f_khz, half, arcs in ((20, 51.45, 6), (50, 20.58, 14), (100, 10.29, 28)):
        assert round(wavelength_mm(f_khz) * 6 / 2, 3) == half
        quarter = round(half / 2, 3)
        assert quarter == {20: 25.725, 50: 10.29, 100: 5.145}[f_khz]
        for flag in (0, 1):
            arc = f"a {quarter:g} 16 0 0 {flag} -{half:g} 0"
            assert waves.count(arc) == arcs // 2, f"{f_khz} kHz wave lost an arc"

    # Atmospheric absorption. 20 C, 50% relative humidity, standard pressure.
    a25 = _sound_absorption_db_per_m(25_000)
    a100 = _sound_absorption_db_per_m(100_000)

    def remains(alpha, d_m):
        return 100 * 10 ** (-alpha * d_m / 10)

    assert round(remains(a25, 4), 1) == 51.0
    assert text.count("51.0 אחוזים") == 3 and attenuation.count("51.0%") == 1
    assert round(remains(a100, 4), 1) == 4.9
    assert text.count("4.9 אחוזים") == 3 and attenuation.count("4.9%") == 1
    assert round(remains(a25, 10), 1) == 18.6 and text.count("18.6 אחוזים") == 1
    assert remains(a100, 10) < 0.1, "the page calls this under a tenth of a per cent"
    assert round(remains(a25, 8), 1) == 26.0 and attenuation.count("26.0%") == 1
    assert round(remains(a100, 2), 1) == 22.1 and attenuation.count("22.1%") == 1

    # The curves are plotted, not stated: x = 470 - 43*d, y = 250 - 2*percent.
    curves = re.findall(r"points=\"([^\"]+)\"", attenuation)
    assert len(curves) == 2, "the attenuation branch lost a curve"
    for alpha, raw in zip((a25, a100), curves):
        points = [tuple(float(v) for v in p.split(",")) for p in raw.split()]
        assert len(points) == 51
        for i, (x, y) in enumerate(points):
            d = i * 10 / 50
            assert x == round(470 - 430 * (d / 10), 1), f"point {i} x drifted"
            assert y == round(250 - 2 * remains(alpha, d), 1), f"point {i} y drifted"

    # The marked dots sit on those same curves, not near them.
    for cx, cy, alpha, d in (("298", "148", a25, 4), ("126", "198", a25, 8),
                             ("384", "206", a100, 2), ("298", "240", a100, 4)):
        assert round(470 - 43 * d) == int(cx)
        assert round(250 - 2 * remains(alpha, d)) == int(cy)
        assert f'<circle cx="{cx}" cy="{cy}"' in attenuation

    # Call rate. The interval is not a style choice, it is the round trip.
    assert round(1000 / 10) == 100 and text.count("100 אלפיות שנייה") == 2
    assert hunt.count("100 אלפיות שנייה") == 1
    assert round(distance(100), 2) == 17.15
    assert text.count("17.15 מטרים") == 2 and hunt.count("17.15 מטרים") == 1
    assert round(echo_ms(2), 2) == 11.66 and text.count("11.66 אלפיות") == 1
    assert round(1000 / 85, 2) == 11.76 and hunt.count("11.76 אלפיות") == 1, \
        "the prose rounds the echo at two metres, the diagram labels the interval"
    assert math.floor(1 / (2 * 2 / C)) == 85 and text.count("85 קריאות") == 1, \
        "85 calls per second is the most that fits without overrunning the echo"
    assert round(1000 / 200) == 5 and text.count("5 אלפיות שנייה") == 3
    assert hunt.count("5 אלפיות שנייה") == 1 and text.count("200 קריאות") == 2
    assert round(distance(5) * 100) == 86
    assert text.count("86 סנטימטרים") == 2 and hunt.count("86 סנטימטרים") == 1

    # The pulse combs are the same arithmetic drawn: 410 px span = 300 ms.
    for interval, baseline, count in ((100.0, 86, 4), (1000 / 85, 170, 26), (5.0, 254, 61)):
        xs = re.findall(rf'<line x1="([\d.]+)" y1="{baseline - 22}" ', hunt)
        assert len(xs) == count, f"the {interval:.2f} ms comb has the wrong pulse count"
        for k, x in enumerate(xs):
            assert float(x) == round(470 - (410 / 300) * k * interval, 1)

    # Doppler, stationary listener, approaching source of the echo.
    f_echo = 50_000 * (C + 5) / (C - 5)
    assert round(f_echo) == 51479 and text.count("51,479 הרץ") == 2
    assert round(f_echo - 50_000) == 1479 and text.count("כ-1,479 הרץ") == 3

    # The simulator has to run the same physics as the page, not its own.
    sim = re.search(r"סונאר של עטלף.*?\}\)\(\);", svg, re.S).group(0)
    assert "var C = 343;" in sim
    assert "6.8346" in sim and "4.6151" in sim and "4.04e4" in sim and "8.686" in sim, \
        "the simulator must use the same ISO 9613-1 absorption as the curve"
    assert "2 * d / C" in sim and "C / (fkHz * 1000)" in sim
    # The 60 dB two-way budget, split in half for the one-way distance.
    assert round(30 / _sound_absorption_db_per_m(50_000), 1) == 18.1
    assert "BUDGET = 60" in sim and "(BUDGET / 2) / alphaDbPerM" in sim


def test_no_svg_label_relies_on_a_text_anchor_attribute():
    """A text-anchor attribute on a diagram label is a lie, and an expensive one.

    The stylesheet sets text-anchor on .diagram__label (start) and on
    .diagram__axis-label (middle), and a CSS rule always beats a presentation
    attribute. So every text-anchor="end" written into the template for three
    months did nothing at all. Labels got positioned against an anchor that
    was never applied, and eight Hebrew labels across four published learning
    pages were running outside their own viewBox and being clipped: the
    optogenetics legend lost 141 units of text off the right edge, and
    "כ-2% מקודדים חלבון" on the genome ruler ran 94 units off the left.

    A getBBox sweep in a browser is the only thing that sees the clipping, and
    it is not available here. What is available is the cause, so that is what
    is guarded: write the position against the anchor the stylesheet actually
    applies, and never against an attribute that is silently discarded."""
    css = (ROOT / "assets" / "css" / "newspaper.css").read_text(encoding="utf-8")
    for cls in ("diagram__label", "diagram__axis-label"):
        rule = re.search(rf"\.{cls}\s*\{{(.*?)\}}", css, re.S)
        assert rule and "text-anchor" in rule.group(1), (
            f".{cls} no longer sets text-anchor in CSS. If that is deliberate, "
            f"the attributes become live again and this test should go"
        )

    for path in sorted((ROOT / "templates").glob("*.j2")):
        src = path.read_text(encoding="utf-8")
        for m in re.finditer(r"<(?:text|tspan)\b[^>]*>", src):
            tag = m.group(0)
            if "text-anchor=" not in tag or "diagram__" not in tag:
                continue
            line = src[:m.start()].count("\n") + 1
            raise AssertionError(
                f"{path.name}:{line} sets a text-anchor attribute on a diagram "
                f"label. CSS overrides it, so the label will not sit where the "
                f"attribute says. Position it against the CSS anchor instead "
                f"(.diagram__label is start, which in RTL is the right edge; "
                f".diagram__axis-label is middle). Tag: {tag[:120]}"
            )
