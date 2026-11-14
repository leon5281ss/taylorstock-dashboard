"""TWSE session coverage cannot substitute for verified trade scope."""
from pathlib import Path
import sys
import unittest
from tempfile import TemporaryDirectory
from hashlib import sha256

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from audit_twse_volume_window import audit, read_evidence
from audit_volume_scope import URLS, url_for


def day_report(day, rows):
    return {"market": "TWSE", "date": day, "stocks": rows, "unit": "shares",
            "dailySource": URLS["TWSE"], "historicalSource": url_for("TWSE", day)}


class TwseVolumeWindowTests(unittest.TestCase):
    def test_closed_day_and_missing_dates_do_not_become_zero(self):
        row = {"code": "2330", "presence": "both", "dailyShares": 0, "historicalShares": 0}
        baseline = {"comparisons": [day_report("2026-11-13", [row])]}
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
        baseline = {"comparisons": [day_report(day, [row]) for day in days]}
        report = audit(baseline, "2026-11-13", set(), 2026)
        self.assertEqual(report["statusCounts"], {"numeric_match_scope_unverified": 60})
        self.assertEqual(report["stocksWithVerifiedWindow"], 0)
        self.assertFalse(report["publishable"])

    def test_blank_and_invalid_reports_do_not_count_as_numeric_dates(self):
        day = "2026-11-13"
        for rows in ([], [{"code": "2330", "presence": "both",
                           "dailyShares": True, "historicalShares": 0}]):
            report = audit({"comparisons": [day_report(day, rows)]}, day, set(), 2026)
            self.assertEqual(report["reportDates"], [day])
            self.assertEqual(report["numericComparisonDates"], [])
            self.assertEqual(report["scopeVerifiedDates"], [])

    def test_malformed_and_duplicate_inputs_are_rejected(self):
        day = "2026-11-13"
        row = {"code": "2330", "presence": "both", "dailyShares": 2, "historicalShares": 1}
        for entries in ([day_report(day, []), day_report(day, [])],
                        [day_report(day, [row, row])], [day_report(day, [{"code": "2330"}])],
                        [dict(day_report(day, []), unit="lots")]):
            with self.assertRaises(ValueError):
                audit({"comparisons": entries}, day, set(), 2026)

    def test_changed_evidence_is_rejected(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "report.json"
            data = b'{"comparisons":[]}'
            digest = sha256(data).hexdigest()
            path.write_bytes(data)
            self.assertEqual(read_evidence(path, digest), {"comparisons": []})
            path.write_bytes(data + b" ")
            with self.assertRaisesRegex(ValueError, "sha256_mismatch"):
                read_evidence(path, digest)
