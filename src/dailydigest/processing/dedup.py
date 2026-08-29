"""Near-duplicate removal across sources. PLACEHOLDER."""

from ..models import Item


def dedup(items: list[Item]) -> list[Item]:
    seen: set[str] = set()
    out: list[Item] = []
    for item in items:
        if item.url in seen:
            continue
        seen.add(item.url)
        out.append(item)
    return out
