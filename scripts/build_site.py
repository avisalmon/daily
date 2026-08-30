"""Build the DailyDigest static newspaper site.

Reads every edition JSON in data/editions/, renders one HTML page per edition
into editions/, and copies the newest edition to index.html.

An edition dated in the future is written but not published: it stays out of the
front page, the archive, search and the learning catalog until its date arrives
in Asia/Jerusalem. That is what lets an edition be prepared the evening before
and appear on its own morning without anyone at the keyboard.

    python scripts/build_site.py
    python scripts/build_site.py --include-future   # local preview only
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape

import weather
import validate

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "editions"
RESEARCH_SRC = ROOT / "data" / "research"
RESEARCH_OUT = ROOT / "research"
TOPIC_DIR = ROOT / "data" / "topics"
LEARN_OUT = ROOT / "learn"
TEMPLATE_DIR = ROOT / "templates"
EDITIONS_DIR = ROOT / "editions"

SITE = {
    "title": "היום בקיצור",
    "title_main": "היום",
    "title_thin": "בקיצור",
    "tagline": "דברים שקרו היום ומעניינים אותי",
    "place": "יוצא לאור מדי יום כמעט",
    "price": "יוצר במלואו על ידי בינה מלאכותית",
    "language": "he",
    "colophon": "הופק אוטומטית",
}

HE_MONTHS = [
    "ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני",
    "יולי", "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר",
]

# ראשון=0 ... שבת=6 לפי weekday() של פייתון: שני=0
HE_WEEKDAYS = {0: "שני", 1: "שלישי", 2: "רביעי", 3: "חמישי", 4: "שישי", 5: "שבת", 6: "ראשון"}


def he_date_long(d: datetime) -> str:
    return f"יום {HE_WEEKDAYS[d.weekday()]}, {d.day} ב{HE_MONTHS[d.month - 1]} {d.year}"


def he_date_short(d: datetime) -> str:
    return f"{d.day} ב{HE_MONTHS[d.month - 1]}"

# Abstract engraving-style placeholders. Swap for real images later.
PALETTES = [
    ("#2b2a26", "#c9bfa8", "#8c1c13"),
    ("#1c2c3a", "#b9c6cf", "#1c4b73"),
    ("#33291f", "#d5c4a4", "#6b4a2f"),
    ("#242b24", "#c2ccbc", "#3f5c3a"),
    ("#312433", "#c9bbcb", "#5d3a63"),
    ("#3a2a22", "#d3bfaf", "#8c1c13"),
]



def paper_today() -> date:
    """The date the paper considers 'today', in Asia/Jerusalem.

    Never use the server clock. GitHub Actions runs in UTC, where midnight in
    Israel falls at 21:00 the previous day in summer and 22:00 in winter, so a
    naive local date would flip the front page two or three hours early and the
    error would change with daylight saving.
    """
    return datetime.now(ZoneInfo("Asia/Jerusalem")).date()


def load_editions(include_future: bool = False) -> list[dict]:
    """Editions newest first, excluding any dated after today.

    An edition may be written and committed the day before it runs. Until its
    date arrives it is not the front page, not in the archive, not in search and
    not in the learning catalog: the whole site is built from this one list, so
    gating here gates everything.
    """
    editions = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(DATA_DIR.glob("*.json"))]
    for e in editions:
        e["story_count"] = 1 + sum(len(s["stories"]) for s in e.get("grid", []))
        e.setdefault("date_long", he_date_long(datetime.fromisoformat(e["date"])))
    if not include_future:
        today = paper_today()
        editions = [e for e in editions if date.fromisoformat(e["date"]) <= today]
    editions.sort(key=lambda e: e["date"], reverse=True)
    return editions


def pending_editions() -> list[dict]:
    """Editions written but not yet due. Reported so a build never looks silent."""
    today = paper_today()
    out = []
    for p in sorted(DATA_DIR.glob("*.json")):
        e = json.loads(p.read_text(encoding="utf-8"))
        if date.fromisoformat(e["date"]) > today:
            out.append(e)
    return out


def publish_research(editions: list[dict]) -> list[str]:
    """Copy each edition's source research PDF into the published site.

    The lead story links to it (docs/SPEC.md §5), so the file must be
    reachable from the site, not just sitting in the gitignored input folder.
    """
    published = []
    for e in editions:
        matches = sorted(RESEARCH_SRC.glob(f"{e['date']}-*.pdf"))
        if not matches:
            continue
        RESEARCH_OUT.mkdir(parents=True, exist_ok=True)
        dest = RESEARCH_OUT / f"{e['date']}.pdf"
        shutil.copyfile(matches[0], dest)
        published.append(dest.name)
    return published


def search_index(editions: list[dict]) -> list[dict]:
    """Flatten every edition into searchable documents.

    One doc per lead story, per grid story, and per learning topic. The whole
    index ships as a single JSON file and is searched client-side, so the site
    stays static.
    """
    docs: list[dict] = []
    for e in editions:
        href = f"editions/{e['date']}.html"
        common = {"date": e["date"], "date_long": e["date_long"], "href": href}

        lead = e["lead"]
        docs.append(
            {
                **common,
                "kind": "lead",
                "title": lead["headline"],
                "source": lead.get("source", ""),
                "text": " ".join([lead.get("standfirst", "")] + lead.get("body", [])),
            }
        )

        for section in e.get("grid", []):
            for story in section.get("stories", []):
                docs.append(
                    {
                        **common,
                        "kind": "story",
                        "title": story["headline"],
                        "source": story.get("source", ""),
                        "text": story.get("summary", ""),
                    }
                )

        learning = e.get("learning")
        if learning:
            docs.append(
                {
                    **common,
                    "kind": "learning",
                    "title": learning["title"],
                    "source": "נושא לימוד",
                    "text": " ".join(learning.get("body", [])),
                }
            )
    return docs


def learning_topics(editions: list[dict]) -> list[dict]:
    """Catalog entries for every learning topic ever published."""
    topics = []
    for e in editions:
        learning = e.get("learning")
        if not learning:
            continue
        body = learning.get("body", [])
        blurb = body[0] if body else ""
        if len(blurb) > 230:
            blurb = blurb[:230].rsplit(" ", 1)[0] + "…"
        topics.append(
            {
                "title": learning["title"],
                "slug": learning.get("slug", ""),
                "blurb": blurb,
                "date": e["date"],
                "date_long": e["date_long"],
                "href": f"editions/{e['date']}.html",
                "page": f"learn/{learning['slug']}.html"
                        if learning.get("slug") and (TOPIC_DIR / f"{learning['slug']}.json").exists()
                        else "",
            }
        )
    return topics


def render_topics(env, editions: list[dict], held_back: set[str] | None = None) -> list[str]:
    """Render one standalone page per learning topic.

    The catalog grows day by day; each topic keeps its own page forever. A topic
    belonging to an edition that is not yet due is skipped, and any page left
    from an earlier build is removed: the learning page would otherwise reveal
    tomorrow's topic while the edition itself is still held back.
    """
    if not TOPIC_DIR.exists():
        return []
    held_back = held_back or set()
    by_date = {e["date"]: e for e in editions}
    template = env.get_template("topic.html.j2")
    LEARN_OUT.mkdir(parents=True, exist_ok=True)
    written = []
    for path in sorted(TOPIC_DIR.glob("*.json")):
        topic = json.loads(path.read_text(encoding="utf-8"))
        if topic.get("edition") in held_back:
            stale = LEARN_OUT / f"{topic['slug']}.html"
            if stale.exists():
                stale.unlink()
                print(f"Withdrew not-yet-due topic: learn/{stale.name}")
            continue
        edition = by_date.get(topic.get("edition", ""))
        if edition:
            topic.setdefault("date_long", edition["date_long"])
        html = template.render(site=SITE, topic=topic, base="../", nav="learn")
        out = LEARN_OUT / f"{topic['slug']}.html"
        out.write_text(html, encoding="utf-8")
        written.append(out.name)
    return written


def group_by_month(archive: list[dict]) -> list[dict]:
    groups: list[dict] = []
    for entry in archive:
        d = datetime.fromisoformat(entry["date"])
        label = f"{HE_MONTHS[d.month - 1]} {d.year}"
        if not groups or groups[-1]["label"] != label:
            groups.append({"label": label, "editions": []})
        groups[-1]["editions"].append(entry)
    return groups


def build(include_future: bool = False) -> None:
    problems = validate.validate()
    if problems:
        print(f"VALIDATION FAILED - {len(problems)} problem(s):")
        for p in problems:
            print(f"  - {p}")
        raise SystemExit("Refusing to publish. Fix the data or the rule in scripts/validate.py.")

    editions = load_editions(include_future=include_future)
    pending = [] if include_future else pending_editions()
    if not editions:
        raise SystemExit(
            "No editions are due yet. "
            + (f"{len(pending)} edition(s) dated in the future: "
               + ", ".join(e["date"] for e in pending)
               + ". Preview with --include-future." if pending else "data/editions/ is empty.")
        )

    research = publish_research(editions)
    EDITIONS_DIR.mkdir(parents=True, exist_ok=True)

    archive = [
        {
            "date": e["date"],
            "date_short": he_date_short(datetime.fromisoformat(e["date"])),
            "date_long": e["date_long"],
            "number": e["number"],
            "href": f"editions/{e['date']}.html",
            "headline": e["lead"]["headline"],
            "story_count": e["story_count"],
            "learning": (e.get("learning") or {}).get("title", ""),
            "has_research": (RESEARCH_OUT / f"{e['date']}.pdf").exists(),
        }
        for e in editions
    ]

    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(["html", "j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("edition.html.j2")

    latest = editions[0]

    # The newest edition carries a reading taken at press time; archived editions
    # keep the weather they were printed with. A failed fetch changes nothing.
    #
    # Press time is once per paper-day. This used to refetch on every build, which
    # was harmless by hand but not in CI: the hourly publish job would rewrite the
    # temperature and commit it 24 times a day. A newspaper prints one reading and
    # does not amend it at noon, so the stored `observed` timestamp decides - if
    # it already falls on the paper's own day, it stands.
    stored_reading = latest.get("almanac") or {}
    observed = str(stored_reading.get("observed", ""))[:10]
    if observed == latest["date"]:
        print(f"Weather: keeping the reading taken at press time ({stored_reading.get('temp')})")
    else:
        try:
            reading = weather.fetch()
            latest["almanac"] = reading
            path = DATA_DIR / f"{latest['date']}.json"
            if path.exists():
                stored = json.loads(path.read_text(encoding="utf-8"))
                stored["almanac"] = reading
                path.write_text(
                    json.dumps(stored, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
            print(f"Weather: {reading['place']} {reading['temp']} {reading['conditions']}")
        except Exception as exc:
            print(f"Weather: fetch failed ({exc}) - keeping stored reading")

    for edition in editions:
        # Pages inside editions/ need to climb one level for shared assets.
        html = template.render(
            site=SITE,
            edition=edition,
            archive=archive,
            base="../",
            is_latest=edition["date"] == latest["date"],
        )
        (EDITIONS_DIR / f"{edition['date']}.html").write_text(html, encoding="utf-8")

    # A held-back edition must not survive as a stale file from an earlier build.
    # Without this, running --include-future once would publish it permanently.
    if not include_future:
        due = {e["date"] for e in editions}
        for stale in sorted(EDITIONS_DIR.glob("*.html")):
            if stale.stem not in due:
                stale.unlink()
                print(f"Withdrew not-yet-due page: editions/{stale.name}")
        if RESEARCH_OUT.exists():
            for stale in sorted(RESEARCH_OUT.glob("*.pdf")):
                if stale.stem not in due:
                    stale.unlink()
                    print(f"Withdrew not-yet-due research: research/{stale.name}")

    index_html = template.render(
        site=SITE,
        edition=latest,
        archive=archive,
        base="",
        is_latest=True,
    )
    (ROOT / "index.html").write_text(index_html, encoding="utf-8")

    # ---- archive, search and learning catalog ----
    docs = search_index(editions)
    (ROOT / "assets" / "search-index.json").write_text(
        json.dumps(docs, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )

    topics = learning_topics(editions)

    pages = {
        "archive.html": ("archive.html.j2", "archive", {"grouped": group_by_month(archive)}),
        "search.html": ("search.html.j2", "search", {}),
        "learn.html": ("learn.html.j2", "learn", {"topics": topics}),
    }
    for out_name, (tpl_name, nav, extra) in pages.items():
        tpl = env.get_template(tpl_name)
        (ROOT / out_name).write_text(
            tpl.render(site=SITE, base="", archive=archive, nav=nav, **extra),
            encoding="utf-8",
        )

    topic_pages = render_topics(env, editions, held_back={e["date"] for e in pending})

    print(f"Built {len(editions)} edition(s).")
    print(f"  index.html -> {latest['date']} (No. {latest['number']})")
    for a in archive:
        print(f"  {a['href']}")
    if pending:
        print(f"Held back {len(pending)} edition(s) not yet due (Asia/Jerusalem {paper_today()}):")
        for e in pending:
            print(f"  {e['date']} (No. {e['number']}) - {e['lead']['headline']}")
    if include_future:
        print("PREVIEW BUILD: future editions are included. Do not commit this output.")
    if research:
        print(f"Published {len(research)} research PDF(s): {', '.join(research)}")
    print(f"Search index: {len(docs)} documents -> assets/search-index.json")
    print(f"Learning catalog: {len(topics)} topic(s) -> learn.html")
    for name in topic_pages:
        print(f"  learn/{name}")
    print("Archive: archive.html")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build the newspaper site.")
    parser.add_argument(
        "--include-future",
        action="store_true",
        help="Also build editions dated after today. Local preview only; the "
             "output must not be committed, because it publishes an edition early.",
    )
    build(include_future=parser.parse_args().include_future)
