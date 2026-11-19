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
# The newsroom has to actually produce.
#
# Between 19 October and 11 November 2026 the hourly publish job ran green
# every hour of every day while the site served a three-week-old paper. Three
# editorial meetings had run and written their plans; no edition was ever
# built. Nothing in the repository noticed, because publish.py is a promoter
# and not a writer: with no new edition on disk it correctly finds nothing to
# do, reports success, and exits 0.
#
# A green workflow over a stale paper is worse than a red one. It answers the
# only question the reader actually asks, "is this today's paper", with the
# wrong answer, and it answers it 24 times a day.
# --------------------------------------------------------------------------

STALE_AFTER_DAYS = 7


def newsroom_gap_days(edition_dates: list[date], today: date) -> int:
    """How many days behind `today` the newest edition *written* is.

    Measured against editions on disk rather than editions published, so a
    paper written tonight for tomorrow counts as fresh: the newsroom is
    working even though nothing has been promoted to the front page yet.
    """
    if not edition_dates:
        return 10**6
    return max(0, (today - max(edition_dates)).days)


def test_the_paper_is_not_stale():
    gap = newsroom_gap_days([date.fromisoformat(p.stem) for p in ALL_EDITIONS], paper_today())
    assert gap <= STALE_AFTER_DAYS, (
        f"the newest edition on disk is {gap} days old, and the publish job "
        f"will go on reporting success anyway, because it promotes editions "
        f"and does not write them. A plan in data/plans/ is a decision, not an "
        f"edition. Run the editorial meeting, then build."
    )


def test_newsroom_gap_counts_tomorrows_paper_as_fresh():
    assert newsroom_gap_days([date(2026, 11, 12)], date(2026, 11, 11)) == 0


def test_newsroom_gap_measures_the_newest_not_the_count():
    dates = [date(2026, 1, 1), date(2026, 11, 4), date(2026, 2, 2)]
    assert newsroom_gap_days(dates, date(2026, 11, 11)) == 7


def test_newsroom_gap_would_have_caught_the_october_silence():
    """The real incident, pinned: on 11 November the newest edition was 19 October."""
    assert newsroom_gap_days([date(2026, 10, 19)], date(2026, 11, 11)) == 23
    assert 23 > STALE_AFTER_DAYS, "the threshold no longer catches the case it was written for"


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
def test_a_held_back_edition_actually_publishes_on_its_day(path: Path, monkeypatch):
    """The sibling above proves tomorrow's paper is invisible tonight. That is
    only half the promise: a paper that is invisible tonight and still invisible
    tomorrow is a paper nobody reads, and nobody is at the keyboard at midnight
    to notice.

    So rehearse the promotion rather than reason about it. Move the paper's
    clock to the edition's own date, run the real build, and look at the front
    page. Then rebuild plainly in a finally, because every other test in this
    file reads the built site off disk and must not find a preview there."""
    ed = json.loads(path.read_text(encoding="utf-8"))
    date_str = ed["date"]
    try:
        monkeypatch.setattr(build_site, "paper_today",
                            lambda: date.fromisoformat(date_str))
        build_site.build()

        index = (ROOT / "index.html").read_text(encoding="utf-8")
        assert ed["lead"]["headline"] in index, (
            f"{date_str} arrived and the front page still does not carry its lead")
        assert (ROOT / "editions" / f"{date_str}.html").exists(), (
            f"{date_str} arrived and its edition page was not rendered")
        assert date_str in (ROOT / "archive.html").read_text(encoding="utf-8"), (
            f"{date_str} arrived and the archive does not link it")

        # A learning topic pinned to this edition is held back with it, so it
        # has to arrive with it too. gps.html shipped dark once for this reason.
        for topic in (ROOT / "data" / "topics").glob("*.json"):
            if json.loads(topic.read_text(encoding="utf-8")).get("edition") != date_str:
                continue
            assert (ROOT / "learn" / f"{topic.stem}.html").exists(), (
                f"{topic.stem} is pinned to {date_str} but did not publish with it")
            assert f"{topic.stem}.html" in (ROOT / "learn.html").read_text(encoding="utf-8"), (
                f"{topic.stem} published but is not listed on the learning index")
    finally:
        monkeypatch.undo()
        build_site.build()


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


def test_delta_v_matches_the_numbers_in_the_article():
    """No reader can catch a wrong derived number, because the paper is the
    source. Edition 18's learning page is arithmetic end to end, so every
    figure it prints is recomputed here."""
    import math

    # Climbing 100 km is cheap. Reaching orbital speed is not.
    climb = 9.81 * 100_000                      # J/kg
    speed = 0.5 * 7800 ** 2                     # J/kg
    assert round(climb / 1000) == 981           # 981 kJ/kg
    assert round(speed / 1e6, 2) == 30.42       # 30.42 MJ/kg
    assert round(speed / climb, 2) == 31.01     # the article's "pi 31"
    assert round(100 * speed / (speed + climb), 1) == 96.9
    assert round(100 * climb / (speed + climb), 1) == 3.1

    # Tsiolkovsky at the standard LEO budget on kerosene and oxygen.
    mr = math.exp(9.4 / 3.3)
    assert round(mr, 2) == 17.26
    prop = 1 - 1 / mr
    assert round(prop * 100, 1) == 94.2

    # The simulator's payoff: with 8 percent structure the payload is negative,
    # so a single stage of this kind cannot reach orbit even empty.
    payload = 1 - prop - 0.08
    assert payload < 0
    assert round(payload * 100, 1) == -2.2

    # Splitting the same budget over two stages needs a far gentler ratio.
    assert round(math.exp(4.7 / 3.3), 1) == 4.2

    # The closing comparison: the energy itself is worth a few shekels.
    assert round(speed / 3.6e6, 2) == 8.45      # kWh per kg


def test_dwarf_planet_topic_matches_the_numbers_it_derives():
    """Edition 19's learning page computes the orbit-clearing parameter itself
    and prints the results as fact. Every derived figure in the text, the
    table and the simulator's defaults is rebuilt here from the inputs the
    page names: NASA fact sheets, JPL SBDB, and the Stern-Levison form with
    the constant that reproduces the accepted value for Earth."""
    import json
    import math
    import re

    EARTH = 5.9722e24
    K = 1.53e5

    def lam(mass_kg, a_au):
        return K * (mass_kg / EARTH) ** 2 / a_au ** 1.5

    pluto_m, pluto_a = 0.01303e24, 39.48
    eris_m, eris_a = 1.67e22, 67.9
    ceres_m, ceres_a = 9.393e20, 2.768
    mars_m, mars_a = 0.642e24, 1.524

    # Table column "Λ (חישוב העיתון)" and the ratio the text leans on.
    assert round(lam(EARTH, 1.0)) == 153_000
    assert round(lam(mars_m, mars_a), -1) == 940
    assert round(lam(ceres_m, ceres_a), 4) == 0.0008
    assert round(lam(pluto_m, pluto_a), 4) == 0.0029
    assert round(lam(eris_m, eris_a), 4) == 0.0021
    assert round(lam(EARTH, 1.0) / lam(pluto_m, pluto_a) / 1e6) == 52

    # Table column "מסה (כדור הארץ = 1)".
    assert round(pluto_m / EARTH, 4) == 0.0022
    assert round(eris_m / EARTH, 4) == 0.0028
    assert round(ceres_m / EARTH, 5) == 0.00016
    assert round(mars_m / EARTH, 3) == 0.107
    assert round(100 * pluto_m / EARTH, 2) == 0.22

    # The thought experiments in the clearing section.
    assert round(lam(pluto_m, 1.0), 2) == 0.73
    assert round(lam(mars_m, pluto_a)) == 7
    assert round(lam(EARTH, pluto_a)) == 617
    need = math.sqrt(pluto_a ** 1.5 / K) * EARTH       # mass that clears at Pluto's a
    assert round(need / pluto_m, 1) == 18.5
    assert round(100 * need / EARTH) == 4
    # Pluto at 1 AU would need 1 / sqrt(0.73) times its mass.
    assert round(math.sqrt(1 / lam(pluto_m, 1.0)), 1) == 1.2

    # Comparisons of bodies. Eris's mass is Brown and Schaller's 1.67e22 kg;
    # Pluto's is the NASA fact sheet, not the lighter Wikipedia figure.
    assert round(eris_m / pluto_m, 2) == 1.28
    assert round(100 * (eris_m / pluto_m - 1)) == 28
    assert round(pluto_m / ceres_m) == 14

    # Periods from the quoted orbital data.
    assert round(90_560 / 365.25, 1) == 247.9
    assert round(205_000 / 365.25, -1) == 560
    assert round(103_000 / 365.25) == 282

    # The candidate, under the assumption the page states: D = 1,000 km,
    # density 2 g/cm3.
    cand_m = 2000 * (4 / 3) * math.pi * (500_000) ** 3
    assert round(cand_m / 1e21, 2) == 1.05
    assert round(lam(cand_m, 42.9), 5) == 0.00002

    # Simulator defaults land on Pluto and reproduce the article's 0.0029.
    topic_dir = ROOT / "data" / "topics"
    assert (topic_dir / "dwarf-planet.json").exists()
    html = (ROOT / "templates" / "topic.html.j2").read_text(encoding="utf-8")
    sim = html[html.index("dp-clearing"):]
    mass_default = float(re.search(r'id="dp-in-mass"[^>]*value="([-\d.]+)"', sim).group(1))
    dist_default = float(re.search(r'id="dp-in-dist"[^>]*value="([-\d.]+)"', sim).group(1))
    m_default = 10 ** mass_default
    a_default = 10 ** dist_default
    assert round(m_default, 4) == 0.0022
    assert round(a_default, 1) == 39.8
    assert round(K * m_default ** 2 / a_default ** 1.5, 4) == 0.0029
    # The Λ = 1 line is drawn through its endpoints: at 100 AU and at 0.316 AU.
    for a_au, x_px, y_px in ((100.0, 40.0, 159.1), (10 ** -0.5, 470.0, 209.1)):
        m_line = math.sqrt(a_au ** 1.5 / K)
        assert round(470 - (math.log10(a_au) + 0.5) / 2.5 * 430, 1) == x_px
        assert round(250 - (math.log10(m_line) + 4.5) / 7.5 * 200, 1) == y_px

    # The size ladder is drawn to one scale: 170 px for Earth's 12,756 km.
    scale = 170 / 12_756
    assert round(2376 * scale / 2, 1) == 15.8      # Pluto
    assert round(2400 * scale / 2, 1) == 16.0      # Eris
    assert round(3475 * scale / 2, 1) == 23.2      # Moon
    assert round(950 * scale / 2, 1) == 6.3        # Ceres
    assert round(1500 * scale / 2, 1) == 10.0      # candidate, upper bound
    assert round(600 * scale / 2, 1) == 4.0        # candidate, lower bound

    # The orbit diagram: 2.3 px per AU, perihelia and aphelia from JPL/NASA.
    S = 2.3
    assert round(30.178 * S, 1) == 69.4                                   # Neptune ring
    for a_au, e, rx, ry in ((39.48, 0.2444, 90.8, 88.1), (42.9, 0.142, 98.7, 97.7), (67.9, 0.438, 156.2, 140.4)):
        assert round(a_au * S, 1) == rx
        assert round(a_au * math.sqrt(1 - e * e) * S, 1) == ry
    assert round(39.48 * (1 - 0.2444), 2) == 29.83                        # inside Neptune's 30.18

    # The page's own words carry the same figures.
    topic = json.loads((topic_dir / "dwarf-planet.json").read_text(encoding="utf-8"))
    text = json.dumps(topic, ensure_ascii=False)
    for needle in ("0.0029", "153,000", "52 מיליון", "פי 18.5", "0.73", "617", "0.22 אחוזים", "כ-28 אחוזים", "כ-560 שנה", "כ-282 שנה", "29.65", "30.18"):
        assert needle in text, needle


def test_light_day_topic_matches_the_numbers_it_derives():
    """Edition 21's learning page converts between light-time and distance and
    prints every result as fact: the unit ladder, light times to the Moon,
    Sun, Mars, Neptune, Proxima and Andromeda, Voyager's speed ratio and the
    trip to Proxima. The paper is the only source for those, so each one is
    rebuilt here from the defined constants and the distances the page names,
    then compared with its words and with the template that draws them.
    BKM section 13."""
    import json
    import math
    import re
    from datetime import date

    C = 299_792.458                 # km/s, exact since the 1983 metre
    DAY = 86_400
    YEAR = 365.25 * DAY             # the IAU's Julian year
    AU = 149_597_870.7              # km, exact since 2012
    LD = C * DAY
    LY = C * YEAR

    # The formula lines and the unit ladder table.
    assert 299_792_458 * 86_400 == 25_902_068_371_200
    assert 299_792_458 * 31_557_600 == 9_460_730_472_580_800
    assert YEAR == 31_557_600
    assert f"{C * 60:,.2f}" == "17,987,547.48"
    assert f"{C * 3600:,.1f}" == "1,079,252,848.8"
    assert f"{LD:,.1f}" == "25,902,068,371.2"
    assert f"{LY:,.1f}" == "9,460,730,472,580.8"
    assert round(C / AU, 3) == 0.002
    assert round(C * 60 / AU, 2) == 0.12
    assert round(C * 3600 / AU, 1) == 7.2
    assert round(LD / AU, 1) == 173.1
    assert f"{LY / AU:,.0f}" == "63,241"
    assert 7.45 < C / 40_075.017 < 7.5          # "כמעט שבע וחצי הקפות"

    def light(km):
        return km / C

    # Light times in the text and the second table.
    assert round(light(384_400), 1) == 1.3
    assert round(2 * light(384_400), 1) == 2.6
    assert divmod(round(light(AU)), 60) == (8, 19)
    assert round(light(54.6e6) / 60) == 3
    assert round(light(401.4e6) / 60) == 22
    assert divmod(round(light(4.5e9) / 60), 60) == (4, 10)
    assert math.isclose(light(LD), DAY)
    assert round(4.24 * 365.25, -1) == 1550                   # Proxima in light-days

    # Voyager 1: 61,000 km/h against light, 49 years since launch, and the
    # trip to Proxima at its present speed.
    v_kms = 61_000 / 3600
    assert round(C / v_kms, -2) == 17_700
    assert int((date(2026, 11, 18) - date(1977, 9, 5)).days / 365.25) == 49
    assert round(4.24 * LY / 61_000 / (YEAR / 3600), -3) == 75_000

    # The to-scale ruler: 432.9 px for 24 light-hours, the Sun at 480.
    def ruler(hours):
        return round(480 - hours / 24 * 432.9, 1)

    html = (ROOT / "templates" / "topic.html.j2").read_text(encoding="utf-8")
    scale = html[html.index("'ld-to-scale'"):html.index("'ld-round-trip'")]
    for hours, x in ((6, 371.8), (12, 263.6), (18, 155.3), (24, 47.1)):
        assert ruler(hours) == x
        assert f'x1="{x}"' in scale
    assert ruler(light(4.5e9) / 3600) == 404.8                  # Neptune
    assert 'cx="404.8"' in scale and 'cx="47.1"' in scale

    # The simulator's log ruler: one second at 480, 440 px for 14 decades.
    sim = html[html.index("'ld-signal-delay'"):]
    sim = sim[:sim.index("</section>")]

    def log_x(seconds):
        return round(480 - math.log10(seconds) / 14 * 440, 1)

    for seconds, x in ((60, 424.1), (3600, 368.2), (DAY, 324.9), (YEAR, 244.3), (1e3 * YEAR, 150.0), (1e6 * YEAR, 55.7)):
        assert log_x(seconds) == x
        assert re.search(rf'x1="{x:g}"', sim), x
    for km, x in ((384_400, 476.6), (AU, 395.2), (4.5e9, 348.7), (LD, 324.9), (4.24 * LY, 224.6), (2.5e6 * LY, 43.2)):
        assert log_x(light(km)) == x
        assert f'cx="{x:g}"' in sim, x

    # The slider opens on Voyager and spans the Moon to past Andromeda.
    lo, hi, start = (float(re.search(rf'id="ld-in-dist"[^>]*{k}="([\d.]+)"', sim).group(1)) for k in ("min", "max", "value"))
    assert start == round(math.log10(LD), 2)
    assert lo < math.log10(384_400) and hi > math.log10(2.5e6 * LY)

    # The destinations the buttons send are the distances the page prints.
    topic = json.loads((ROOT / "data" / "topics" / "light-day.json").read_text(encoding="utf-8"))
    km = {d["label"]: d["km"] for d in topic["sim"]["destinations"]}
    assert km["הירח"] == 384_400 and km["השמש"] == AU and km["נפטון"] == 4.5e9
    assert km["מאדים, הכי קרוב"] == 54.6e6 and km["מאדים, הכי רחוק"] == 401.4e6
    assert math.isclose(km["וויאג'ר 1"], LD)
    assert math.isclose(km["פרוקסימה קנטאורי"], 4.24 * LY)
    assert math.isclose(km["אנדרומדה"], 2.5e6 * LY)
    assert [d["label"] for d in topic["sim"]["destinations"] if d.get("default")] == ["וויאג'ר 1"]

    # The page's own words carry the same figures.
    text = json.dumps(topic, ensure_ascii=False)
    for needle in ("25,902,068,371.2", "299,792.458", "17,987,547.48", "1,079,252,848.8",
                   "9,460,730,472,580.8", "173.1", "63,241", "1.3 שניות", "כ-2.6 שניות",
                   "8 דקות ו-19 שניות", "בין 3 ל-22 דקות־אור", "4 שעות ו-10 דקות",
                   "4.24 שנים", "כ-1,550 ימי־אור", "פי 17,700", "כ-75,000 שנה", "ב-49 שנים", "12:16"):
        assert needle in text, needle


def test_fpga_topic_matches_the_numbers_it_derives():
    """Edition 22's learning page counts the circuits one lookup table can
    hold, names all 16 two-input tables in its simulator, turns a path delay
    into a clock rate and a bitstream into bytes. The paper is the only source
    for those, so each is recomputed here and compared with the page's words,
    the simulator's presets and names, and the template that draws them.
    BKM section 13."""
    import json
    import re
    from datetime import date

    topic = json.loads((ROOT / "data" / "topics" / "fpga.json").read_text(encoding="utf-8"))
    text = json.dumps(topic, ensure_ascii=False)
    html = (ROOT / "templates" / "topic.html.j2").read_text(encoding="utf-8")
    sections = {s["heading"]: s for s in topic["sections"]}

    # k inputs give 2^k rows and 2^(2^k) different tables.
    for k, row in enumerate(sections["כמה מעגלים בטבלה אחת"]["table"]["rows"], start=1):
        assert row == [str(k), str(2 ** k), f"{2 ** 2 ** k:,}"], row
    assert 18 * 10 ** 18 < 2 ** 64 < 19 * 10 ** 18            # "יותר מ-18 מיליארד מיליארד"
    for needle in ("16 טבלאות שונות", "זה 65,536", "יותר מ-18 מיליארד מיליארד", "2 בחזקת 16 פונקציות"):
        assert needle in text, needle

    # Each preset is the truth table of the gate it is named after, rows 00, 01, 10, 11.
    def truth(f):
        return "".join(str(f(a, b)) for a in (0, 1) for b in (0, 1))

    gates = {"AND": lambda a, b: a & b, "OR": lambda a, b: a | b, "XOR": lambda a, b: a ^ b,
             "NAND": lambda a, b: 1 - (a & b), "NOR": lambda a, b: 1 - (a | b),
             "XNOR": lambda a, b: 1 - (a ^ b)}
    presets = topic["sim"]["presets"]
    assert {p["label"]: p["bits"] for p in presets} == {g: truth(f) for g, f in gates.items()}
    assert [p["label"] for p in presets if p.get("default")] == ["AND"]

    def spoken(g):
        return ", ".join(truth(gates[g]))

    assert f"אם בתאים כתוב {spoken('AND')}, הטבלה מתנהגת כמו AND" in text
    assert f"אם כתוב {spoken('OR')}, היא OR" in text
    assert f"אם כתוב {spoken('XOR')}, היא XOR" in text
    quiz = next(q for q in topic["quiz"] if "איזה שער היא מחקה" in q["q"])
    assert spoken("XOR") in quiz["q"] and quiz["options"][quiz["answer"]] == "XOR"

    # The static diagram shows AND, and both muxes are wired where they are drawn:
    # the select lines stop on the slanted edge, the output leaves the narrow side's middle.
    lut = html[html.index("sec.diagram.type == 'fpga-lut'"):html.index("sec.diagram.type == 'fpga-fabric'")]
    assert "".join(re.findall(r'class="fpga-cell-text">([01])<', lut)) == truth(gates["AND"])
    stage = html[html.index('id="fpga-stage"'):]
    stage = stage[:stage.index("</svg>")]
    for section in (lut, stage):
        points = re.search(r'<polygon points="([\d.,\s]+)" class="fpga-mux"/>', section).group(1)
        (xr, _), (_, yr), (xl, yl), (_, yt) = (tuple(map(float, p.split(","))) for p in points.split())
        for x in (252, 218):
            y = round(yr - (xr - x) * (yr - yl) / (xr - xl), 1)
            assert f'x2="{x}" y2="{y:g}"' in section, (x, y)
        assert f'<line x1="{xl:g}" y1="{(yl + yt) / 2:g}"' in section

    # The simulator names all 16 tables, indexed by the four bits read as a binary number.
    script = html[html.index("/* ===== FPGA:"):]
    script = script[:script.index("</script>")]
    names = re.findall(r"'([^']+)'", re.search(r"var TABLE_NAMES = \[(.*?)\];", script, re.S).group(1))
    described = {
        "תמיד 0": lambda a, b: 0, "AND": gates["AND"], "A וגם לא B": lambda a, b: a & (1 - b),
        "העתק של A": lambda a, b: a, "B וגם לא A": lambda a, b: b & (1 - a),
        "העתק של B": lambda a, b: b, "XOR": gates["XOR"], "OR": gates["OR"],
        "NOR": gates["NOR"], "XNOR": gates["XNOR"], "ההפך של B": lambda a, b: 1 - b,
        "A או לא B": lambda a, b: a | (1 - b), "ההפך של A": lambda a, b: 1 - a,
        "B או לא A": lambda a, b: b | (1 - a), "NAND": gates["NAND"], "תמיד 1": lambda a, b: 1,
    }
    assert len(names) == 16 and sorted(names) == sorted(described)
    for index, name in enumerate(names):
        assert truth(described[name]) == f"{index:04b}", name
    assert "TABLE_NAMES[parseInt(key, 2)]" in script and "var row = a * 2 + b;" in script
    assert "var ADDR = ['00', '01', '10', '11'];" in script
    assert "ארבעה ביטים נותנים 16 טבלאות אפשריות" in topic["sim"]["intro"]

    # A path delay sets the clock: Fmax = 1 / t.
    def mhz(ns):
        return 1 / (ns * 1e-9) / 1e6

    assert round(mhz(4)) == 250 and round(mhz(5)) == 200
    assert "1 / 4 ns = 250 MHz" in text and "4 ננו-שניות" in text and "250 מגה-הרץ" in text
    quiz = next(q for q in topic["quiz"] if "5 ננו-שניות" in q["q"])
    assert quiz["options"][quiz["answer"]] == "200 מגה-הרץ"

    # The critical-path diagram's example: 1.0 ns plus 0.75 ns for each table on the path.
    path = html[html.index("sec.diagram.type == 'fpga-critical-path'"):]
    path = path[:path.index("{% endif %}")]
    tables = [len(re.findall(r'class="fpga-lutbox[ "]', row)) for row in path.split('class="fpga-head')[:-1]]
    assert tables == [1, 2, 4]
    delays = [1.0 + 0.75 * n for n in tables]
    assert delays == [1.75, 2.5, 4.0]
    for d in delays:
        assert f">{d:g} ננו-שניות" in path, d
    assert round(mhz(max(delays))) == 250 and "מהיר מ-250 מגה-הרץ" in path

    # The Artix-7 bitstream in bytes, and Freeman's dates.
    assert round(30_606_304 / 8 / 1e6, 1) == 3.8
    assert "30,606,304 ביטים, כ-3.8 מיליון בייט" in text
    born, granted, died = date(1948, 7, 26), date(1989, 9, 26), date(1989, 10, 22)
    assert (died - granted).days < 30
    assert died.year - born.year - ((died.month, died.day) < (born.month, born.day)) == 41
    assert "ב-26 בספטמבר 1989, ופרימן מת פחות מחודש אחר כך, בגיל 41" in text

    # The takeaway's ranges are the two rows of the Kuon and Rose table.
    rows = sections["מחיר הגמישות"]["table"]["rows"]
    area, delay, power = ([float(r[i].replace("פי ", "")) for r in rows] for i in (1, 2, 3))
    for column, word in ((area, "גדול"), (delay, "איטי"), (power, "וצרך")):
        assert f"{word} פי {min(column):g} עד {max(column):g}" in text, word


def test_el_nino_topic_matches_the_numbers_it_derives():
    """Edition 20's learning page reads NOAA's RONI and ONI files itself and
    prints what it finds: peaks, their seasons, ranks, swings, how many
    episodes ever crossed 2.0, and the polylines of the timeline diagram.
    The paper is the only source for every one of those, so they are rebuilt
    here from the series the page carries and compared with its words, its
    table, and the template that draws them. BKM section 13."""
    import json
    import re

    SEASONS = ["DJF", "JFM", "FMA", "MAM", "AMJ", "MJJ", "JJA", "JAS", "ASO", "SON", "OND", "NDJ"]
    topic = json.loads((ROOT / "data" / "topics" / "el-nino.json").read_text(encoding="utf-8"))
    series = topic["sim"]["series"]
    names = topic["sim"]["season_names"]
    start, roni, oni = series["start_year"], series["roni"], series["oni"]
    assert start == 1950
    assert len(roni) == len(oni) == 921          # DJF 1950 to ASO 2026
    assert len(names) == 12

    def idx(year, season):
        return (year - start) * 12 + SEASONS.index(season)

    def label(i):
        return f"{names[i % 12]} {start + i // 12}"

    assert idx(2026, "ASO") == len(roni) - 1

    def peak(vals, year):
        """Highest value from JJA of the start year to AMJ of the next, or to
        the end of the record. The table's note states this definition."""
        lo, hi = idx(year, "JJA"), min(idx(year + 1, "AMJ"), len(vals) - 1)
        best = max(range(lo, hi + 1), key=lambda i: vals[i])
        return vals[best], label(best)

    # The table: both rulers, value and season of each peak.
    table = next(sec["table"] for sec in topic["sections"] if sec.get("table"))
    years = {"1982–83": 1982, "1991–92": 1991, "1997–98": 1997,
             "2015–16": 2015, "2023–24": 2023, "2026, עד כה": 2026}
    assert [row[0] for row in table["rows"]] == list(years)
    for row in table["rows"]:
        r_val, r_when = peak(roni, years[row[0]])
        o_val, o_when = peak(oni, years[row[0]])
        assert row[1:] == [f"{r_val:.2f}", r_when, f"{o_val:.2f}", o_when], row

    # The sentences around it.
    assert max(roni) == 2.40 and label(roni.index(max(roni))) == "דצמבר–פברואר 1983"
    assert max(oni) == 2.59 and label(oni.index(max(oni))) == "נובמבר–ינואר 2015"
    assert roni[-1] == 1.97 and oni[-1] == 2.46
    assert round(100 * roni[-1] / max(roni)) == 82
    # ONI in ASO 2026 is the third highest season on record, behind two
    # seasons of the 2015-16 winter.
    assert sorted((v for v in oni if v > oni[-1]), reverse=True) == [2.59, 2.50]
    # On RONI, 2015-16 drops to third among the big events.
    ranked = sorted(((peak(roni, y)[0], y) for y in (1982, 1991, 1997, 2015)), reverse=True)
    assert [y for _, y in ranked] == [1982, 1997, 2015, 1991]

    # The swing from DJF to ASO of the same calendar year, RONI.
    def swing(year):
        return round(roni[idx(year, "ASO")] - roni[idx(year, "DJF")], 2)

    assert roni[idx(2026, "DJF")] == -0.91
    assert swing(2026) == 2.88
    assert swing(1997) == 2.28
    assert swing(1982) == 1.53
    assert swing(2015) == 1.26

    # Episodes: runs of consecutive seasons at or above a threshold. This is
    # the simulator's definition, stated in its caveat, not NOAA's.
    def runs(vals, t):
        out, run = [], None
        for i, v in enumerate(vals):
            if v >= t - 1e-9:
                if run is None:
                    run = [i, i]
                    out.append(run)
                run[1] = i
            else:
                run = None
        return out

    strong = runs(roni, 2.0)
    assert [label(max(range(a, b + 1), key=lambda i: roni[i])) for a, b in strong] == [
        "דצמבר–פברואר 1983", "דצמבר–פברואר 1992", "נובמבר–ינואר 1997", "נובמבר–ינואר 2015"]
    assert sum(v >= 2.0 for v in roni) == 16
    assert runs(roni, 2.5) == []                       # "שלא נרשם מעולם ב-RONI"
    assert len(runs(oni, 2.5)) == 1 and sum(v >= 2.5 for v in oni) == 2
    assert len(runs(oni, 2.0)) == 4

    # Niño 3.4: 50 degrees of longitude on the equator by 10 of latitude.
    assert round(50 * 111.32) == 5566
    assert round(50 * 111.32 * 10 * 111.32 / 1e6, 1) == 6.2

    tpl = (ROOT / "templates" / "topic.html.j2").read_text(encoding="utf-8")

    def branch(needle):
        at = tpl.index(needle)
        return tpl[at:tpl.index("{% endif %}", at)]

    # The timeline diagram: its polylines are these series, drawn at
    # x = 90 + i * 380 / 13 and y = 260 - (v + 1) * 210 / 3.6.
    timeline = branch("sec.diagram.type == 'enso-roni-timeline'")

    def points(year, n):
        lo = idx(year, "DJF")
        return " ".join(f"{90 + i * 380 / 13:.1f},{260 - (roni[lo + i] + 1.0) * 210 / 3.6:.1f}"
                        for i in range(n))

    drawn = re.findall(r'<polyline points="([^"]+)" class="(enso-line[^"]*)"', timeline)
    assert drawn == [
        (points(1982, 14), "enso-line enso-line--dotted"),
        (points(1997, 14), "enso-line enso-line--dashed"),
        (points(2015, 14), "enso-line"),
        (points(2026, 9), "enso-line enso-line--now"),
    ]
    assert idx(2026, "DJF") + 9 == len(roni), "the 2026 line must run to the last season"
    last_x, last_y = points(2026, 9).split()[-1].split(",")
    assert f'<circle cx="{last_x}" cy="{last_y}" r="4" class="enso-hit"/>' in timeline
    for v, y in ((2.0, "85"), (0.5, "172.5")):
        assert f"{260 - (v + 1.0) * 210 / 3.6:g}" == y
        assert f'<line x1="80" y1="{y}" x2="484" y2="{y}" class="enso-threshold"/>' in timeline
    assert round(260 - 1.0 * 210 / 3.6, 1) == 201.7
    assert '<line x1="80" y1="201.7" x2="484" y2="201.7" class="enso-zero"/>' in timeline

    # The map: x = 40 + (degrees east of 120E) * 440 / 170, y = 160 - 4 * lat.
    def lon_x(deg_east_of_120e):
        return round(40 + deg_east_of_120e * 440 / 170, 1)

    def lat_y(lat):
        return round(160 - 4 * lat, 1)

    regions = branch("sec.diagram.type == 'enso-nino-regions'")
    assert (lon_x(70), lon_x(120), lat_y(5), lat_y(-5)) == (221.2, 350.6, 140, 180)   # 170W-120W, 5N-5S
    assert f'<rect x="221.2" y="140" width="{350.6 - 221.2:.1f}" height="40" class="enso-box"/>' in regions
    assert (lat_y(20), lat_y(-20)) == (80, 240)
    assert '<rect x="40" y="80" width="440" height="160" class="enso-band"/>' in regions
    assert (lon_x(360 - 149.5 - 120), lat_y(-17.5)) == (274.2, 230)                  # Tahiti
    assert (lon_x(130.8 - 120), lat_y(-12.5)) == (68.0, 210)                          # Darwin
    assert '<circle cx="274.2" cy="230" r="4" class="enso-station"/>' in regions
    assert '<circle cx="68" cy="210" r="4" class="enso-station"/>' in regions

    # The simulator: the record fills the stage exactly, and the slider
    # starts on the "very strong" line the text talks about.
    sim = tpl[tpl.index("topic.sim.type == 'enso-history'"):]
    assert re.search(r'id="enso-in-threshold"[^>]*value="2.0"', sim)
    for year, x in ((1950, 20), (1980, 308), (2020, 692)):
        assert 20 + (year - 1950) * 12 * 0.8 == x
        assert f'<text x="{x}" y="257" class="diagram__axis-label">{year}</text>' in sim
    assert round(20 + (len(roni) - 1) * 0.8, 1) == 756.0 and 'x2="756"' in sim
    assert round(130 - 2 * 110 / 3, 1) == 56.7 and 'y1="56.7" x2="768"' in sim

    # The page's own words carry the same figures.
    text = json.dumps(topic, ensure_ascii=False)
    for needle in ("5,566", "6.2 מיליון", "82 אחוזים", "2.88", "מינוס 0.91", "השלישי בגובהו",
                   "ארבעה אירועים", "2.40", "2.59"):
        assert needle in text, needle


def test_orbital_compute_figure_matches_the_numbers_in_the_article():
    """Edition 18's lead figure and body are the paper's own calculation, not a
    quote. Every number in them is rebuilt from the stated assumptions."""
    SOLAR, EFF, SIGMA, EPS, PUE = 1361.0, 0.320, 5.670374419e-8, 0.9, 1.20

    assert round(SOLAR * EFF, 1) == 435.5       # W per square metre, ideal

    def radiate(k):
        return EPS * SIGMA * k ** 4

    assert round(radiate(300), 1) == 413.4
    assert round(radiate(350), 1) == 765.8
    assert round(radiate(400), 1) == 1306.5
    assert round(radiate(400) / radiate(300), 2) == 3.16

    heat = 1e6 * PUE                            # watts to shed per MW of compute
    assert round(heat / radiate(300)) == 2903
    assert round(heat / radiate(350)) == 1567
    assert round(heat / radiate(400)) == 919
    assert round(heat / (SOLAR * EFF * 0.70)) == 3936

    # Launch price. Both figures pair a price with the payload mass quoted in
    # the same breath; mixing a reusable price with an expendable mass is the
    # error the article names.
    f9 = 74e6 / 22_800
    fh = 150e6 / 63_800
    assert round(f9) == 3246
    assert round(fh) == 2351
    assert round(f9 / 200, 1) == 16.2           # to Google's own threshold


def test_every_topic_diagram_and_sim_type_is_handled_by_the_template():
    """Jinja does not raise on a value it has no branch for. A diagram type the
    template never matches renders nothing at all and the page ships looking
    fine, so the data is walked here instead of trusted."""
    tpl = (ROOT / "templates" / "topic.html.j2").read_text(encoding="utf-8")
    missing = []
    for path in TOPICS:
        topic = json.loads(path.read_text(encoding="utf-8"))
        wanted = []
        for sec in topic.get("sections", []):
            diagram = sec.get("diagram")
            if diagram and diagram.get("type"):
                wanted.append(("diagram", diagram["type"],
                               f"sec.diagram.type == '{diagram['type']}'"))
        sim = topic.get("sim")
        if sim and sim.get("type"):
            wanted.append(("sim", sim["type"],
                           f"topic.sim.type == '{sim['type']}'"))
        for kind, name, needle in wanted:
            if needle not in tpl:
                missing.append(f"{path.name}: {kind} '{name}' has no branch")
    assert not missing, "topic.html.j2 silently drops: " + "; ".join(missing)


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


def test_the_counter_in_use_is_the_only_one_wired_in():
    """A counter was replaced once. A second tracker left wired into the
    templates would keep sending pageviews to an account nobody reads, and the
    stale visible counter would print a number from the wrong source. The
    guard is by absence of anything else, not by the name of what was dropped,
    so the next replacement is caught too."""
    allowed = "babook.co.il"
    script_src = re.compile(r"<script[^>]*\bsrc=[\"']([^\"']+)[\"']", re.I)
    for path in sorted((ROOT / "templates").glob("*.j2")):
        for src in script_src.findall(path.read_text(encoding="utf-8")):
            if src.startswith(("http://", "https://", "//")):
                assert allowed in src, (
                    f"{path.name} loads a second remote script: {src}")
    for page in _served_pages():
        for src in script_src.findall(page.read_text(encoding="utf-8")):
            if src.startswith(("http://", "https://", "//")):
                assert allowed in src, (
                    f"{page.relative_to(ROOT)} loads a second remote script: {src}; "
                    "rebuild the site if the templates are already clean")


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


def test_authenticity_lead_matches_the_number_it_derives():
    """BKM 13. The 2026-10-18 lead quotes two effects from Porter and Machery's
    second study, 0.814 and 1.045 rating points, and then prints their sum as
    the distance between the two directions. That third bar is the desk's own
    arithmetic: no reader can catch it being wrong, because the paper is where
    it first appears."""
    ed = json.loads(
        (ROOT / "data" / "editions" / "2026-10-18.json").read_text(encoding="utf-8"))
    text = json.dumps(ed, ensure_ascii=False)

    label_penalty, authorship_gain = 0.814, 1.045
    assert "0.814" in text and "1.045" in text

    gap = round(label_penalty + authorship_gain, 3)
    assert gap == 1.859

    bars = [b["value"] for b in ed["lead"]["figure"]["bars"]]
    assert bars == [authorship_gain, label_penalty, gap]
    assert ed["lead"]["figure"]["max"] >= max(bars)

    # Both effects are on the same seven-point scale, so the derived gap has to
    # stay inside it or the two numbers were never comparable to begin with.
    assert gap < 7

    # The figure note has to keep saying the third bar was computed here. The
    # moment it reads as quoted, the reader loses the only warning they get.
    note = ed["lead"]["figure"]["note"]
    assert "חושבה כאן" in note and "אינה מצוטטת" in note


def test_gps_page_matches_the_relativity_numbers_it_derives():
    """BKM 13. The GPS page prints four numbers that are not quoted from any
    source: the two relativistic clock rates, their sum, and the daily ground
    error that follows. They are recomputed here from the two formulas the page
    itself prints, so a drift in either the text or the diagram fails."""
    topic = json.loads(
        (ROOT / "data" / "topics" / "gps.json").read_text(encoding="utf-8"))
    text = json.dumps(topic, ensure_ascii=False)
    svg = (ROOT / "templates" / "topic.html.j2").read_text(encoding="utf-8")

    c = 299_792_458.0          # m/s, exact by definition
    GM = 3.986_004_418e14      # m^3/s^2, WGS 84
    r_earth = 6_371_000.0      # m, mean radius
    a = 26_560_000.0           # m, GPS semi-major axis
    period = 43_082.0          # s, half a sidereal day
    day = 86_400.0

    v = 2 * math.pi * a / period
    assert round(v) == 3874, "orbital speed, metres per second"
    assert "3,874 מטר לשנייה" in text

    # Special relativity: the moving clock loses.
    slow = v * v / (2 * c * c) * day * 1e6
    assert round(slow, 1) == 7.2
    assert "7.2 מיקרו-שניות" in text and "7.2 מיקרו-שניות" in svg

    # General relativity: the clock higher in the well gains, and gains more.
    fast = GM / (c * c) * (1 / r_earth - 1 / a) * day * 1e6
    assert round(fast, 1) == 45.7
    assert "45.7 מיקרו-שניות" in text and "45.7 מיקרו-שניות" in svg
    assert fast > slow, "the page says gravity wins; if it stops winning, so must the page"

    net = round(fast - slow, 1)
    assert net == 38.5
    assert "38.5 מיקרו-שניות" in text and "38.5 מיקרו-שניות" in svg

    # The whole point of the section: what those microseconds cost on the ground.
    km_per_day = net * 1e-6 * c / 1000
    assert round(km_per_day, 1) == 11.5
    assert "11.5 קילומטר ביום" in text and "11.5 קילומטר ביום" in svg

    # And the conversion the rest of the page leans on, light in one nanosecond.
    assert round(c / 1e9, 2) == 0.30
    assert "30 סנטימטר" in text


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


def test_efficiency_lead_matches_the_ratios_and_rates_it_derives():
    """BKM 13. The 2026-10-19 lead's whole argument is arithmetic the desk does
    itself. The headcount ratios are not quoted anywhere, and the two revenue
    per employee figures are divisions of numbers taken from 10-K filings. No
    reader can catch any of them being wrong, because the paper is where they
    first appear."""
    ed = json.loads(
        (ROOT / "data" / "editions" / "2026-10-19.json").read_text(encoding="utf-8"))
    text = json.dumps(ed, ensure_ascii=False)

    # Output per worker needed to hold output constant after a headcount cut.
    assert round(1 / 0.5, 1) == 2.0
    assert round(1 / 0.2, 1) == 5.0
    # And with output itself growing 30 percent.
    assert round(1.3 / 0.5, 1) == 2.6
    assert round(1.3 / 0.2, 1) == 6.5
    for printed in ("פי 2.6", "פי 6.5"):
        assert printed in text, f"the lead no longer prints {printed}"

    # The measured field-study gain the whole piece is weighed against. 15
    # percent and 5,172 agents are the published QJE abstract, not the 14
    # percent and 5,179 the received research document carried.
    assert "15 אחוז" in text and "5,172" in text
    assert "5,179" not in text and "34 אחוז" not in text

    # Revenue per employee, computed from the filings, in millions of dollars.
    palantir = 4_475_446_000 / 4_429
    servicenow = 13_278_000_000 / 29_187
    assert round(palantir / 1e6, 2) == 1.01
    assert round(servicenow / 1e6, 3) == 0.455
    assert round(servicenow / 1e3) == 455 and "455 אלף" in text

    bars = {b["label"]: b["value"] for b in ed["lead"]["figure"]["bars"]}
    values = list(bars.values())
    assert values == sorted(values, reverse=True), "figure bars must descend"
    assert ed["lead"]["figure"]["max"] >= max(values)
    assert 2.0 in values, "the claimed threshold bar is gone"
    assert round(palantir / 1e6, 2) in values
    assert round(servicenow / 1e6, 3) in values

    # The only bar above the claimed threshold is a self-defined metric, and
    # the note is the reader's only warning that it is not the same division.
    top = max(bars, key=bars.get)
    assert bars[top] == 2.57 and "מדד שהחברה הגדירה" in top
    note = ed["lead"]["figure"]["note"]
    assert "מדד שהחברה מגדירה בעצמה" in note and "אינה אותו חישוב" in note


def test_public_key_page_matches_the_exchange_it_works_through():
    """BKM 13. The public-key page walks a full Diffie-Hellman exchange by hand
    and prints every intermediate number, and the simulator recomputes the same
    thing in the browser. Nothing here is quoted, so a typo in either the prose
    or the JavaScript would ship looking perfectly reasonable."""
    topic = json.loads(
        (ROOT / "data" / "topics" / "public-key.json").read_text(encoding="utf-8"))
    text = json.dumps(topic, ensure_ascii=False)

    p, g, a, b = 23, 5, 6, 15
    pub_a = pow(g, a, p)
    pub_b = pow(g, b, p)
    assert pub_a == 8 and pub_b == 19

    shared = pow(pub_b, a, p)
    assert shared == pow(pub_a, b, p) == 2, "the two sides must agree"
    # The reason they agree, stated in the prose as 5 to the ninetieth.
    assert pow(g, a * b, p) == shared and a * b == 90
    assert "5 בחזקת 90" in text

    for printed in ("15,625", "השארית היא 8", "ומקבל 19", "התוצאה היא 2"):
        assert printed in text, f"the page no longer prints {printed!r}"

    # The eavesdropper's search is what the simulator's bar measures: a plain
    # scan for the exponent, which on a clock this small ends almost at once.
    tries = next(k for k in range(1, p) if pow(g, k, p) == pub_a)
    assert tries == a <= p - 1

    sim = topic["sim"]
    assert sim["type"] == "dh-exchange"
    src = (ROOT / "templates" / "topic.html.j2").read_text(encoding="utf-8")
    block = src.split("דיפי-הלמן: חילוף מפתחות")[1]
    assert f"var P = {p}, G = {g};" in block, (
        "the simulator no longer uses the same clock and base as the prose"
    )
    for element in ("dh-in-a", "dh-in-b", "dh-out-pa", "dh-out-pb", "dh-out-k", "dh-bar"):
        assert f'id="{element}"' in src, f"the simulator lost {element}"

    # The page must keep saying this is a demonstration. A 23-hour clock is not
    # encryption, and the caveat is the only place the reader is told so.
    assert "2048 ביט" in sim["caveat"] and "הדגמה" in sim["caveat"]


def test_post_quantum_lead_matches_the_numbers_it_derives():
    """BKM 13. The 2026-11-15 lead quotes two qubit estimates (Gidney and Ekerå
    2019: about 20 million; Gidney 2025: under one million) and two machine
    sizes (Willow 105, Helios 98). Everything else numeric on the page is the
    desk's own arithmetic: the "more than twentyfold" drop, the "four orders of
    magnitude" between a hundred and a million, the 617 decimal digits of a
    2048-bit key, and the figure that draws the two estimates side by side. No
    reader can catch a wrong one, because the paper is where they first appear."""
    ed = json.loads(
        (ROOT / "data" / "editions" / "2026-11-15.json").read_text(encoding="utf-8"))
    text = json.dumps(ed, ensure_ascii=False)

    old, new = 20_000_000, 1_000_000
    assert "20 מיליון" in text and "ממיליון" in text
    assert old / new == 20 and "יותר מפי 20" in text, \
        "the drop is exactly twentyfold at the bound, and more below it"

    # Both machines the article names are about a hundred qubits, and the
    # bound is a million: four decimal orders of magnitude, not three or five.
    willow, helios = 105, 98
    assert "105 קיוביטים" in text and "מונה 98" in text
    for machine in (willow, helios):
        assert round(math.log10(new / machine)) == 4
    assert "ארבעה סדרי גודל" in text

    # A 2048-bit number has ceil(2048 * log10 2) decimal digits. The quote's
    # byline and the body both print it, so a drift would show in two places.
    digits = math.ceil(2048 * math.log10(2))
    assert digits == 617 and text.count("617 ספרות") == 2

    # The figure restates the two estimates in millions and nothing else, with
    # the smaller bar drawn at the bound the paper actually gives. The unit
    # lives in the title so the value column prints a bare number.
    fig = ed["lead"]["figure"]
    bars = [b["value"] for b in fig["bars"]]
    assert bars == [old // 1_000_000, new // 1_000_000] == [20, 1]
    assert fig["unit"] == "" and "במיליונים" in fig["title"]
    assert fig["max"] >= max(bars)
    assert "חסם עליון" in fig["note"], \
        "the note has to keep saying the second bar is a bound, not a measurement"
    assert "מאה מתוך 20 מיליון" in fig["note"]
    assert fig["source"]

    # The largest number factored honestly on quantum hardware, per Cloudflare's
    # 2025 review, is 15. It appears in the body and in the pull quote.
    assert "הוא 15" in text and ed["quote"]["text"].count("15") == 1


def test_free_innovation_lead_matches_the_numbers_it_derives():
    """BKM 13. The 2026-11-16 lead quotes the bank experiment's raw counts, 33
    of 158 invited newcomers gone against 22 of 63 controls, and then prints
    the desk's own arithmetic on them: two leave rates, a gap of 14 points, a
    drop of about 40 percent, the 67 invitees who never came, and Intel IT's
    122 weekly hours turned into a year. The authors' "about 50 percent" comes
    from their logistic regression and must stay theirs. The background
    document prints the same numbers, so it is walked too."""
    ed = json.loads(
        (ROOT / "data" / "editions" / "2026-11-16.json").read_text(encoding="utf-8"))
    doc = json.loads(
        (ROOT / "data" / "research" / "2026-11-16.doc.json").read_text(encoding="utf-8"))
    lead = ed["lead"]
    fig = lead["figure"]
    paragraphs = [lead["standfirst"], *lead["body"], fig["note"]]
    text = " ".join(paragraphs)
    doc_text = json.dumps(doc, ensure_ascii=False)

    invited, invited_left, control, control_left, attended = 158, 33, 63, 22, 91
    invited_rate = round(invited_left / invited * 100, 1)
    control_rate = round(control_left / control * 100, 1)
    assert (invited_rate, control_rate) == (20.9, 34.9)
    gap = control_left / control - invited_left / invited
    assert round(gap * 100) == 14
    assert round(gap / (control_left / control) * 100) == 40
    assert invited + control == 221 and invited - attended == 67
    assert 122 * 52 == 6344

    for needle in ("20.9 אחוז", "34.9 אחוז", "33 מתוך 158", "22 מתוך 63",
                   "14 נקודות אחוז", "כ-40 אחוז", "6,344"):
        assert needle in text, f"the lead lost {needle!r}"
        assert needle in doc_text, f"the background document lost {needle!r}"
    assert "221 עובדים" in text and "67 שלא הגיעו" in fig["note"]
    assert "122 שעות" in text

    # The 50 percent is the authors' model, not the raw rates. Wherever the
    # lead prints it, the authors and their regression are named beside it.
    fifty = [p for p in paragraphs if "50 אחוז" in p]
    assert fifty
    for p in fifty:
        assert "המחברים" in p and "רגרסיה לוגיסטית" in p

    # The figure draws control before invited, overall then men then women,
    # and the gender rates are the authors', printed in the body as drawn.
    bars = fig["bars"]
    values = [b["value"] for b in bars]
    assert values == [control_rate, invited_rate, 42.42, 20.65, 26.67, 21.21]
    assert [b.get("muted", False) for b in bars] == [True, False] * 3
    assert f"{control_left} מתוך {control}" in bars[0]["label"]
    assert f"{invited_left} מתוך {invited}" in bars[1]["label"]
    for v in values[2:]:
        assert f"{v:g}" in text
    assert fig["max"] >= max(values) and fig["unit"] == "%"
    assert "אינו מובהק" in fig["note"] and fig["source"]


def test_patents_lead_matches_the_numbers_it_derives():
    """BKM 13. The 2026-11-18 lead turns WIPO's 35.3 percent still in force at
    year ten into "about two in three" gone and its 17 percent into "about one
    in six", sums Humira's annual sales into "more than 200 billion", counts
    the American exclusivity in years, and divides Qualcomm's segment results
    into two shares Qualcomm never printed. The figure redraws the 10-K series.
    The background document prints the same numbers, so it is walked too."""
    ed = json.loads(
        (ROOT / "data" / "editions" / "2026-11-18.json").read_text(encoding="utf-8"))
    doc = json.loads(
        (ROOT / "data" / "research" / "2026-11-18.doc.json").read_text(encoding="utf-8"))
    lead = ed["lead"]
    fig = lead["figure"]
    text = " ".join([lead["standfirst"], *lead["body"], fig["note"]])
    doc_text = json.dumps(doc, ensure_ascii=False)

    in_force_at_ten, full_term, moore_lapsed = 35.3, 17, 53.71
    assert round(100 - in_force_at_ten, 1) == 64.7 and "64.7" in doc_text
    assert abs((100 - in_force_at_ten) / 100 - 2 / 3) < 0.02
    assert abs(full_term / 100 - 1 / 6) < 0.01
    assert "שניים מכל שלושה" in text and "אחד מכל שישה" in lead["standfirst"]
    assert moore_lapsed > 50 and "יותר ממחצית" in text

    # Worldwide Humira sales in billions of dollars, Abbott then AbbVie 10-Ks.
    humira = {
        2003: 0.280, 2004: 0.852, 2005: 1.4, 2006: 2.0, 2007: 3.0, 2008: 4.5,
        2009: 5.5, 2010: 6.5, 2011: 7.9, 2012: 9.265, 2013: 10.659,
        2014: 12.543, 2015: 14.012, 2016: 16.078, 2017: 18.427, 2018: 19.936,
        2019: 19.169, 2020: 19.832, 2021: 20.694, 2022: 21.237, 2023: 14.404,
        2024: 8.993, 2025: 4.540,
    }
    exclusive = sum(v for year, v in humira.items() if year <= 2022)
    assert round(exclusive, 2) == 213.78 and exclusive > 200
    assert "213.78" in doc_text and "213.78" in fig["note"]
    assert "200 מיליארד" in text
    assert max(humira, key=humira.get) == 2022
    assert 2023 - 2003 == 20 and "20 שנה" in lead["standfirst"]
    molecule_expiry, first_biosimilar = (2016, 12), (2023, 1)
    months = (first_biosimilar[0] - molecule_expiry[0]) * 12 + first_biosimilar[1] - molecule_expiry[1]
    assert months > 6 * 12 and "יותר משש שנים" in text
    assert 2002 + 12 == 2014
    for needle in ("21.237", "14.404", "8.993", "4.540", "דצמבר 2014"):
        assert needle in text, f"the lead lost {needle!r}"
        assert needle in doc_text, f"the background document lost {needle!r}"

    qtl_revenue, qualcomm_revenue, qtl_ebt, qct_ebt = 5556, 43120, 4022, 10101
    assert round(qtl_revenue / qualcomm_revenue * 100, 1) == 12.9
    assert round(qtl_ebt / (qtl_ebt + qct_ebt) * 100, 1) == 28.5
    assert round(qtl_ebt / qtl_revenue * 100) == 72
    for needle in ("12.9 אחוז", "28.5 אחוז", "72 אחוז"):
        assert needle in text, f"the lead lost {needle!r}"
        assert needle in doc_text, f"the background document lost {needle!r}"

    years = list(range(2014, 2026))
    bars = fig["bars"]
    assert [b["label"] for b in bars] == [str(y) for y in years]
    assert [b["value"] for b in bars] == [round(humira[y], 1) for y in years]
    assert [b.get("muted", False) for b in bars] == [y >= 2023 for y in years]
    assert fig["max"] >= max(b["value"] for b in bars) and fig["unit"] == ""
    assert "21.237" in lead["body"][fig["after"]], (
        "the Humira chart no longer sits under the paragraph that prints its numbers")


def test_fpga_lead_matches_the_numbers_it_derives():
    """BKM 13. The 2026-11-20 lead sets one model's two scores side by side,
    58 percent on VerilogEval's study exercises and 31 percent on CVDP's
    engineer-written problems, and calls the gap "almost double". It divides
    LATCH's held-out results by the in-sample ones into "less than half" and
    "about a third", and the figure note prints both ratios. LATCH split its
    16 designs eight and eight, so the halves must average back to the
    whole-set numbers the lead also prints. The background document prints the
    same numbers, so it is walked too."""
    ed = json.loads(
        (ROOT / "data" / "editions" / "2026-11-20.json").read_text(encoding="utf-8"))
    doc = json.loads(
        (ROOT / "data" / "research" / "2026-11-20.doc.json").read_text(encoding="utf-8"))
    lead = ed["lead"]
    fig = lead["figure"]
    text = " ".join([lead["standfirst"], *lead["body"], fig["note"]])
    doc_text = json.dumps(doc, ensure_ascii=False)

    # Llama 3.1 405B, writing a circuit from a spec: VerilogEval, then CVDP.
    study, engineers = 58, 31
    assert round(study / engineers, 2) == 1.87 and "1.87" in doc_text
    assert 1.75 < study / engineers < 2
    assert "כמעט פי שניים" in text and "כמעט פי שניים" in doc_text

    # LATCH: the model with its knowledge base and the plain rule, on held-out
    # designs against the designs they were built from.
    model_new, model_seen, rule_new, rule_seen = 11.9, 28.6, 9.7, 30.1
    assert round(model_new / model_seen, 2) == 0.42 < 0.5
    assert round(rule_new / rule_seen, 2) == 0.32
    assert abs(rule_new / rule_seen - 1 / 3) < 0.02
    assert "פחות ממחצית" in text and "כשליש" in text
    assert "0.42" in fig["note"] and "0.32" in fig["note"]
    assert abs((model_new + model_seen) / 2 - 20.3) < 0.1
    assert round((rule_new + rule_seen) / 2, 1) == 19.9
    for needle in ("58 אחוז", "31 אחוז", "11.9", "28.6", "9.7", "30.1",
                   "19.9", "20.3", "98.2"):
        assert needle in text, f"the lead lost {needle!r}"
        assert needle in doc_text, f"the background document lost {needle!r}"

    bars = fig["bars"]
    assert [b["value"] for b in bars] == [model_seen, model_new, rule_seen, rule_new]
    assert [b.get("muted", False) for b in bars] == [True, False, True, False]
    assert fig["max"] >= max(b["value"] for b in bars) and fig["unit"] == "%"
    assert "11.9" in lead["body"][fig["after"]], (
        "the LATCH chart no longer sits under the paragraph that prints its numbers")

    # Altera was Intel's, Intel still holds 49 percent of it, and Intel employs
    # the editor. The disclosure travels with every lead that names Altera.
    assert "אלטרה" in text and "אינטל היא מקום עבודתו של עורך העיתון" in text


def test_edition_22_briefs_match_the_numbers_they_derive():
    """BKM 13. Two briefs on 2026-11-20 print numbers their sources never did.
    Anthropic gave a price and a share count but no deal size, so 81.3 billion
    is 980 million shares at 83 dollars. The upsizing from 825 million is all
    new company stock only because the seven founders sell 3,378,378 shares
    each both before and after. Nvidia gave 2.4 billion of licensed Hopper
    sales and 115.8 billion of revenue, and the brief calls the first about 2
    percent of the second."""
    ed = json.loads(
        (ROOT / "data" / "editions" / "2026-11-20.json").read_text(encoding="utf-8"))
    stories = {s["url"]: s["summary"] for sec in ed["grid"] for s in sec["stories"]}

    anthropic = stories[
        "https://www.anthropic.com/news/anthropic-prices-initial-public-offering"]
    company, founders, per_founder = 956_351_354, 23_648_646, 3_378_378
    total, before, price = 980_000_000, 825_000_000, 83
    assert company + founders == total
    assert founders == 7 * per_founder and "שבעת המייסדים" in anthropic
    assert company - (before - founders) == total - before == 155_000_000
    assert round(total * price / 1e9, 1) == 81.3
    for needle in ("956,351,354", "23,648,646", "980 מיליון", "825 מיליון",
                   "83 דולר", "81.3 מיליארד", "חשבון העיתון"):
        assert needle in anthropic, f"the Anthropic brief lost {needle!r}"

    nvidia = stories["https://www.cbsnews.com/news/nvidia-stops-shipping-hopper-chips-china/"]
    hopper, revenue = 2.4, 115.8
    assert round(hopper / revenue * 100) == 2
    for needle in ("2.4 מיליארד", "115.8 מיליארד", "כ-2 אחוז", "חשבון העיתון"):
        assert needle in nvidia, f"the Nvidia brief lost {needle!r}"


def _render_lead_related(lead: dict) -> str:
    """Render the lead's cross-reference block through the real template."""
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    import build_site

    env = Environment(
        loader=FileSystemLoader(build_site.TEMPLATE_DIR),
        autoescape=select_autoescape(["html", "j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    src = (build_site.TEMPLATE_DIR / "edition.html.j2").read_text(encoding="utf-8")
    start = src.index("{% if edition.lead.related %}")
    end = src.index("{% endif %}", start) + len("{% endif %}")
    return env.from_string(src[start:end]).render(edition={"lead": lead}, base="../")


def test_a_lead_cross_reference_renders_as_a_link_to_the_topic_page():
    """BKM 11. Jinja renders a missing key as nothing, so a lead whose `related`
    block named the wrong key would ship with a silent hole where the link to
    the earlier learning page should be. The block is rendered through the real
    template with the real key names, and the link has to come out."""
    html = _render_lead_related({"headline": "כותרת", "related": {
        "slug": "public-key", "title": "מה זו הצפנת מפתח ציבורי"}})
    assert 'href="../learn/public-key.html"' in html
    assert "מה זו הצפנת מפתח ציבורי" in html
    assert "ראו גם:" in html, "the default label is used when none is given"

    html = _render_lead_related({"headline": "כותרת", "related": {
        "label": "רקע", "slug": "public-key", "title": "ת"}})
    assert "רקע:" in html and "ראו גם" not in html

    assert "lead__related" not in _render_lead_related({"headline": "כותרת"})


def test_a_lead_cross_reference_must_name_a_topic_on_disk(tmp_path):
    """The template cannot tell a slug with no topic file from a real one; it
    renders a link to a 404 either way. The validator has to catch it, the same
    way it catches a learning block that names a topic that does not exist."""
    base = {"date": "2020-01-01", "number": 1, "compiled_at": "2020-01-01T00:00:00"}

    def related_errors(rel: dict) -> list[str]:
        errors: list[str] = []
        validate.check_edition(dict(base, lead={"related": rel}),
                               tmp_path / "x.json", {}, errors)
        return [e for e in errors if "lead.related" in e]

    assert not related_errors({"slug": "public-key", "title": "ת"})
    assert related_errors({"slug": "no-such-topic", "title": "ת"}), \
        "a cross-reference to a topic that does not exist was accepted"
    assert related_errors({"slug": "public-key"}), \
        "a cross-reference with no visible title was accepted"
    assert related_errors({"title": "ת"}), \
        "a cross-reference with no slug was accepted"


def test_every_lead_cross_reference_in_every_edition_resolves():
    """The two rules above, applied to the real editions rather than fixtures,
    including editions not yet due. The block must render a link to a topic page
    the catalog actually builds, and the title the reader clicks on must be the
    topic's own, not a paraphrase that drifted when the page was renamed."""
    seen = 0
    for path in ALL_EDITIONS:
        ed = json.loads(path.read_text(encoding="utf-8-sig"))
        rel = (ed.get("lead") or {}).get("related")
        if not rel:
            continue
        seen += 1
        topic_path = ROOT / "data" / "topics" / f"{rel['slug']}.json"
        assert topic_path.exists(), f"{path.name}: lead.related names {rel['slug']!r}, no such topic"
        topic = json.loads(topic_path.read_text(encoding="utf-8-sig"))
        stem = topic["title"].split(":")[0].strip()
        assert stem in rel["title"], \
            f"{path.name}: the cross-reference title no longer matches the topic's"
        html = _render_lead_related(ed["lead"])
        assert f'href="../learn/{rel["slug"]}.html"' in html
        assert rel["title"] in html
    assert seen, "no edition carries a lead cross-reference; this walk checks nothing"


