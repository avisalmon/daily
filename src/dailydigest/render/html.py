"""HTML/email renderer using templates/digest.html.j2. PLACEHOLDER."""

from typing import Any

from ..models import Item


def render(items: list[Item], cfg: dict[str, Any], date: str | None = None) -> str:
    raise NotImplementedError("HTML renderer not implemented yet")
