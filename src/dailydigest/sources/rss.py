"""RSS/Atom source fetcher. PLACEHOLDER."""

from typing import Any

from ..models import Item


def fetch(source: dict[str, Any]) -> list[Item]:
    raise NotImplementedError("RSS fetcher not implemented yet")
