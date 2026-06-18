from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class Listing:
    source: str
    source_listing_id: str | None
    url: str
    title: str
    price_pcm: int | None = None
    bedrooms: float | None = None
    postcode: str | None = None
    area: str | None = None
    furnished: str | None = None
    image_url: str | None = None
    description: str = ""
    search_name: str | None = None
    zone_hint: str | None = None
    fetched_at: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    dedupe_key: str | None = None


@dataclass(slots=True)
class FilterDecision:
    accepted: bool
    reasons: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class FetchResult:
    source: str
    fetched: int = 0
    accepted: int = 0
    rejected: int = 0
    errors: list[str] = field(default_factory=list)

