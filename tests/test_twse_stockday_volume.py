"""Validate monthly source identity, units and per-session rows."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from compare_twse_stockday_volume import exit_status, parse_month, window_status


class TwseStockDayVolumeTests(unittest.TestCase):
    def test_explicit_zero_and_invalid_volume_are_distinct(self):
        payload = {"stat": "OK", "date": "20261101", "title": "115年11月 2330 台積電",
                   "fields": ["日期", "成交股數"], "data": [["115/11/12", "0"], ["115/11/13", "--"]]}
        _, rows = parse_month(json.dumps(payload), "2330", "2026-11")
        self.assertEqual(rows, {"2026-11-12": 0, "2026-11-13": None})

    def test_identity_unit_and_duplicate_official_session_are_rejected(self):
        payload = {"stat": "OK", "date": "20261101", "title": "115年11月 2330 台積電",
                   "fields": ["日期", "成交股數"], "data": [["115/11/12", "2"]] * 2}
        for code, field, error in (("2317", "成交股數", "identity"),
                                   ("2330", "成交張數", "unit"),
                                   ("2330", "成交股數", "duplicate")):
            payload["fields"][1] = field
            with self.assertRaisesRegex(ValueError, error):
                parse_month(json.dumps(payload), code, "2026-11")

    def test_full_window_distinguishes_match_missing_and_invalid(self):
        rows = [{"date": str(i), "archiveShares": 0, "stockDayShares": 0,
                 "status": "explicit_zero"} for i in range(60)]
        for value, status, complete, matches in (
            (0, "explicit_zero", True, True), (1, "different", True, False),
            (None, "missing_or_invalid_evidence", False, False),
            (True, "missing_or_invalid_evidence", False, False),
        ):
            with self.subTest(value=value):
                rows[-1].update(stockDayShares=value, status=status)
                result = window_status(rows)
                self.assertEqual(result["numericWindowComplete"], complete)
                self.assertEqual(result["numericWindowAllMatch"], matches)
                self.assertFalse(result["scopeVerifiedWindowComplete"])
                self.assertEqual(exit_status({"dataAcquisitionComplete": complete,
                                              "numericComparisonPassed": matches}),
                                 0 if matches else 2 if complete else 1)
