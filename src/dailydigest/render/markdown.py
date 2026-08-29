"""Markdown digest renderer using templates/digest.md.j2. PLACEHOLDER."""

from datetime import date as _date
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..models import Item

TEMPLATE_DIR = Path("templates")


def render(items: list[Item], cfg: dict[str, Any], date: str | None = None) -> str:
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("digest.md.j2")
    return template.render(
        title=cfg.get("title", "Daily Digest"),
        date=date or _date.today().isoformat(),
        items=items,
    )
