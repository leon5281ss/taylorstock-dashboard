"""Verify the separation of field signatures and historical trading scope."""
import hashlib
from datetime import date, timedelta
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from audit_stockday_single_source import check
from compare_twse_stockday_volume import monthly_url


class StockDayScopeTests(unittest.TestCase):
    def test_cross_month_signature_changes_without_missing_values(self):
        with TemporaryDirectory() as temp:
            folder = Path(temp)
            manifest = {}
            for month in ("10", "11"):
                fields = ["日期", "成交股數"]
                row = [f"115/{month}/12", "0"]
                if month == "11":
                    fields.append("註記")
                    row.append("")
                raw = json.dumps({"stat":"OK","date":f"2026{month}01",
                                  "title":f"115年{month}月 2330 台積電",
                                  "fields":fields,"data":[row]}).encode()
                name = f"stockday-2330-2026-{month}.json"
                (folder/name).write_bytes(raw)
                manifest[name] = {"source":monthly_url("2330", f"2026-{month}"),
                                  "sha256":hashlib.sha256(raw).hexdigest()}
            dates = ["2026-10-12","2026-11-12"]
            report = check("2330",dates,folder,manifest)
            self.assertFalse(report["numericWindowComplete"])
            self.assertIn("cross_month_schema_mismatch", report["blockers"])
            self.assertFalse(report["crossMonthSchemaConsistent"])
            self.assertFalse(report["historicalScopeVerified"])
            self.assertIsNone(report["v5v60"])
            (folder/name).write_bytes(raw+b" ")
            self.assertEqual(check("2330",dates,folder,manifest)["missingOrInvalidDates"], [dates[1]])

    def test_calendar_window_complete_and_source_failures(self):
        start = date(2026, 8, 10)
        days = [start + timedelta(days=i) for i in range(84)]
        sessions = [d.isoformat() for d in days if d.weekday() < 5]
        with TemporaryDirectory() as temp:
            folder = Path(temp)
            manifest = {}
            for month in sorted({d[:7] for d in sessions}):
                rows = [[f"115/{d[5:7]}/{d[8:]}", "1"] for d in sessions if d.startswith(month)]
                data = {"stat":"OK","date":month.replace("-","")+"01",
                        "title":f"115年{month[-2:]}月 2330 台積電",
                        "fields":["日期","成交股數"],"data":rows}
                raw = json.dumps(data).encode()
                name = f"stockday-2330-{month}.json"
                (folder/name).write_bytes(raw)
                manifest[name] = {"source":monthly_url("2330",month),
                                  "sha256":hashlib.sha256(raw).hexdigest()}
            result = check("2330",sessions,folder,manifest)
            self.assertTrue(result["numericWindowComplete"])
            self.assertEqual(result["blockers"], ["historical_scope_unverified"])
            self.assertIsNone(result["v5v60"])
            manifest[name]["source"] += "&wrong=1"
            result = check("2330",sessions,folder,manifest)
            self.assertIn("raw_source_or_sha256_mismatch",result["blockers"])
            del manifest[name]
            result = check("2330",sessions,folder,manifest)
            self.assertIn("raw_source_missing",result["blockers"])
            self.assertIn("numeric_window_incomplete",result["blockers"])
            for invalid in ("2026-11-31", "2026-11-14"):
                with self.assertRaises(ValueError):
                    check("2330",[invalid],folder,manifest)
