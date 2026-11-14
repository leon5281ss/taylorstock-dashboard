"""Volume disagreements and missing evidence must keep V5/V60 unavailable."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from audit_volume_scope import compare
from backfill_market_pilot import PilotError
from test_research_history_batch import tpex


class VolumeScopeAuditTests(unittest.TestCase):
    def test_equal_and_different_shares_do_not_certify_scopes(self):
        for archive_volume, status in ((30000, "equal"), (30123, "different")):
            with self.subTest(status=status):
                result = compare("2026-11-13", "TPEX", {"6488": archive_volume, "1234": 0},
                                 tpex("2026-11-13"))
                self.assertEqual(result["counts"], {status: 1, "missing_or_invalid_historical_volume": 1})
                self.assertEqual(result["historicalScope"], "round_lot")
                self.assertFalse(result["scopeEquivalenceVerified"])
                self.assertTrue(all(row["v5v60"] is None for row in result["stocks"]))

    def test_date_mismatch_and_missing_date_are_rejected(self):
        for payload in (tpex("2026-11-12"), tpex("2026-11-13")):
            if payload["date"].endswith("13"):
                del payload["date"]
            with self.assertRaises(PilotError):
                compare("2026-11-13", "TPEX", {"6488": 30000}, payload)

    def test_duplicate_symbol_rejected(self):
        payload = tpex("2026-11-13")
        payload["tables"][0]["data"] *= 2
        with self.assertRaisesRegex(PilotError, "duplicate_historical_volume_code"):
            compare("2026-11-13", "TPEX", {"6488": 30000}, payload)

    def test_coverage_direction_and_relative_difference(self):
        payload = tpex("2026-11-13")
        rows = payload["tables"][0]["data"]
        rows.extend([["6489", "100", "1", "1", "1", "1", "1"], ["6490", "--", "1", "1", "1", "1", "1"]])
        result = compare("2026-11-13", "TPEX",
                         {"6488": 40000, "6490": True, "1234": 0}, payload)
        summary = result["summary"]
        self.assertEqual(summary["coverage"], {"both": 2, "daily_only": 1, "historical_only": 1})
        self.assertEqual(summary["historicalLower"], 1)
        self.assertEqual(summary["absoluteDifferenceShares"], 10000)
        self.assertEqual(summary["meanRelativeDifferencePercent"], -25)
        self.assertEqual((summary["invalidDaily"], summary["invalidHistorical"]), (1, 1))
        self.assertTrue(all(row["v5v60"] is None for row in result["stocks"]))
