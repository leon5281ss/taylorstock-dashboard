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
        issuer = dict(event, source="https://pr.tsmc.com/english/news/3287", documentId="3287",
                      terms={"paymentDate": "2026-07-09", "recordDate": "2026-06-17",
                             "cashPerShareTwd": "6.00"})
        exchange = dict(event, documentId="8a8216d69e6379f4019eb0d03b0101de", source="https://wwwc.twse.com.tw/staticFiles/news/news/"
                        "tsecnews/8a8216d69e6379f4019eb0d03b0101de.pdf")
        result = compare(issuer, exchange,
                         evaluated_at=datetime.fromisoformat("2026-06-11T09:00:00+08:00"))
        self.assertEqual(result["effectiveDate"], "2026-06-11")
        self.assertEqual(result["status"], "blocked")
        self.assertIn("issuer_announcement_time_unverified", result["issues"])
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
        self.assertIn("issuer_announcement_after_evaluation", result["issues"])
        self.assertIn("mismatch_newSharesPerOldShare", result["issues"])
        self.assertFalse(result["publishable"])

    def test_document_identity_and_both_release_times(self):
        event = dict(market="TWSE", code="2330", kind="cashDividend",
                     exDate="2026-06-11", effectiveDate="2026-06-11", terms=[])
        issuer = dict(event, source="https://pr.tsmc.com.attacker.invalid/english/news/3287",
                      documentId="3287", announcedAt="2026-06-10T16:00:00")
        exchange = dict(event, documentId="8a8216d69e6379f4019eb0d03b0101de",
                        source="https://wwwc.twse.com.tw/staticFiles/news/news/"
                               "tsecnews/8a8216d69e6379f4019eb0d03b0101de.pdf",
                        announcedAt="2026-06-11T02:00:00Z", version=2, revisions=[])
        result = compare(issuer, exchange,
                         evaluated_at=datetime.fromisoformat("2026-06-11T09:00:00+08:00"))
        for issue in ("issuer_untrusted_document", "issuer_announcement_time_unverified",
                      "exchange_announcement_after_evaluation",
                      "exchange_revision_history_unverified", "invalid_entitlement_record"):
            self.assertIn(issue, result["issues"])
        self.assertEqual(result["documents"]["exchange"]["publicationTimeTaipei"],
                         "2026-06-11T10:00:00+08:00")
        self.assertIsNone(result["adjustedPriceReturn"])

    def test_wrong_types_and_document_id_mismatch(self):
        event = dict(market="TWSE", code="2330", kind="cashDividend",
                     exDate="2026-06-11", effectiveDate="2026-06-11",
                     terms={"cashPerShareTwd": True, "recordDate": [], "paymentDate": 7})
        result = compare(dict(event, documentId="3288", source="https://pr.tsmc.com/english/news/3287"),
                         event, evaluated_at=datetime.fromisoformat("2026-06-11T09:00:00"))
        for issue in ("issuer_untrusted_document", "evaluation_time_unverified",
                      "invalid_cashPerShareTwd", "invalid_recordDate", "invalid_paymentDate"):
            self.assertIn(issue, result["issues"])
        self.assertIsNone(result["candidateAdjustmentFactor"])
