"""Offline official ex-rights reference event tests. Never imply price adjustment."""
import unittest
from datetime import date
from unittest.mock import patch
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import collect_corporate_action_research as corp


def roster():
    return {"errors": {}, "markets": {
        "TWSE": {"2330": {"code": "2330"}},
        "TPEX": {"6488": {"code": "6488"}}}}


def twse():
    return {"stat": "OK", "fields": [
        "資料日期", "股票代號", "股票名稱", "除權息前收盤價",
        "除權息參考價", "權/息"],
        "data": [["115年06月05日", "2330", "台積電", "100", "96.50", "息"],
                 ["115年06月05日", "0050", "ETF", "50", "49", "息"]]}


def tpex():
    return {"stat": "ok", "tables": [{
        "fields": ["除權息日期", "代號", "名稱", "除權息前收盤價",
                   "除權息參考價", "權/息"],
        "data": [["115/06/05", "6488", "環球晶", "200", "195", "權息"]],
        "totalCount": 1}]}


class CorporateActionReferenceTests(unittest.TestCase):
    def test_sources_and_post_body(self):
        request = corp.request_details("2026-01-01", "2026-11-14")
        self.assertIn("startDate=20260101", request["TWSE"]["url"])
        self.assertIn("endDate=20261114", request["TWSE"]["url"])
        self.assertEqual(request["TPEX"]["method"], "POST")
        self.assertIn("id=", request["TPEX"]["body"])
        self.assertIn("startDate=2026%2F01%2F01", request["TPEX"]["body"])

    def test_twse_roc_text_and_tpex_roc_slash_dates(self):
        self.assertEqual(corp.corporate_date("115年06月05日"), "2026-06-05")
        self.assertEqual(corp.corporate_date("115/06/05"), "2026-06-05")
        with self.assertRaises(corp.CorporateError):
            corp.corporate_date("115年02月30日")

    def test_normalizes_fields_and_ignores_etf(self):
        self.assertEqual(corp.normalized_field(" 除權息參考價<br>"), "除權息參考價")
        result = corp.event_records(twse(), "TWSE", "2026-01-01",
                                    "2026-11-14", roster()["markets"]["TWSE"])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["code"], "2330")
        self.assertAlmostEqual(result[0]["referenceRatio"], 0.965)
        self.assertEqual(result[0]["type"], "息")

    def test_tpex_schema_and_event(self):
        result = corp.event_records(tpex(), "TPEX", "2026-01-01",
                                    "2026-11-14", roster()["markets"]["TPEX"])
        self.assertEqual(result[0]["type"], "權息")
        self.assertEqual(result[0]["referencePrice"], 195)

    def test_total_count_truncation_blocks_data(self):
        data = tpex()
        data["tables"][0]["totalCount"] = 2
        with self.assertRaisesRegex(corp.CorporateError, "truncated"):
            corp.source_table(data, "TPEX")

    def test_schema_change_blocks(self):
        data = twse()
        data["fields"][4] = "不認識欄位"
        with self.assertRaisesRegex(corp.CorporateError, "unknown_corporate_schema"):
            corp.source_table(data, "TWSE")

    def test_out_of_range_event_blocks(self):
        with self.assertRaisesRegex(corp.CorporateError, "outside_requested_window"):
            corp.event_records(twse(), "TWSE", "2026-11-01",
                               "2026-11-14", roster()["markets"]["TWSE"])

    def test_zero_and_missing_ref_price_blocks(self):
        data = twse()
        data["data"][0][4] = "0"
        with self.assertRaisesRegex(corp.CorporateError, "reference_price_invalid"):
            corp.event_records(data, "TWSE", "2026-01-01",
                               "2026-11-14", roster()["markets"]["TWSE"])

    def test_duplicate_same_symbol_date_blocks(self):
        data = tpex()
        data["tables"][0]["data"].append(data["tables"][0]["data"][0][:])
        data["tables"][0]["totalCount"] = 2
        with self.assertRaisesRegex(corp.CorporateError, "duplicate_corporate_event"):
            corp.event_records(data, "TPEX", "2026-01-01",
                               "2026-11-14", roster()["markets"]["TPEX"])

    def test_full_research_snapshot_marks_unadjusted(self):
        result = corp.research_snapshot("2026-01-01", "2026-11-14",
                                        roster(), {"TWSE": twse(), "TPEX": tpex()})
        self.assertEqual(result["marketCounts"], {"TWSE": 1, "TPEX": 1})
        self.assertTrue(result["referenceRatioIsNotTotalReturn"])
        self.assertFalse(result["cashDividendTotalReturnCorrectlyModelled"])
        self.assertFalse(result["historicalPointInTimeCompanyUniverse"])
        self.assertFalse(result["adjustedOhlcvReady"])
        self.assertFalse(result["publishable"])
        self.assertIsNone(result["top10"])

    def test_offline_end_to_end_with_mocked_fetches(self):
        with patch.object(corp, "official_universe", return_value=roster()):
            result = corp.collect(today=date(2026, 11, 14),
                                  text_fetch=lambda _: __import__("json").dumps(twse()),
                                  post=lambda _, form: tpex(),
                                  sleep=lambda _: None)
        self.assertEqual(result["asOf"], "2026-11-14")
        self.assertEqual(len(result["events"]), 2)

    def test_source_failures_do_not_substitute_estimated_prices(self):
        with patch.object(corp, "official_universe", return_value=roster()):
            with self.assertRaisesRegex(corp.CorporateError, "corporate_api_network_or_json_error"):
                corp.collect(today=date(2026, 11, 14), text_fetch=lambda _: "bad JSON",
                             post=lambda _, form: tpex(), sleep=lambda _: None)


if __name__ == "__main__":
    unittest.main()
