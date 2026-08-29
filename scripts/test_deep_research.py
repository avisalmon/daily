"""Verify the OpenAI deep-research setup and report real token cost.

Runs one small deep-research job end to end so we know the key works, the
model is reachable, and what a run actually costs before committing to a
daily schedule.

    .\.venv\Scripts\python.exe scripts\test_deep_research.py
    .\.venv\Scripts\python.exe scripts\test_deep_research.py "your topic here"

The key is read from .env (OPENAI_API_KEY) and never printed.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parent.parent

# USD per 1M tokens. Update if OpenAI changes pricing.
PRICING = {
    "o4-mini-deep-research": {"input": 2.00, "output": 8.00},
    "o3-deep-research": {"input": 10.00, "output": 40.00},
}

DEFAULT_TOPIC = (
    "What actually changed in consumer electric vehicle battery technology "
    "in the last 12 months? Focus on shipping products, not announcements."
)


def main() -> int:
    load_dotenv(ROOT / ".env")

    key = os.getenv("OPENAI_API_KEY")
    if not key:
        print("OPENAI_API_KEY is not set. Add it to .env first.")
        return 1

    model = os.getenv("DEEP_RESEARCH_MODEL", "o4-mini-deep-research")
    topic = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TOPIC

    print(f"model: {model}")
    print(f"topic: {topic[:80]}...")
    print("submitting (this takes several minutes)...\n")

    client = OpenAI(api_key=key, timeout=3600)
    started = time.time()

    response = client.responses.create(
        model=model,
        input=(
            f"{topic}\n\n"
            "Be analytical and specific. Include figures and dates. "
            "Prioritize primary and reputable sources. "
            "Include inline citations and return all source metadata."
        ),
        background=True,
        tools=[{"type": "web_search_preview"}],
    )

    # Poll until the background job finishes.
    while response.status in ("queued", "in_progress"):
        time.sleep(10)
        response = client.responses.retrieve(response.id)
        print(f"  [{int(time.time() - started):>4}s] {response.status}")

    elapsed = time.time() - started
    print(f"\nstatus: {response.status}  ({elapsed / 60:.1f} min)")

    if response.status != "completed":
        print(f"failed: {getattr(response, 'error', 'unknown error')}")
        return 1

    text = response.output_text or ""

    # Count distinct cited sources from the annotation metadata.
    urls: set[str] = set()
    for item in response.output or []:
        for content in getattr(item, "content", []) or []:
            for ann in getattr(content, "annotations", []) or []:
                url = getattr(ann, "url", None)
                if url:
                    urls.add(url)

    usage = response.usage
    cost = None
    if usage and model in PRICING:
        p = PRICING[model]
        cost = (usage.input_tokens / 1e6) * p["input"] + (
            usage.output_tokens / 1e6
        ) * p["output"]

    print("-" * 60)
    print(f"report length : {len(text):,} chars")
    print(f"cited sources : {len(urls)}")
    if usage:
        print(f"input tokens  : {usage.input_tokens:,}")
        print(f"output tokens : {usage.output_tokens:,}")
    if cost is not None:
        print(f"ESTIMATED COST: ${cost:.2f}   (~${cost * 30:.0f}/month daily)")
    print("-" * 60)

    out = ROOT / "data" / "raw" / "deep_research_test.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"\nreport saved -> {out}")
    print("\nfirst 600 chars:\n")
    print(text[:600])

    return 0


if __name__ == "__main__":
    sys.exit(main())
