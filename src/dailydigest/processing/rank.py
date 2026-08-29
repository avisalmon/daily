"""Relevance ranking and top-N selection. PLACEHOLDER."""

from typing import Any

from ..models import Item


def rank(items: list[Item], cfg: dict[str, Any]) -> list[Item]:
    limit = cfg.get("selection", {}).get("max_items", 10)
    return sorted(items, key=lambda i: i.score, reverse=True)[:limit]
