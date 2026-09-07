"""Render a research reference document to PDF.

The paper stopped republishing the deep-research PDF it was handed. That
document arrives branded, in the wrong direction for Hebrew, and containing
errors this desk has already checked and rejected. Reprinting it would mean
citing, as the article's reference, a document the article disagrees with.

So the paper writes its own. Source lives in `data/research/<date>.doc.json`,
renders through `templates/research.html.j2`, and prints through headless
Chrome, which is the only thing on this machine that lays out Hebrew properly.

    python scripts/research_doc.py 2026-09-07

The original stays in git history and in data/research/ on disk. It is not
published, which is the point, but it is not destroyed either.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "data" / "research"
OUT = ROOT / "research"
TEMPLATES = ROOT / "templates"

CHROME_CANDIDATES = [
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path("/usr/bin/google-chrome"),
    Path("/usr/bin/chromium"),
]


def find_chrome() -> Path:
    for c in CHROME_CANDIDATES:
        if c.exists():
            return c
    found = shutil.which("chrome") or shutil.which("chromium") or shutil.which("msedge")
    if found:
        return Path(found)
    raise SystemExit(
        "No Chrome or Edge found. Headless Chrome is what lays out the Hebrew; "
        "there is no fallback that gets RTL right."
    )


def count_words(doc: dict) -> int:
    """Words in the body, which is what the edition byline claims. Headings and
    the source list are excluded: the byline says how much there is to read."""
    text: list[str] = []
    for section in doc["sections"]:
        for block in section["blocks"]:
            if block["kind"] in {"p", "quote", "note"}:
                text.append(block["text"])
            elif block["kind"] == "list":
                text.extend(block["items"])
    joined = " ".join(text)
    return len(re.findall(r"[^\s]+", joined))


def render_html(doc: dict) -> str:
    env = Environment(
        loader=FileSystemLoader(TEMPLATES),
        autoescape=True,
        undefined=StrictUndefined,
    )
    env.globals["word_count"] = count_words(doc)
    return env.get_template("research.html.j2").render(doc=doc)


def print_pdf(html: str, out_pdf: Path) -> None:
    chrome = find_chrome()
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        page = tmp_path / "doc.html"
        page.write_text(html, encoding="utf-8")
        profile = tmp_path / "profile"

        cmd = [
            str(chrome),
            "--headless=new",
            "--disable-gpu",
            f"--user-data-dir={profile}",
            "--no-first-run",
            "--no-pdf-header-footer",
            "--run-all-compositor-stages-before-draw",
            "--virtual-time-budget=20000",
            f"--print-to-pdf={out_pdf}",
            page.as_uri(),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=180)
        if not out_pdf.exists() or out_pdf.stat().st_size == 0:
            raise SystemExit(
                f"Chrome produced no PDF.\n{result.stdout}\n{result.stderr}"
            )


def page_count(pdf: Path) -> int:
    from pypdf import PdfReader

    return len(PdfReader(str(pdf)).pages)


def build(date: str, keep_html: Path | None = None) -> dict:
    src = DOCS / f"{date}.doc.json"
    if not src.exists():
        raise SystemExit(f"No document source at {src}")

    doc = json.loads(src.read_text(encoding="utf-8"))
    html = render_html(doc)
    if keep_html:
        keep_html.write_text(html, encoding="utf-8")

    OUT.mkdir(exist_ok=True)
    out_pdf = OUT / f"{date}.pdf"
    print_pdf(html, out_pdf)

    stats = {
        "pdf": str(out_pdf.relative_to(ROOT)),
        "pages": page_count(out_pdf),
        "words": count_words(doc),
        "bytes": out_pdf.stat().st_size,
    }
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("date", help="edition date, YYYY-MM-DD")
    ap.add_argument("--html", type=Path, help="also write the intermediate HTML here")
    args = ap.parse_args()

    stats = build(args.date, keep_html=args.html)
    print(f"{stats['pdf']}  {stats['pages']} pages  "
          f"{stats['words']:,} words  {stats['bytes']:,} bytes")
    print()
    print("Byline for the edition JSON (BKM 13: these are derived, so pin them):")
    print(f'  "source": "מחקר עומק · {stats["pages"]} עמודים · '
          f'{stats["words"]:,} מילים"')


if __name__ == "__main__":
    main()
