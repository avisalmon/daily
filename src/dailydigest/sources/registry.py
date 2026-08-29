"""Source registry. Register a fetcher per source type."""

from typing import Any, Callable

from ..models import Item
from . import rss, web

FETCHERS: dict[str, Callable[[dict[str, Any]], list[Item]]] = {
    "rss": rss.fetch,
    "web": web.fetch,
}


def fetch_all(cfg: dict[str, Any]) -> list[Item]:
    items: list[Item] = []
    for source in cfg.get("sources", []):
        if not source.get("enabled", True):
            continue
        fetcher = FETCHERS.get(source.get("type"))
        if fetcher is None:
            continue
        items.extend(fetcher(source))
    return items
