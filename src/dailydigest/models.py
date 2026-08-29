"""Canonical data model for a digest item.

PLACEHOLDER — fields will firm up once docs/SPEC.md is filled in.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class Item(BaseModel):
    id: str
    title: str
    url: str
    source: str
    published_at: datetime | None = None
    author: str | None = None
    raw_text: str | None = None
    summary: str | None = None
    topics: list[str] = Field(default_factory=list)
    score: float = 0.0


class Digest(BaseModel):
    date: str
    title: str
    sections: dict[str, list[Item]] = Field(default_factory=dict)
