"""Pipeline orchestration: fetch -> normalize -> dedup -> filter -> rank -> summarize -> render -> deliver.

PLACEHOLDER — each stage currently a no-op stub.
"""

from typing import Any

from .delivery import deliver
from .processing import dedup, filters, rank, summarize
from .render import markdown
from .sources import registry


def run_pipeline(cfg: dict[str, Any], date: str | None = None, dry_run: bool = False) -> str:
    items = registry.fetch_all(cfg)
    items = dedup.dedup(items)
    items = filters.apply(items, cfg)
    items = rank.rank(items, cfg)
    items = summarize.summarize(items, cfg)
    digest = markdown.render(items, cfg, date=date)

    if dry_run:
        return f"[dry-run] {len(items)} items; digest not delivered."

    deliver.send(digest, cfg)
    return f"Delivered digest with {len(items)} items."
