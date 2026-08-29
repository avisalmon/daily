"""Write the digest to output/digests/. """

from datetime import date as _date
from pathlib import Path
from typing import Any

OUTPUT_DIR = Path("output/digests")


def send(digest: str, cfg: dict[str, Any]) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"digest-{_date.today().isoformat()}.md"
    path.write_text(digest, encoding="utf-8")
    return path
