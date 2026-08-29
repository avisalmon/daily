"""Regression tests for the newspaper.

Every test here exists because something actually went wrong. Adding one is the
last step of fixing an editorial or rendering bug — see docs/RUNBOOK.md §5.

    pytest -q
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import ledger  # noqa: E402
import validate  # noqa: E402
import weather  # noqa: E402

CSS = ROOT / "assets" / "css" / "newspaper.css"
EDITIONS = sorted((ROOT / "data" / "editions").glob("*.json"))
TOPICS = sorted((ROOT / "data" / "topics").glob("*.json"))


# --------------------------------------------------------------------------
# The contract in docs/SPEC.md holds for real data.
# --------------------------------------------------------------------------

def test_all_published_data_validates():
    assert validate.validate() == []


def test_there_is_at_least_one_edition():
    assert EDITIONS, "no editions on disk"


# --------------------------------------------------------------------------
# Encoding. PowerShell silently rewrote docs/SPEC.md as cp1252 once and turned
# every Hebrew word into mojibake. Nothing shipped may contain it again.
# --------------------------------------------------------------------------

TEXT_FILES = [
    *EDITIONS,
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
    for path in EDITIONS:
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
    for path in EDITIONS:
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


@pytest.mark.parametrize("path", TOPICS, ids=lambda p: p.stem)
def test_every_topic_has_a_rendered_page(path: Path):
    topic = json.loads(path.read_text(encoding="utf-8"))
    page = ROOT / "learn" / f"{topic['slug']}.html"
    assert page.exists(), f"{topic['slug']} has no rendered page - run build_site.py"


@pytest.mark.parametrize("path", EDITIONS, ids=lambda p: p.stem)
def test_edition_links_to_its_topic_page_and_the_catalog(path: Path):
    """The learning block silently dropped its link once: the template asked for
    `learning.url` while the data carried `learning.slug`."""
    ed = json.loads(path.read_text(encoding="utf-8"))
    slug = (ed.get("learning") or {}).get("slug")
    if not slug:
        pytest.skip("edition has no learning topic")
    for page in (ROOT / "index.html", ROOT / "editions" / f"{ed['date']}.html"):
        html = page.read_text(encoding="utf-8")
        if ed["date"] not in html:
            continue
        assert f"{slug}.html" in html, f"{page.name} does not link to the topic page"
        assert "learn.html" in html, f"{page.name} does not link to the catalog"


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

# --------------------------------------------------------------------------
# The research bank: a pool of undated deep researches.
# --------------------------------------------------------------------------

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


def test_claimed_bank_research_is_on_disk_for_its_edition():
    import research_bank

    for item in research_bank.load()["items"]:
        if not item.get("used_in"):
            continue
        expected = ROOT / "data" / "research" / f"{item['used_in']}-{item['id']}.pdf"
        assert expected.exists(), f"{item['id']} claims {item['used_in']} but {expected.name} is gone"


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


def test_build_is_reproducible():
    """Building twice in a row must succeed - it is run every single day."""
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build_site.py")],
        capture_output=True, text=True, encoding="utf-8", cwd=ROOT,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
