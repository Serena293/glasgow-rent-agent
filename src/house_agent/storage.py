from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .models import Listing
from .normalise import canonical_url


SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dedupe_key TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    source_listing_id TEXT,
    canonical_url TEXT NOT NULL,
    title TEXT NOT NULL,
    price_pcm INTEGER NOT NULL,
    last_price_pcm INTEGER NOT NULL,
    bedrooms REAL,
    postcode TEXT,
    area TEXT,
    furnished TEXT,
    image_url TEXT,
    description TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    first_sent_at TEXT,
    last_sent_at TEXT,
    last_sent_price_pcm INTEGER,
    baseline_seen_at TEXT,
    raw_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_listings_pending
ON listings(first_sent_at, last_sent_price_pcm, last_price_pcm);

CREATE TABLE IF NOT EXISTS listing_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    source_listing_id TEXT,
    canonical_url TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    UNIQUE(source, canonical_url)
);
"""

POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    id SERIAL PRIMARY KEY,
    dedupe_key TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    source_listing_id TEXT,
    canonical_url TEXT NOT NULL,
    title TEXT NOT NULL,
    price_pcm INTEGER NOT NULL,
    last_price_pcm INTEGER NOT NULL,
    bedrooms DOUBLE PRECISION,
    postcode TEXT,
    area TEXT,
    furnished TEXT,
    image_url TEXT,
    description TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    first_sent_at TEXT,
    last_sent_at TEXT,
    last_sent_price_pcm INTEGER,
    baseline_seen_at TEXT,
    raw_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_listings_pending
ON listings(first_sent_at, last_sent_price_pcm, last_price_pcm);

CREATE TABLE IF NOT EXISTS listing_sources (
    id SERIAL PRIMARY KEY,
    listing_id INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    source_listing_id TEXT,
    canonical_url TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    UNIQUE(source, canonical_url)
);
"""


class Database:
    def __init__(self, raw, kind: str):
        self.raw = raw
        self.kind = kind

    def execute(self, query: str, params=()):
        if self.kind == "postgres":
            query = query.replace("?", "%s")
        return self.raw.execute(query, params)

    def executescript(self, script: str) -> None:
        if self.kind == "sqlite":
            self.raw.executescript(script)
            return
        for statement in script.split(";"):
            statement = statement.strip()
            if statement:
                self.raw.execute(statement)



def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def database_path_from_url(database_url: str) -> Path:
    if not database_url.startswith("sqlite:///"):
        raise ValueError("Only sqlite:/// URLs are supported locally for now.")
    return Path(database_url.replace("sqlite:///", "", 1))


@contextmanager
def connect(database_url: str):
    if is_postgres_url(database_url):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("Postgres support requires psycopg. Run: python -m pip install -e .") from exc
        raw = psycopg.connect(normalize_postgres_url(database_url), row_factory=dict_row)
        conn = Database(raw, "postgres")
    else:
        path = database_path_from_url(database_url)
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = sqlite3.connect(path)
        raw.row_factory = sqlite3.Row
        raw.execute("PRAGMA foreign_keys = ON")
        conn = Database(raw, "sqlite")
    try:
        yield conn
        raw.commit()
    finally:
        raw.close()


def is_postgres_url(database_url: str) -> bool:
    return database_url.startswith(("postgres://", "postgresql://"))


def normalize_postgres_url(database_url: str) -> str:
    if database_url.startswith("postgres://"):
        return "postgresql://" + database_url.removeprefix("postgres://")
    return database_url


def init_db(conn: Database) -> None:
    conn.executescript(POSTGRES_SCHEMA if conn.kind == "postgres" else SQLITE_SCHEMA)


def upsert_listing(conn: Database, listing: Listing, now: datetime | None = None) -> str:
    now = now or utc_now()
    now_iso = now.isoformat()
    url = canonical_url(listing.url)
    raw_json = json.dumps(listing.raw, ensure_ascii=True, sort_keys=True)
    if not listing.dedupe_key:
        raise ValueError(f"Listing missing dedupe_key: {listing.title}")
    existing = conn.execute(
        "SELECT * FROM listings WHERE dedupe_key = ?",
        (listing.dedupe_key,),
    ).fetchone()
    if existing is None:
        values = (
            listing.dedupe_key,
            listing.source,
            listing.source_listing_id,
            url,
            listing.title,
            listing.price_pcm,
            listing.price_pcm,
            listing.bedrooms,
            listing.postcode,
            listing.area,
            listing.furnished,
            listing.image_url,
            listing.description,
            now_iso,
            now_iso,
            raw_json,
        )
        insert_sql = """
        INSERT INTO listings (
            dedupe_key, source, source_listing_id, canonical_url, title,
            price_pcm, last_price_pcm, bedrooms, postcode, area, furnished,
            image_url, description, first_seen_at, last_seen_at, raw_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        if conn.kind == "postgres":
            cursor = conn.execute(insert_sql + " RETURNING id", values)
            listing_id = int(cursor.fetchone()["id"])
        else:
            cursor = conn.execute(insert_sql, values)
            listing_id = int(cursor.lastrowid)
        upsert_listing_source(conn, listing_id, listing, url, now_iso)
        return "new"

    listing_id = int(existing["id"])
    previous_sent_price = existing["last_sent_price_pcm"]
    previous_price = existing["last_price_pcm"]
    conn.execute(
        """
        UPDATE listings
        SET source = ?,
            source_listing_id = ?,
            canonical_url = ?,
            title = ?,
            price_pcm = ?,
            last_price_pcm = ?,
            bedrooms = ?,
            postcode = ?,
            area = ?,
            furnished = ?,
            image_url = ?,
            description = ?,
            last_seen_at = ?,
            raw_json = ?
        WHERE id = ?
        """,
        (
            listing.source,
            listing.source_listing_id,
            url,
            listing.title,
            listing.price_pcm,
            listing.price_pcm,
            listing.bedrooms,
            listing.postcode,
            listing.area,
            listing.furnished,
            listing.image_url,
            listing.description,
            now_iso,
            raw_json,
            listing_id,
        ),
    )
    upsert_listing_source(conn, listing_id, listing, url, now_iso)
    if previous_sent_price is not None and listing.price_pcm is not None and listing.price_pcm < int(previous_sent_price):
        return "price_drop"
    if previous_price is not None and listing.price_pcm is not None and listing.price_pcm != int(previous_price):
        return "price_change"
    return "known"


def upsert_listing_source(
    conn: Database,
    listing_id: int,
    listing: Listing,
    url: str,
    now_iso: str,
) -> None:
    existing = conn.execute(
        "SELECT id FROM listing_sources WHERE source = ? AND canonical_url = ?",
        (listing.source, url),
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE listing_sources SET last_seen_at = ?, source_listing_id = ? WHERE id = ?",
            (now_iso, listing.source_listing_id, int(existing["id"])),
        )
        return
    conn.execute(
        """
        INSERT INTO listing_sources (
            listing_id, source, source_listing_id, canonical_url, first_seen_at, last_seen_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (listing_id, listing.source, listing.source_listing_id, url, now_iso, now_iso),
    )


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict]:
    return [dict(row) for row in rows]


def pending_notifications(conn: Database) -> list[dict]:
    rows = conn.execute(
        """
        SELECT *,
               CASE
                 WHEN first_sent_at IS NULL THEN 'new'
                 WHEN last_sent_price_pcm IS NOT NULL AND last_price_pcm < last_sent_price_pcm THEN 'price_drop'
                 ELSE 'known'
               END AS notification_reason
        FROM listings
        WHERE first_sent_at IS NULL
           OR (last_sent_price_pcm IS NOT NULL AND last_price_pcm < last_sent_price_pcm)
        ORDER BY last_price_pcm ASC, first_seen_at ASC
        """
    ).fetchall()
    return rows_to_dicts(rows)


def mark_sent(conn: Database, listing_ids: list[int], sent_at: datetime | None = None) -> None:
    if not listing_ids:
        return
    sent_at = sent_at or utc_now()
    sent_iso = sent_at.isoformat()
    placeholders = ",".join("?" for _ in listing_ids)
    conn.execute(
        f"""
        UPDATE listings
        SET first_sent_at = COALESCE(first_sent_at, ?),
            last_sent_at = ?,
            last_sent_price_pcm = last_price_pcm
        WHERE id IN ({placeholders})
        """,
        [sent_iso, sent_iso, *listing_ids],
    )


def mark_baseline_seen(conn: Database, listing_ids: list[int], seen_at: datetime | None = None) -> None:
    if not listing_ids:
        return
    seen_at = seen_at or utc_now()
    seen_iso = seen_at.isoformat()
    placeholders = ",".join("?" for _ in listing_ids)
    conn.execute(
        f"""
        UPDATE listings
        SET baseline_seen_at = COALESCE(baseline_seen_at, ?),
            first_sent_at = COALESCE(first_sent_at, ?),
            last_sent_at = COALESCE(last_sent_at, ?),
            last_sent_price_pcm = COALESCE(last_sent_price_pcm, last_price_pcm)
        WHERE id IN ({placeholders})
        """,
        [seen_iso, seen_iso, seen_iso, *listing_ids],
    )


def all_listing_ids(conn: Database) -> list[int]:
    rows = conn.execute("SELECT id FROM listings").fetchall()
    return [int(row["id"]) for row in rows]


def count_listings(conn: Database) -> int:
    row = conn.execute("SELECT COUNT(*) AS count FROM listings").fetchone()
    return int(row["count"])
