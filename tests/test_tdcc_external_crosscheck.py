"""Compare independently sourced weekly TDCC cohorts without promoting history."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from crosscheck_tdcc_mirror import MirrorError, compare


def snap(codes=range(1000, 2200), date="2026-11-13"):
    return {
        "asOf": date, "status": "tdcc_shareholder_research_only",
        "dataCadence": "weekly", "publishable": False,
        "companies": [
            {"code": str(code), "market": "TWSE",
             "shareholders": 100, "depositoryShares": 20000,
             "tier15Shares": 15000, "tier15PercentOfDepository": 75.,
             "level16AdjustmentShares": 0}
            for code in codes]
    }


class WeeklyTdccMirrorTests(unittest.TestCase):
    def test_identical_latest_week_does_not_authorize_earlier_mirror_weeks(self):
        r = compare(snap(), snap())
        self.assertEqual(r["sharedCompanies"], 1200)
        self.assertEqual(r["valueDifferenceCount"], 0)
        self.assertFalse(r["mirrorHistoryAuthorizedForFactorUsage"])
        self.assertIsNone(r["top10"])
        self.assertFalse(r["publishable"])

    def test_mismatched_week_is_refused(self):
        with self.assertRaisesRegex(MirrorError, "date_mismatch"):
            compare(snap(), snap(date="2026-11-06"))

    def test_too_many_differences_are_refused(self):
        official, mirror = snap(), snap()
        for row in mirror["companies"][:10]:
            row["tier15Shares"] += 1
        with self.assertRaisesRegex(MirrorError, "value_mismatch"):
            compare(official, mirror)

    def test_external_mirror_missing_enough_companies_is_refused(self):
        with self.assertRaisesRegex(MirrorError, "overlap_insufficient"):
            compare(snap(), snap(codes=range(1000, 1900)))

    def test_price_scope_is_not_permitted_as_shareholder_snapshot(self):
        bad = snap()
        bad["dataCadence"] = "daily"
        with self.assertRaisesRegex(MirrorError, "provenance"):
            compare(bad, snap())


if __name__ == "__main__":
    unittest.main()
