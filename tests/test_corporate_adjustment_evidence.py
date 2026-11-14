"""Corporate event evidence and price adjustment boundaries."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from audit_corporate_price_events import research_event


class CorporateAdjustmentEvidenceTests(unittest.TestCase):
    def test_reference_match_does_not_create_adjusted_or_total_return(self):
        event = {"market": "TWSE", "code": "2330", "exDate": "2026-07-08",
                 "type": "息", "previousClose": 100, "referencePrice": 97,
                 "referenceRatio": 0.97}
        result = research_event(event, "2026-07-07", 100, 99, tolerance=0.011)
        self.assertTrue(result["exchangeReference"]["storedRatioConsistent"])
        self.assertEqual(result["rawPrice"]["eventClose"], 99)
        self.assertIsNone(result["adjustedPrice"]["factor"])
        self.assertIsNone(result["adjustedPrice"]["priceReturn"])
        self.assertIsNone(result["reinvestedTotalReturn"])
        self.assertIsNone(result["announcementDate"])
        self.assertEqual(result["status"], "adjustment_blocked")

    def test_mismatched_reference_and_missing_quote_report_separate_errors(self):
        event = {"market": "TPEX", "code": "6488", "exDate": "2026-07-08",
                 "type": "權息", "previousClose": 100, "referencePrice": 80,
                 "referenceRatio": 0.9}
        result = research_event(event, "2026-07-07", 95, None, tolerance=0.011)
        self.assertIn("prior_close_mismatch", result["issues"])
        self.assertIn("event_quote_missing", result["issues"])
        self.assertIn("reference_ratio_inconsistent", result["issues"])

    def test_missing_prior_quote_is_never_filled_with_reference(self):
        event = {"market": "TPEX", "code": "6488", "exDate": "2026-07-08",
                 "type": "權", "previousClose": 100, "referencePrice": 80,
                 "referenceRatio": 0.8}
        result = research_event(event, None, None, 80, tolerance=0.011)
        self.assertIn("prior_quote_missing", result["issues"])
        self.assertIsNone(result["rawPrice"]["previousClose"])
        self.assertIsNone(result["adjustedPrice"]["previousClose"])
