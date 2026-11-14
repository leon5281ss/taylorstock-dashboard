"""A sample quantity and an aggregate do not establish inclusion."""
import json
from pathlib import Path
import sys
import unittest
from tempfile import TemporaryDirectory
from hashlib import sha256

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from audit_twse_session_components import audit, parse, source_url


class TwseSessionComponentTests(unittest.TestCase):
    def test_quantity_without_report_unit_is_retained_without_conversion(self):
        data = {"stat":"OK", "date":"20261113", "title":"盤後定價交易",
                "total":2, "fields":["證券代號","成交數量"], "data":[["2330","2"], ["1101","0"]]}
        parsed = parse(json.dumps(data), "BFT41U", "2026-11-13")
        self.assertIsNone(parsed["unit"])
        self.assertEqual(parsed["values"], {"2330": 2, "1101": 0})
        self.assertNotIn("1301", parsed["values"])

    def test_date_and_duplicate_rows_fail_closed(self):
        data = {"stat":"OK", "date":"20261113", "title":"盤中零股交易行情單",
                "total":2, "fields":["證券代號","成交股數"], "data":[["2330","10"]]*2}
        with self.assertRaisesRegex(ValueError, "date_or_title"):
            parse(json.dumps(data), "TWTC7U", "2026-11-12")
        with self.assertRaisesRegex(ValueError, "duplicate_symbol"):
            parse(json.dumps(data), "TWTC7U", "2026-11-13")

    def test_incomplete_invalid_and_wrong_field_reports(self):
        data = {"stat":"OK", "date":"20261113", "title":"盤中零股交易行情單",
                "fields":["證券代號","成交股數"], "data":[["2330","0"]], "total":1}
        for updates, error in (({"total":2}, "incomplete"),
                               ({"fields":["證券代號","成交張數"]}, "schema"),
                               ({"data":[["2330",True]]}, "invalid_component_quantity"),
                               ({"data":[["2330","-1"]]}, "invalid_component_quantity")):
            with self.subTest(updates=updates), self.assertRaisesRegex(ValueError, error):
                parse(json.dumps(dict(data, **updates)), "TWTC7U", "2026-11-13")

    def test_replay_checks_registered_hash_and_missing_sources(self):
        day = "2026-11-13"
        file = "twse-TWTC7U-20261113.json"
        data = {"stat":"OK", "date":"20261113", "title":"盤中零股交易行情單",
                "fields":["證券代號","成交股數"], "data":[["2330","10"]], "total":1}
        raw = json.dumps(data).encode()
        baseline = {"stocks":[{"comparisons":[{"date":day,"code":"2330",
                    "archiveSource":"https://openapi.twse.com.tw/example",
                    "archiveShares":100,"stockDayShares":100}]}]}
        with TemporaryDirectory() as temp:
            folder = Path(temp)
            manifest = {file: {"url":source_url("TWTC7U",day), "date":day, "file":file,
                               "report":"TWTC7U", "sha256":sha256(raw).hexdigest(),
                               "responseDate":day, "unit":"shares", "fields":data["fields"]}}
            (folder/"twse-components-manifest.json").write_text(json.dumps(manifest))
            (folder/file).write_bytes(raw)
            result = audit(baseline,folder)
            self.assertEqual(result["captures"][0]["parseStatus"], "parsed")
            self.assertEqual(result["status"], "failed_official_evidence")
            self.assertFalse(result["officialSourceAcquisitionComplete"])
            self.assertIsNone(result["comparisons"][0]["reportedComponents"]["TWT53U"])
            (folder/file).write_bytes(raw+b" ")
            result = audit(baseline,folder)
            self.assertEqual(result["captures"][0]["error"], "raw_sha256_mismatch")
            self.assertIsNone(result["comparisons"][0]["reportedComponents"]["TWTC7U"])
            self.assertFalse(result["rawIntegrityVerified"])
