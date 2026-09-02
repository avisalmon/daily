"""The humanization rules: this paper must not read or look machine-written.

The tells are consistent and mechanical, so they can be checked mechanically.
`validate.py` runs this over every published string, and the build refuses to
publish a paper that trips it.

    python scripts\\style.py            # check published content
    python scripts\\style.py --verbose  # show every string checked

Scope: **reader-facing content only** - editions, topics, and the rendered
site. Code comments and docstrings are for us, not for the reader, and are
deliberately not policed.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# --- 1. no em dash in prose -------------------------------------------------
# The em dash as a dramatic pause is the single loudest AI tell. Hebrew prose
# has commas, colons and full stops; use them.
#
# An en dash is correct typography for a closed range, and must be tight:
# 2023-2026, פברואר-מרץ. A *spaced* en dash is the prose pause, which is the
# same tell as the em dash.
EM_DASH = re.compile(r"—")
EN_DASH_IN_PROSE = re.compile(r"\s–|–\s")

# --- 2. no emoji, no decorative symbols -------------------------------------
EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF"      # pictographs, emoticons, symbols
    "\u2600-\u27BF"               # misc symbols and dingbats
    "\u2B00-\u2BFF"
    "\uFE0F\u200D]"               # variation selector, ZWJ
)

# Arrows are legitimate *chart* notation (an axis label reading "זמן ←"), but in
# prose or a link they are app decoration. Checked in content only, so the
# diagram markup in the templates is untouched.
ARROW = re.compile("[\u2190-\u21FF\u27F0-\u27FF]")

# --- 3. no AI filler phrases ------------------------------------------------
# Phrases that signal a model reaching for transition rather than saying
# something. Hebrew first, then the English ones that leak through translation.
FILLER_HE = [
    "חשוב לציין",
    "יש לציין",
    "בשורה התחתונה",
    "בעולם של היום",
    "בעידן שבו",
    "אין ספק ש",
    "המהפכה ה",
    "צוללים ל",
    "בואו נצלול",
    "כפי שראינו",
    "לסיכום,",
    "מרתק",
    "פורץ דרך",
    "משנה משחק",
    "טמון בו פוטנציאל",
]
FILLER_EN = [
    "delve into",
    "it's worth noting",
    "it is worth noting",
    "in today's world",
    "game-changer",
    "game changer",
    "revolutionize",
    "seamless",
    "leverage the power",
    "unlock the potential",
    "at the end of the day",
    "moreover,",
    "furthermore,",
]

# --- 4. no "not only X but also Y" ------------------------------------------
NOT_ONLY_HE = re.compile(r"לא רק .{1,60}? אלא גם")
NOT_ONLY_EN = re.compile(r"not only .{1,60}? but also", re.I)

# --- 5. no triple-clause listing rhythm -------------------------------------
# "fast, cheap, and reliable" three-beat cadence, over-used by models.
# Only flagged when it appears more than twice in one field.
TRIPLE = re.compile(r"\b\w+, \w+,? (?:ו|and )\w+\b")


def check_string(s: str, where: str) -> list[str]:
    problems = []

    if EM_DASH.search(s):
        problems.append(f"{where}: em dash in prose ({_excerpt(s, '—')})")

    for m in EN_DASH_IN_PROSE.finditer(s):
        problems.append(f"{where}: en dash outside a number range ({_excerpt(s, '–')})")
        break

    if EMOJI.search(s):
        found = EMOJI.search(s).group(0)
        problems.append(f"{where}: emoji or decorative symbol {found!r}")

    if ARROW.search(s) and "diagram" not in where and "caption" not in where:
        problems.append(f"{where}: arrow glyph {ARROW.search(s).group(0)!r} in content")

    low = s.lower()
    for phrase in FILLER_HE:
        if phrase in s:
            problems.append(f"{where}: filler phrase {phrase!r}")
    for phrase in FILLER_EN:
        if phrase in low:
            problems.append(f"{where}: filler phrase {phrase!r}")

    if NOT_ONLY_HE.search(s) or NOT_ONLY_EN.search(s):
        problems.append(f"{where}: 'not only X but also Y' construction")

    return problems


def _excerpt(s: str, needle: str, width: int = 34) -> str:
    i = s.find(needle)
    start = max(0, i - width)
    return "…" + s[start:i + width].strip() + "…"


def walk(obj, path: str = ""):
    if isinstance(obj, str):
        yield path, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from walk(v, f"{path}.{k}" if path else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk(v, f"{path}[{i}]")


# Fields that are identifiers or machine data, not prose.
SKIP_KEYS = ("url", "slug", "id", "file", "date", "compiled_at", "added_at",
             "claimed_at", "kind", "image", "href", "class", "source_url",
             "archive_url", "recorded_at", "duration")


def check_file(path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    problems = []
    for field, text in walk(data):
        leaf = field.split(".")[-1].split("[")[0]
        if leaf in SKIP_KEYS:
            continue
        problems += check_string(text, f"{path.name} {field}")
    return problems


def check_content() -> list[str]:
    problems = []
    for path in sorted((ROOT / "data" / "editions").glob("*.json")):
        problems += check_file(path)
    for path in sorted((ROOT / "data" / "topics").glob("*.json")):
        problems += check_file(path)
    return problems


def main() -> int:
    problems = check_content()
    if problems:
        print(f"STYLE CHECK FAILED - {len(problems)} problem(s):")
        for p in problems:
            print(f"  - {p}")
        print("\nSee docs/SPEC.md - the paper must not read as machine-written.")
        return 1
    print("Style check passed. No em dashes, no emoji, no filler.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
