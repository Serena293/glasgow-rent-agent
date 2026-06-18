from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from house_agent.filters import apply_filters
from house_agent.models import Listing


CRITERIA = {
    "max_price_pcm": 900,
    "min_bedrooms": 1,
    "property_kinds": ["flat", "apartment"],
    "furnishing": {"accepted": ["furnished", "part-furnished"], "reject_unknown": True},
    "allowed_locations": {
        "postcodes": ["G11", "G3 8", "G41"],
        "area_terms": ["Partick", "Finnieston", "Shawlands", "Strathbungo"],
    },
    "exclude_keywords": ["student-only", "sublet", "unfurnished", "house share"],
}


class FilterTests(unittest.TestCase):
    def test_accepts_part_furnished_g11_flat(self):
        listing = Listing(
            source="test",
            source_listing_id="1",
            url="https://example.test/1",
            title="1 bed flat in Partick G11",
            price_pcm=850,
            bedrooms=1,
            description="Part-furnished flat close to subway.",
            zone_hint="G11",
        )

        decision = apply_filters(listing, CRITERIA)

        self.assertTrue(decision.accepted)
        self.assertTrue(listing.dedupe_key)

    def test_rejects_student_only(self):
        listing = Listing(
            source="test",
            source_listing_id="2",
            url="https://example.test/2",
            title="1 bed flat in G41",
            price_pcm=800,
            bedrooms=1,
            description="Furnished student-only property.",
            zone_hint="G41",
        )

        decision = apply_filters(listing, CRITERIA)

        self.assertFalse(decision.accepted)
        self.assertTrue(any("student" in reason for reason in decision.reasons))

    def test_rejects_g3_when_not_g3_8_without_area_term(self):
        listing = Listing(
            source="test",
            source_listing_id="3",
            url="https://example.test/3",
            title="1 bed flat G3 7AB",
            price_pcm=850,
            bedrooms=1,
            description="Furnished apartment.",
            postcode="G3 7AB",
        )

        decision = apply_filters(listing, CRITERIA)

        self.assertFalse(decision.accepted)
        self.assertIn("outside configured postcodes/areas", decision.reasons)


if __name__ == "__main__":
    unittest.main()
