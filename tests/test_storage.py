from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from house_agent.filters import ensure_dedupe_key
from house_agent.models import Listing
from house_agent.storage import connect, init_db, mark_baseline_seen, pending_notifications, upsert_listing


class StorageTests(unittest.TestCase):
    def test_baseline_suppresses_existing_listing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_url = f"sqlite:///{Path(temp_dir) / 'test.sqlite3'}"
            listing = Listing(
                source="test",
                source_listing_id="1",
                url="https://example.test/1",
                title="1 bed furnished flat G11",
                price_pcm=850,
                bedrooms=1,
                zone_hint="G11",
            )
            ensure_dedupe_key(listing)

            with connect(db_url) as conn:
                init_db(conn)
                upsert_listing(conn, listing)
                pending = pending_notifications(conn)
                self.assertEqual(len(pending), 1)
                mark_baseline_seen(conn, [int(pending[0]["id"])])
                self.assertEqual(pending_notifications(conn), [])

    def test_price_drop_after_baseline_is_pending(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_url = f"sqlite:///{Path(temp_dir) / 'test.sqlite3'}"
            listing = Listing(
                source="test",
                source_listing_id="1",
                url="https://example.test/1",
                title="1 bed furnished flat G11",
                price_pcm=850,
                bedrooms=1,
                zone_hint="G11",
            )
            ensure_dedupe_key(listing)

            with connect(db_url) as conn:
                init_db(conn)
                upsert_listing(conn, listing)
                pending = pending_notifications(conn)
                mark_baseline_seen(conn, [int(pending[0]["id"])])

            listing.price_pcm = 800
            ensure_dedupe_key(listing)
            with connect(db_url) as conn:
                upsert_listing(conn, listing)
                pending = pending_notifications(conn)
                self.assertEqual(len(pending), 1)
                self.assertEqual(pending[0]["notification_reason"], "price_drop")


if __name__ == "__main__":
    unittest.main()
