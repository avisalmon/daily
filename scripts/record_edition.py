"""Record an edition's decisions into the editorial ledger.

Marks the chosen briefs as published (so they can never be printed twice) and
adds every candidate shown at the meeting to the proposed pool (so good stories
that were passed over can resurface later).

    python scripts/record_edition.py 2026-08-30
    python scripts/record_edition.py 2026-08-30 --proposed data/_news_cache.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ledger  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PLANS = ROOT / "data" / "plans"


def read_json(path: Path):
    raw = path.read_bytes()
    encoding = "utf-16" if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig"
    return json.loads(raw.decode(encoding))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("date", help="edition date, e.g. 2026-08-30")
    ap.add_argument(
        "--proposed",
        help="optional JSON array of every candidate shown at the meeting",
    )
    args = ap.parse_args()

    plan_path = PLANS / f"{args.date}.plan.json"
    if not plan_path.exists():
        print(f"no plan at {plan_path}", file=sys.stderr)
        return 1

    plan = read_json(plan_path)

    if args.proposed:
        candidates = read_json(Path(args.proposed))
        ledger.record_proposed(candidates)
        print(f"recorded {len(candidates)} proposed candidate(s)")

    briefs = plan.get("briefs", [])
    ledger.record_published(briefs, args.date)
    print(f"recorded {len(briefs)} published item(s) for {args.date}")

    data = ledger.load()
    print(f"ledger now: {len(data['published'])} published, {len(data['proposed'])} in pool")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
