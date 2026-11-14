"""TWSE session coverage cannot substitute for verified trade scope."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from audit_twse_volume_window import audit


class TwseVolumeWindowTests(unittest.TestCase):
    def test_closed_day_and_missing_dates_do_not_become_zero(self):
        row = {"code": "2330", "presence": "both", "dailyShares": 0, "historicalShares": 0}
        baseline = {"comparisons": [{"market": "TWSE", "date": "2026-11-13", "stocks": [row]}]}
        report = audit(baseline, "2026-11-13", {"2026-11-12"}, 2026)
        self.assertEqual(len(report["requiredDates"]), 60)
        self.assertNotIn("2026-11-12", report["requiredDates"])
        self.assertEqual(len(report["missingComparisonDates"]), 59)
        self.assertEqual(report["stocks"][0]["dailyStatus"]["2026-11-13"], "explicit_zero")
        self.assertEqual(report["stocks"][0]["dailyStatus"]["2026-11-11"], "comparison_missing")
        self.assertFalse(report["suspensionEvidenceAvailable"])
        self.assertEqual(report["scopeVerifiedDays"], 0)
        self.assertIsNone(report["stocks"][0]["v5v60"])

    def test_even_sixty_numeric_matches_leave_scope_unverified(self):
        days = audit({"comparisons": []}, "2026-11-13", set(), 2026)["requiredDates"]
        row = {"code": "2330", "presence": "both", "dailyShares": 100, "historicalShares": 100}
        baseline = {"comparisons": [{"market": "TWSE", "date": day, "stocks": [row]} for day in days]}
        report = audit(baseline, "2026-11-13", set(), 2026)
        self.assertEqual(report["statusCounts"], {"numeric_match_scope_unverified": 60})
        self.assertEqual(report["stocksWithVerifiedWindow"], 0)
        self.assertFalse(report["publishable"])
