"""Corporate reference previous close is not adjusted or total-return history."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"scripts"))
import audit_corporate_price_events as validator


def event(day, prev=100):
    return {"market": "TWSE", "code": "2330", "exDate": day,
            "previousClose": prev, "referencePrice": 95., "referenceRatio": .95}


def snap(day, close):
    return {"asOf": day, "closes": {("TWSE", "2330"): close}}


class CorporatePriceEventCrosscheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.daily = self.root/"daily"
        self.research = self.root/"history"
        self.events = self.root/"corporate"
        for p in (self.daily, self.research, self.events):
            p.mkdir()
        (self.research/"2026-11-11.json.gz").write_bytes(b"fixture")
        (self.daily/"2026-11-12.json.gz").write_bytes(b"fixture")
        (self.daily/"2026-11-13.json.gz").write_bytes(b"fixture")

    def tearDown(self):
        self.tmp.cleanup()

    def invoke(self, events):
        def loader(path, *, historical):
            d = path.name[:10]
            return snap(d, 100 if d == "2026-11-11" else 95)
        with (patch.object(validator, "load_snapshot", side_effect=loader),
              patch.object(validator, "load_events", return_value=events)):
            return validator.audit(self.daily, self.research, self.events)

    def test_previous_close_match_does_not_enable_trading(self):
        result = self.invoke([event("2026-11-12")])
        self.assertEqual(result["eventsInsidePriceRange"], 1)
        self.assertEqual(result["priorRawCloseMatchesReferencePreviousClose"], 1)
        self.assertFalse(result["corporateActionsCheckedForTrading"])
        self.assertFalse(result["priceSeriesAdjustedForCashAndStockDividends"])
        self.assertFalse(result["publishable"])
        self.assertIsNone(result["top10"])

    def test_prior_close_difference_reported_not_rewritten(self):
        result = self.invoke([event("2026-11-12", prev=99)])
        self.assertEqual(len(result["samplePriorCloseDifferences"]), 1)
        self.assertEqual(result["priorRawCloseMatchesReferencePreviousClose"], 0)
        self.assertEqual(result["samplePriorCloseDifferences"][0]["observedPriorClose"], 100)

    def test_outside_price_range_is_not_assumed_adjacent(self):
        result = self.invoke([event("2026-10-01")])
        self.assertEqual(result["eventsOutsidePriceRange"], 1)
        self.assertEqual(result["eventsInsidePriceRange"], 0)

    def test_event_day_missing_from_archived_prices(self):
        result = self.invoke([event("2026-11-12"), event("2026-11-10")])
        self.assertEqual(result["eventsInsidePriceRange"], 1)
        self.assertEqual(result["eventsOutsidePriceRange"], 1)

    def test_overlap_across_price_sources_rejected(self):
        (self.research/"2026-11-12.json.gz").write_bytes(b"fixture")
        with self.assertRaisesRegex(validator.EventPriceError, "overlapping_price_sources"):
            self.invoke([event("2026-11-12")])

    def test_zero_events_rejected(self):
        with self.assertRaisesRegex(validator.EventPriceError, "zero_official_corporate_events"):
            self.invoke([])


if __name__ == "__main__":
    unittest.main()
