from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from .filters import apply_filters
from .models import Listing
from .sources import make_source
from .storage import connect, count_listings, init_db, mark_baseline_seen, pending_notifications, upsert_listing


@dataclass(slots=True)
class RunStats:
    fetched: int = 0
    accepted: int = 0
    rejected: int = 0
    inserted_new: int = 0
    known: int = 0
    price_drops: int = 0
    errors: list[str] = field(default_factory=list)
    reject_reasons: Counter = field(default_factory=Counter)


def fetch_filter_store(
    config: dict,
    *,
    source_filter: str | None = None,
    fetch_detail_pages: bool | None = None,
    progress=None,
) -> RunStats:
    stats = RunStats()
    database_url = config["app"]["database_url"]
    runtime_config = dict(config.get("runtime", {}))
    if fetch_detail_pages is not None:
        runtime_config["fetch_detail_pages"] = fetch_detail_pages
    with connect(database_url) as conn:
        init_db(conn)
        for source_name, source_config in enabled_sources(config, source_filter=source_filter).items():
            if progress:
                progress(f"Checking {source_name}...")
            try:
                source = make_source(source_name, source_config, runtime_config)
                listings = source.fetch()
            except Exception as exc:
                stats.errors.append(f"{source_name}: {exc}")
                if progress:
                    progress(f"{source_name}: error")
                continue
            if progress:
                progress(f"{source_name}: fetched {len(listings)} candidates")
            stats.fetched += len(listings)
            for listing in listings:
                decision = apply_filters(listing, config["criteria"])
                if not decision.accepted:
                    stats.rejected += 1
                    stats.reject_reasons.update(decision.reasons)
                    continue
                stats.accepted += 1
                state = upsert_listing(conn, listing)
                if state == "new":
                    stats.inserted_new += 1
                elif state == "price_drop":
                    stats.price_drops += 1
                else:
                    stats.known += 1
    return stats


def enabled_sources(config: dict, *, source_filter: str | None = None) -> dict:
    return {
        name: source
        for name, source in sorted(
            config.get("sources", {}).items(),
            key=lambda item: int(item[1].get("priority", 100)),
        )
        if source.get("enabled", True)
        and (source_filter is None or name == source_filter)
    }


def baseline_current_listings(
    config: dict,
    *,
    source_filter: str | None = None,
    fetch_detail_pages: bool | None = None,
    progress=None,
) -> tuple[RunStats, int]:
    stats = fetch_filter_store(
        config,
        source_filter=source_filter,
        fetch_detail_pages=fetch_detail_pages,
        progress=progress,
    )
    database_url = config["app"]["database_url"]
    with connect(database_url) as conn:
        pending = pending_notifications(conn)
        ids = [int(item["id"]) for item in pending]
        mark_baseline_seen(conn, ids)
    return stats, len(ids)


def load_pending(config: dict) -> list[dict]:
    database_url = config["app"]["database_url"]
    with connect(database_url) as conn:
        init_db(conn)
        return pending_notifications(conn)


def database_is_empty(config: dict) -> bool:
    database_url = config["app"]["database_url"]
    with connect(database_url) as conn:
        init_db(conn)
        return count_listings(conn) == 0
