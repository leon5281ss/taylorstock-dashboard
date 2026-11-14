"""A sample quantity and an aggregate do not establish inclusion."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from audit_twse_session_components import parse


class TwseSessionComponentTests(unittest.TestCase):
    def test_quantity_without_report_unit_is_retained_without_conversion(self):
        data = {"stat":"OK", "date":"20261113", "title":"盤後定價交易",
                "fields":["證券代號","成交數量"], "data":[["2330","2"], ["1101","0"]]}
        parsed = parse(json.dumps(data), "BFT41U", "2026-11-13")
        self.assertIsNone(parsed["unit"])
        self.assertEqual(parsed["values"], {"2330": 2, "1101": 0})
        self.assertNotIn("1301", parsed["values"])

    def test_date_and_duplicate_rows_fail_closed(self):
        data = {"stat":"OK", "date":"20261113", "title":"盤中零股交易行情單",
                "fields":["證券代號","成交股數"], "data":[["2330","10"]]*2}
        with self.assertRaisesRegex(ValueError, "date_or_title"):
            parse(json.dumps(data), "TWTC7U", "2026-11-12")
        with self.assertRaisesRegex(ValueError, "duplicate_symbol"):
            parse(json.dumps(data), "TWTC7U", "2026-11-13")
