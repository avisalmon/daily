"""Fetch candidate news items for the editorial meeting.

Reads config/sources.yaml, pulls every feed, filters by recency, deduplicates
across outlets, and prints the surviving candidates grouped by source.

Usage:
    python scripts/fetch_news.py --hours 48
    python scripts/fetch_news.py --hours 72 --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ledger  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "config" / "sources.yaml"
CACHE = ROOT / "data" / "_news_cache.json"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) DailyDigest/0.1"

STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
    "is", "are", "was", "were", "its", "it", "as", "at", "by", "from",
    "this", "that", "new", "says", "say", "will",
}


@dataclass
class Item:
    title: str
    url: str
    source: str
    published: str | None
    summary: str
    weight: float
    topics: list[str] = field(default_factory=list)
    dupes: list[str] = field(default_factory=list)
    times_proposed: int = 0


def load_sources() -> list[dict]:
    with SOURCES.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return [s for s in (data.get("sources") or []) if s.get("url")]


def clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", text).strip()


def entry_time(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        parsed = entry.get(key)
        if parsed:
            return datetime.fromtimestamp(time.mktime(parsed), tz=timezone.utc)
    return None


def fetch_one(source: dict, cutoff: datetime, attempts: int = 3) -> tuple[str, list[Item], str | None]:
    """Return (source_name, items, error).

    Retries an empty result. TechCrunch and Ars Technica both returned a
    truncated body once, at the same byte offset, and feedparser reported a
    mismatched tag; both parsed perfectly a second later. Without a retry a
    transient blip silently drops two of the best sources from an editorial
    meeting, and the meeting looks thin for no visible reason.
    """
    name = source.get("name", source["url"])
    last_error = None
    for attempt in range(attempts):
        try:
            parsed = feedparser.parse(source["url"], agent=UA)
            bozo = getattr(parsed, "bozo_exception", None)
            if parsed.entries:
                break
            last_error = f"no entries ({bozo})" if bozo else "no entries"
        except Exception as exc:  # pragma: no cover - network
            last_error = str(exc)
        if attempt < attempts - 1:
            time.sleep(1.5 * (attempt + 1))
    else:
        return name, [], last_error

    items: list[Item] = []
    for entry in parsed.entries:
        when = entry_time(entry)
        if when and when < cutoff:
            continue
        title = clean(entry.get("title", ""))
        link = entry.get("link", "")
        if not title or not link:
            continue
        items.append(
            Item(
                title=title,
                url=link,
                source=name,
                published=when.isoformat() if when else None,
                summary=clean(entry.get("summary", ""))[:400],
                weight=float(source.get("weight", 1.0)),
                topics=list(source.get("topics") or []),
            )
        )
    return name, items, None


def signature(title: str) -> frozenset[str]:
    words = re.findall(r"[a-z0-9]+", title.lower())
    return frozenset(w for w in words if w not in STOPWORDS and len(w) > 2)


def dedupe(items: list[Item]) -> list[Item]:
    """Collapse the same story reported by several outlets.

    Keeps the highest-weighted copy and records the others under `dupes`.
    """
    items = sorted(items, key=lambda i: -i.weight)
    kept: list[tuple[frozenset[str], Item]] = []

    for item in items:
        sig = signature(item.title)
        if not sig:
            kept.append((sig, item))
            continue
        for other_sig, other in kept:
            if not other_sig:
                continue
            overlap = len(sig & other_sig) / min(len(sig), len(other_sig))
            if overlap >= 0.6:
                other.dupes.append(item.source)
                break
        else:
            kept.append((sig, item))
    return [item for _, item in kept]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--hours", type=int, default=48, help="recency window")
    ap.add_argument("--json", action="store_true", help="emit JSON")
    ap.add_argument(
        "--include-published",
        action="store_true",
        help="do not filter out stories already printed (default: filter them)",
    )
    args = ap.parse_args()

    sources = load_sources()
    if not sources:
        print("no sources configured in config/sources.yaml", file=sys.stderr)
        return 1

    cutoff = datetime.now(timezone.utc) - timedelta(hours=args.hours)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda s: fetch_one(s, cutoff), sources))

    all_items: list[Item] = []
    errors: list[tuple[str, str]] = []
    for name, items, err in results:
        if err:
            errors.append((name, err))
        all_items.extend(items)

    deduped = dedupe(all_items)

    led = ledger.load()
    printed = ledger.published_urls(led)
    seen_before = ledger.proposed_counts(led)

    skipped = 0
    if not args.include_published:
        kept = []
        for item in deduped:
            if ledger.normalize_url(item.url) in printed:
                skipped += 1
                continue
            kept.append(item)
        deduped = kept

    for item in deduped:
        item.times_proposed = seen_before.get(ledger.normalize_url(item.url), 0)

    deduped.sort(key=lambda i: (i.published or ""), reverse=True)

    # Always write the cache. record_edition.py --proposed reads this file and
    # docs/RUNBOOK.md tells you to pass it, but nothing ever wrote it, so it sat
    # stale from an earlier day and quietly described the wrong meeting.
    # Written without a BOM: json.loads rejects one.
    payload = json.dumps([asdict(i) for i in deduped], ensure_ascii=False, indent=2)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(payload, encoding="utf-8")

    if args.json:
        print(payload)
        return 0

    print(
        f"window: last {args.hours}h   raw: {len(all_items)}   "
        f"after dedup: {len(deduped)}   already printed (skipped): {skipped}"
    )
    print(f"cache: {len(deduped)} candidates -> {CACHE.relative_to(ROOT)}")
    if errors:
        print("\nFEED ERRORS")
        for name, err in errors:
            print(f"  ! {name}: {err}")

    print()
    for item in deduped:
        when = (item.published or "")[:16].replace("T", " ")
        tag = f"  [+{len(item.dupes)} others]" if item.dupes else ""
        seen = f"  [proposed before x{item.times_proposed}]" if item.times_proposed else ""
        print(f"- {item.title}")
        print(f"  {item.source} | {when}{tag}{seen}")
        print(f"  {item.url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
