"""Validate the contents underpinning each TPEx classification claim."""
import json
from pathlib import Path
import sys
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch
from hashlib import sha256

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from reconcile_volume_categories import REPORTS, audit, parse, source_url


class VolumeCategoryTests(unittest.TestCase):
    def payload(self, quantity="0", field="成交股數"):
        return {"stat": "ok", "date": "20261113", "tables": [
            {"fields": ["代號", field], "data": [["6488", quantity]]}]}

    def test_explicit_zero_is_distinct_from_absence_and_invalid_value(self):
        payload = self.payload()
        payload["tables"][0]["data"].append(["6489", "--"])
        result = parse("oddQuote", "2026-11-13", json.dumps(payload))
        self.assertEqual(result["values"], {"6488": 0, "6489": None})
        self.assertNotIn("1234", result["values"])

    def test_lots_remain_lots(self):
        result = parse("fixPricing", "2026-11-13", json.dumps(self.payload("2", "成交張數")))
        self.assertEqual((result["unit"], result["values"]["6488"]), ("lots", 2))
        self.assertIn("type=Daily", source_url("odd", "2026-11-13"))

    def test_wrong_date_unit_and_duplicate_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "date_mismatch"):
            parse("oddQuote", "2026-11-12", json.dumps(self.payload()))
        with self.assertRaisesRegex(ValueError, "scope_or_unit"):
            parse("oddQuote", "2026-11-13", json.dumps(self.payload("2", "成交張數")))
        payload = self.payload()
        payload["tables"][0]["data"] *= 2
        with self.assertRaisesRegex(ValueError, "duplicate_volume_code"):
            parse("oddQuote", "2026-11-13", json.dumps(payload))

    def test_block_report_preserves_separate_transactions_for_one_symbol(self):
        payload = self.payload("1000")
        table = payload["tables"][0]
        table["fields"].append("成交時間")
        table["data"][0].append("10:00:00")
        table["data"].append(["6488", "2000", "11:00:00"])
        result = parse("quote", "2026-11-13", json.dumps(payload))
        self.assertEqual(result["values"]["6488"], 3000)
        table["data"].append(table["data"][0])
        with self.assertRaisesRegex(ValueError, "duplicate_block_transaction"):
            parse("quote", "2026-11-13", json.dumps(payload))

    def test_all_and_partial_download_failures(self):
        day = "2026-11-13"
        baseline = {"comparisons": [{"market": "TPEX", "date": day, "stocks": []}]}
        raw = json.dumps(self.payload()).encode()
        with TemporaryDirectory() as directory, patch("reconcile_volume_categories.time.sleep"):
            for successful in (0, 1):
                with self.subTest(successful=successful), patch(
                    "reconcile_volume_categories.fetch",
                    side_effect=[raw] * successful + [OSError("offline")] * (4 - successful),
                ):
                    report = audit(baseline, Path(directory))
                    self.assertTrue(report["auditExecuted"])
                    self.assertFalse(report["officialReportsComplete"])
                    self.assertEqual(report["status"], "failed_official_evidence")
                    self.assertEqual(sum("error" in r for r in report["sources"]), 4 - successful)

    def test_replay_rejects_corruption_and_hash_mismatch(self):
        day = "2026-11-13"
        category = "oddQuote"
        baseline = {"comparisons": [{"market": "TPEX", "date": day, "stocks": []}]}
        name = f"{category}-{day}.json"
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / name).write_bytes(b"corrupt")
            for digest, error in (("0" * 64, "raw_sha256_mismatch"),
                                  (sha256(b"corrupt").hexdigest(), "Expecting value")):
                manifest = {(category, day): {"source": source_url(category, day),
                                             "rawFile": name, "sha256": digest}}
                report = audit(baseline, folder, manifest=manifest)
                self.assertFalse(report["officialReportsComplete"])
                self.assertIn(error, report["sources"][0]["error"])
