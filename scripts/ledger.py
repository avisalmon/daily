"""Editorial ledger — what we published, and what we proposed but didn't use.

Two jobs:

1. **Never print the same story twice.** Published URLs are excluded from
   future editorial meetings automatically.
2. **Let good stories come back.** Items proposed but not chosen stay in the
   pool with a counter, so they can resurface on a quiet day instead of being
   lost.

Stored at data/ledger.json. Committed to git — it is editorial history.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "data" / "ledger.json"

_TRACKING_PREFIXES = ("utm_", "fbclid", "gclid", "mc_cid", "mc_eid", "ref")


def normalize_url(url: str) -> str:
    """Strip tracking params and trailing slashes so the same story matches."""
    if not url:
        return ""
    parts = urlsplit(url.strip())
    query = "&".join(
        q
        for q in parts.query.split("&")
        if q and not q.split("=")[0].lower().startswith(_TRACKING_PREFIXES)
    )
    path = parts.path.rstrip("/") or "/"
    netloc = parts.netloc.lower().removeprefix("www.")
    return urlunsplit((parts.scheme.lower(), netloc, path, query, ""))


def _empty() -> dict:
    return {"published": [], "proposed": []}


def load() -> dict:
    if not LEDGER.exists():
        return _empty()
    with LEDGER.open(encoding="utf-8") as fh:
        data = json.load(fh)
    data.setdefault("published", [])
    data.setdefault("proposed", [])
    return data


def save(data: dict) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def published_urls(data: dict | None = None) -> set[str]:
    data = data or load()
    return {normalize_url(e["url"]) for e in data["published"] if e.get("url")}


def proposed_counts(data: dict | None = None) -> dict[str, int]:
    data = data or load()
    return {
        normalize_url(e["url"]): e.get("times_proposed", 1)
        for e in data["proposed"]
        if e.get("url")
    }


def record_proposed(items: list[dict]) -> dict:
    """Add candidates shown at an editorial meeting. Increments repeat counts."""
    data = load()
    index = {normalize_url(e["url"]): e for e in data["proposed"] if e.get("url")}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for item in items:
        key = normalize_url(item.get("url", ""))
        if not key:
            continue
        if key in index:
            index[key]["times_proposed"] = index[key].get("times_proposed", 1) + 1
            index[key]["last_proposed"] = now
        else:
            entry = {
                "url": item["url"],
                "title": item.get("title", ""),
                "source": item.get("source", ""),
                "first_proposed": now,
                "last_proposed": now,
                "times_proposed": 1,
            }
            data["proposed"].append(entry)
            index[key] = entry

    save(data)
    return data


def record_published(items: list[dict], edition_date: str) -> dict:
    """Mark items as printed. They are removed from the proposed pool."""
    data = load()
    already = published_urls(data)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for item in items:
        key = normalize_url(item.get("url", ""))
        if not key or key in already:
            continue
        data["published"].append(
            {
                "url": item["url"],
                "title": item.get("title", ""),
                "title_he": item.get("title_he", ""),
                "source": item.get("source", ""),
                "edition_date": edition_date,
                "recorded_at": now,
            }
        )
        already.add(key)

    printed = published_urls(data)
    data["proposed"] = [
        e for e in data["proposed"] if normalize_url(e.get("url", "")) not in printed
    ]

    save(data)
    return data


if __name__ == "__main__":
    d = load()
    print(f"published: {len(d['published'])}")
    print(f"proposed pool: {len(d['proposed'])}")
    for e in sorted(d["published"], key=lambda x: x.get("edition_date", ""), reverse=True)[:20]:
        print(f"  {e.get('edition_date')}  {e.get('title', '')[:70]}")
