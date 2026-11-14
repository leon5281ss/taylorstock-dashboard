"""Document-based disclosure matching and time gating."""
from datetime import datetime
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from corporate_action_disclosure import compare


class DisclosureTests(unittest.TestCase):
    def test_tsmc_2026_june_exchange_and_issuer_partial_match(self):
        event = dict(market="TWSE", code="2330", kind="cashDividend",
                     exDate="2026-06-11", effectiveDate="2026-06-11")
        issuer = dict(event, source="https://investor.tsmc.com/chinese/dividends",
                      terms={"paymentDate": "2026-07-09"})
        exchange = dict(event, source="https://wwwc.twse.com.tw/staticFiles/news/news/"
                        "tsecnews/8a8216d69e6379f4019eb0d03b0101de.pdf")
        result = compare(issuer, exchange,
                         evaluated_at=datetime.fromisoformat("2026-06-11T09:00:00+08:00"))
        self.assertEqual(result["effectiveDate"], "2026-06-11")
        self.assertEqual(result["status"], "blocked")
        self.assertIn("announcement_time_unverified", result["issues"])
        self.assertIn("missing_cashPerShareTwd", result["issues"])
        self.assertIsNone(result["candidateAdjustmentFactor"])
        self.assertIsNone(result["reinvestedTotalReturn"])

    def test_future_disclosure_and_different_terms_are_blocked(self):
        event = dict(market="TPEX", code="1234", kind="reverseSplit",
                     exDate="2026-06-11", effectiveDate="2026-06-11")
        issuer = dict(event, source="https://example.com/issuer",
                      announcedAt="2026-06-10T16:00:00+08:00",
                      terms={"newSharesPerOldShare": "0.5"})
        exchange = dict(event, source="https://example.org/exchange",
                        terms={"newSharesPerOldShare": "0.25"})
        result = compare(issuer, exchange,
                         evaluated_at=datetime.fromisoformat("2026-06-10T13:30:00+08:00"))
        self.assertIn("announcement_after_evaluation", result["issues"])
        self.assertIn("mismatch_newSharesPerOldShare", result["issues"])
        self.assertFalse(result["publishable"])
