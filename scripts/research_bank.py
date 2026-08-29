"""The research bank — a pool of deep researches waiting for an edition.

Drop any PDF into data/research/bank/ with any filename. This script reads it,
records what it is, and makes it available as a lead candidate at the next
editorial meeting.

A research in the bank is *undated*. It becomes dated only when you choose it
for an edition, at which point `use` copies it into place under the name the
build expects.

    python scripts\\research_bank.py                    # list the bank
    python scripts\\research_bank.py scan               # re-read the folder
    python scripts\\research_bank.py show <id>          # extracted text preview
    python scripts\\research_bank.py use <id> <date>    # claim it for an edition

The PDFs themselves are gitignored (they are inputs, often large). The index is
committed, so the bank survives a fresh clone even if the files don't.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BANK_DIR = ROOT / "data" / "research" / "bank"
RESEARCH_DIR = ROOT / "data" / "research"
INDEX = RESEARCH_DIR / "bank.json"

HEBREW = re.compile(r"[\u0590-\u05FF]")


# ---------------------------------------------------------------------------
# reading a PDF
# ---------------------------------------------------------------------------

def _read_pdf(path: Path) -> tuple[str, int]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages = len(reader.pages)
    chunks = []
    for page in reader.pages[:6]:
        try:
            chunks.append(page.extract_text() or "")
        except Exception:
            continue
    return "\n".join(chunks), pages


def _guess_title(text: str, fallback: str) -> str:
    """The first substantial line is almost always the title."""
    for raw in text.splitlines():
        line = " ".join(raw.split())
        if len(line) < 8 or len(line) > 140:
            continue
        # Skip page furniture.
        if re.fullmatch(r"[\d\s\.\-–—|]+", line):
            continue
        if line.lower().startswith(("page ", "http", "www.", "doi:")):
            continue
        return line
    return fallback


def _slugify(title: str) -> str:
    """ASCII slug. Hebrew titles have no useful transliteration, so they fall
    back to the filename - the slug is only a handle, never displayed."""
    ascii_only = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_only.lower()).strip("-")
    return slug[:60] or "research"


def _summarize(text: str, limit: int = 320) -> str:
    body = " ".join(text.split())
    return body[:limit] + ("…" if len(body) > limit else "")


# ---------------------------------------------------------------------------
# the index
# ---------------------------------------------------------------------------

def load() -> dict:
    if not INDEX.exists():
        return {"items": []}
    data = json.loads(INDEX.read_text(encoding="utf-8"))
    data.setdefault("items", [])
    return data


def save(data: dict) -> None:
    INDEX.parent.mkdir(parents=True, exist_ok=True)
    data["items"].sort(key=lambda i: (i.get("used_in") or "9999", i.get("added_at", "")))
    INDEX.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def scan(verbose: bool = True) -> dict:
    """Read every PDF in the bank folder. Existing entries keep their metadata
    so hand-written notes and titles are never overwritten."""
    BANK_DIR.mkdir(parents=True, exist_ok=True)
    data = load()
    by_file = {i["file"]: i for i in data["items"]}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    found = 0
    for pdf in sorted(BANK_DIR.glob("*.pdf")):
        found += 1
        name = pdf.name
        if name in by_file:
            by_file[name]["missing"] = False
            continue

        try:
            text, pages = _read_pdf(pdf)
        except Exception as exc:
            if verbose:
                print(f"  ! {name}: unreadable ({exc})")
            continue

        title = _guess_title(text, pdf.stem)
        entry = {
            "id": _slugify(title if not HEBREW.search(title) else pdf.stem),
            "file": name,
            "title": title,
            "language": "he" if HEBREW.search(text) else "en",
            "pages": pages,
            "words": len(text.split()),
            "extractable": bool(text.strip()),
            "preview": _summarize(text),
            "added_at": now,
            "used_in": None,
            "notes": "",
        }

        existing_ids = {i["id"] for i in data["items"]}
        if entry["id"] in existing_ids:
            entry["id"] = f"{entry['id']}-{len(data['items']) + 1}"

        data["items"].append(entry)
        by_file[name] = entry
        if verbose:
            flag = "" if entry["extractable"] else "  (NO TEXT - scanned PDF?)"
            print(f"  + {entry['id']}  {entry['pages']}pp  {entry['title'][:60]}{flag}")

    # Flag entries whose file is gone rather than deleting - the record of what
    # was published must survive the file.
    for item in data["items"]:
        item["missing"] = not (BANK_DIR / item["file"]).exists()

    save(data)
    if verbose:
        avail = [i for i in data["items"] if not i["used_in"] and not i["missing"]]
        print(f"Bank: {found} file(s) on disk, {len(avail)} available, "
              f"{len(data['items']) - len(avail)} used or missing.")
    return data


def available(data: dict | None = None) -> list[dict]:
    data = data or load()
    return [i for i in data["items"] if not i.get("used_in") and not i.get("missing")]


def find(item_id: str, data: dict | None = None) -> dict | None:
    data = data or load()
    for item in data["items"]:
        if item["id"] == item_id:
            return item
    return None


def use(item_id: str, edition_date: str) -> Path:
    """Claim a bank item for an edition and put the PDF where the build expects."""
    try:
        date.fromisoformat(edition_date)
    except ValueError:
        raise SystemExit(f"{edition_date!r} is not an ISO date (YYYY-MM-DD)")

    data = load()
    item = find(item_id, data)
    if not item:
        raise SystemExit(f"No bank item {item_id!r}. Run: python scripts\\research_bank.py")
    if item.get("used_in"):
        raise SystemExit(f"{item_id!r} was already used in {item['used_in']}")

    src = BANK_DIR / item["file"]
    if not src.exists():
        raise SystemExit(f"{src} is missing - the PDF was moved or deleted")

    dest = RESEARCH_DIR / f"{edition_date}-{item['id']}.pdf"
    shutil.copy2(src, dest)

    item["used_in"] = edition_date
    item["claimed_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    save(data)

    print(f"Claimed {item_id!r} for {edition_date}")
    print(f"  {src.name}  ->  data/research/{dest.name}")
    print("  Next: write the lead into data/editions/%s.json, then build." % edition_date)
    return dest


# ---------------------------------------------------------------------------

def _print_bank() -> None:
    data = scan(verbose=False)
    avail = available(data)
    used = [i for i in data["items"] if i.get("used_in")]

    if not data["items"]:
        print("The bank is empty.")
        print(f"Drop PDFs into {BANK_DIR.relative_to(ROOT)} and run this again.")
        return

    print(f"AVAILABLE ({len(avail)})")
    for i in avail:
        warn = "" if i["extractable"] else "   [NO TEXT LAYER]"
        print(f"  {i['id']}")
        print(f"      {i['title'][:74]}")
        print(f"      {i['pages']}pp · {i['words']:,} words · {i['language']}{warn}")
        if i.get("notes"):
            print(f"      note: {i['notes']}")

    if used:
        print(f"\nUSED ({len(used)})")
        for i in used:
            print(f"  {i['used_in']}  {i['id']}  {i['title'][:50]}")

    missing = [i for i in data["items"] if i.get("missing") and not i.get("used_in")]
    if missing:
        print(f"\nMISSING FILE ({len(missing)})")
        for i in missing:
            print(f"  {i['id']}  (expected {i['file']})")


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "list"

    if cmd in ("list", "ls"):
        _print_bank()
    elif cmd == "scan":
        scan()
    elif cmd == "show":
        if len(argv) < 2:
            raise SystemExit("usage: research_bank.py show <id>")
        item = find(argv[1])
        if not item:
            raise SystemExit(f"No bank item {argv[1]!r}")
        print(json.dumps(item, ensure_ascii=False, indent=2))
        pdf = BANK_DIR / item["file"]
        if pdf.exists():
            text, _ = _read_pdf(pdf)
            print("\n--- extracted text (first 1500 chars) ---")
            print(" ".join(text.split())[:1500])
    elif cmd == "use":
        if len(argv) < 3:
            raise SystemExit("usage: research_bank.py use <id> <YYYY-MM-DD>")
        use(argv[1], argv[2])
    else:
        raise SystemExit(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
