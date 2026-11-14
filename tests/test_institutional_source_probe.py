"""TWSE/TPEX dated institutional endpoints: offline schema and date tests."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from probe_institutional_history import (
    SourceProbeError, dated_url, inspect_day, probe, table_from_source,
)


def twse(net):
    return {"stat": "OK", "fields": [
        "證券代號", "外陸資買賣超股數(不含外資自營商)",
        "投信買賣超股數", "自營商買賣超股數"],
        "data": [["2330", str(net), "22", "-50"],
                 ["2303", "11", "22", "33"]]}


def tpex(net):
    return {"stat": "ok", "tables": [
        {"fields": ["代號", "外資淨買", "買股數", "賣股數", "買股數"],
         "data": [["6488", str(net), "300", "200", "100"],
                  ["8069", "10", "30", "20", "10"]]},
        {"fields": ["分類"], "data": []}]}


class InstitutionSourceProbeTests(unittest.TestCase):
    def test_urls_use_official_dated_feeds_not_openapi_snapshots(self):
        a = dated_url("TWSE", "2026-11-13")
        b = dated_url("TPEX", "2026-11-13")
        self.assertIn("date=20261113", a)
        self.assertIn("selectType=ALLBUT0999", a)
        self.assertIn("/insti/dailyTrade?", b)
        self.assertIn("sect=EW", b)
        self.assertIn("date=115%2F11%2F13", b)
        self.assertIn("type=Daily", b)
        with self.assertRaisesRegex(SourceProbeError, "unknown_exchange"):
            dated_url("OTHER", "2026-11-13")

    def test_date_stable_twse_quotes(self):
        result = inspect_day(twse(100), "TWSE", "2026-11-12", min_rows=2)
        self.assertEqual(result["tableRows"], 2)
        self.assertEqual(result["sourceDateEvidence"], "query_only_unverified")
        self.assertFalse(result["hasRepeatedColumnNames"])

    def test_tpex_repeated_columns_are_reported_not_silently_deduped(self):
        result = inspect_day(tpex(200), "TPEX", "2026-11-12", min_rows=2)
        self.assertTrue(result["hasRepeatedColumnNames"])
        self.assertEqual(result["columnCount"], 5)

    def test_two_market_dates_change_data_and_never_publish(self):
        urls = []
        def fetch(url):
            urls.append(url)
            is_first = "11%2F12" in url or "20261112" in url
            market = "TPEX" if "tpex.org.tw" in url else "TWSE"
            return json.dumps((tpex(100) if is_first else tpex(150)) if
                              market == "TPEX" else
                              (twse(100) if is_first else twse(150)))
        report = probe(["2026-11-12", "2026-11-13"],
                       fetch=fetch, sleep=lambda _: None,
                       min_rows=2)
        self.assertEqual(len(urls), 4)
        self.assertEqual(set(report["markets"]), {"TWSE", "TPEX"})
        self.assertTrue(report["markets"]["TPEX"]["dailyResponsesDistinct"])
        self.assertFalse(report["dataMergeAllowed"])
        self.assertFalse(report["publishable"])
        self.assertIsNone(report["top10"])

    def test_same_latest_tpex_payload_for_both_dates_rejected(self):
        def fetch(url):
            return json.dumps(tpex(50) if "tpex.org.tw" in url else
                              (twse(50) if "20261112" in url else twse(51)))
        with self.assertRaisesRegex(SourceProbeError, "dated_request_not_proven_TPEX"):
            probe(["2026-11-12", "2026-11-13"],
                  fetch=fetch, sleep=lambda _: None, min_rows=2)

    def test_mismatched_explicit_date_fails(self):
        data = twse(1)
        data["date"] = "115/11/13"
        with self.assertRaisesRegex(SourceProbeError, "response_date_mismatch"):
            inspect_day(data, "TWSE", "2026-11-12", min_rows=2)

    def test_schema_change_fails(self):
        t = tpex(1)
        t["tables"][0]["data"][0].append("surplus")
        with self.assertRaisesRegex(SourceProbeError, "row_length_mismatch"):
            table_from_source(t, "TPEX")

    def test_unpublished_and_insufficient_rows_blocked(self):
        t = twse(1)
        t["stat"] = "NOT_AVAILABLE"
        with self.assertRaisesRegex(SourceProbeError, "stat_not_ok"):
            inspect_day(t, "TWSE", "2026-11-12", min_rows=2)
        with self.assertRaisesRegex(SourceProbeError, "coverage_too_low"):
            inspect_day(tpex(1), "TPEX", "2026-11-12", min_rows=10)

    def test_rate_limit_and_date_order_required(self):
        for days in (["2026-11-12"], ["2026-11-13", "2026-11-12"],
                     ["2026-11-13", "2026-11-13"]):
            with self.subTest(days=days), self.assertRaises(SourceProbeError):
                probe(days, sleep=lambda _: None, min_rows=2)
        with self.assertRaisesRegex(SourceProbeError, "rate_limit_required"):
            probe(["2026-11-12", "2026-11-13"], delay=1)


if __name__ == "__main__":
    unittest.main()
