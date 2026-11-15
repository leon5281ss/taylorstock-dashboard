"""Verify the separation of field signatures and historical trading scope."""
import hashlib
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
            self.assertTrue(report["numericWindowComplete"])
            self.assertFalse(report["crossMonthSchemaConsistent"])
            self.assertFalse(report["historicalScopeVerified"])
            self.assertIsNone(report["v5v60"])
            (folder/name).write_bytes(raw+b" ")
            self.assertEqual(check("2330",dates,folder,manifest)["missingOrInvalidDates"], [dates[1]])
