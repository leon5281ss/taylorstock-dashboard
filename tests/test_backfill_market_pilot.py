"""Offline safety tests for isolated TWSE/TPEx historical backfill."""
import gzip
import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from backfill_market_pilot import (PilotError, combine, normalize_header,
                                   pilot_dates, records, tables, url_for)


def roster():
    return {"markets": {
        "TWSE": {"2330": {"code": "2330", "name": "台積電", "market": "TWSE"}},
        "TPEX": {"6488": {"code": "6488", "name": "環球晶", "market": "TPEX"}}
    }, "errors": {}}


def twse(day="20261104"):
    fields = ["證券代號", "證券名稱", "成交股數", "成交筆數", "成交金額",
              "開盤價", "最高價", "最低價", "收盤價", "漲跌(+/-)"]
    record = ["2330", "台積電", "1,234", "20", "123,400",
              "100.0", "102", "99", "101", "<p>+</p>"]
    return {"date": day, "stat": "OK", "tables": [
        {"fields": ["指數", "收盤指數"], "data": [["發行量加權股價指數", "99"]]},
        {"fields": fields, "data": [record]}]}


def tpex(day="1151104"):
    fields = ["代號", "名稱", "收盤", "漲跌", "開盤", "最高", "最低",
              "成交股數", "成交金額(元)", "成交筆數", "最後買價"]
    record = ["6488", "環球晶", "505", "5", "500", "511", "498",
              "30,000", "15,100,000", "200", "504"]
    return {"date": day, "stat": "ok", "tables": [{"fields": fields, "data": [record]}]}


class HistoricalPilotTests(unittest.TestCase):
    def test_source_urls_have_requested_historical_date(self):
        self.assertIn("20261104", url_for("TWSE", "2026-11-04"))
        self.assertIn("2026%2F11%2F04", url_for("TPEX", "2026-11-04"))
        self.assertIn("type=EW", url_for("TPEX", "2026-11-04"))

    def test_named_table_not_index_and_date_verified(self):
        result = combine("2026-11-04", roster(), {"TWSE": twse(), "TPEX": tpex()})
        self.assertEqual(result["status"], "historical_pilot_research_only")
        self.assertFalse(result["pointInTimeUniverse"])
        self.assertFalse(result["mixedVolumeWithDailyOpenAPI"])
        self.assertEqual(result["marketCounts"], {"TWSE": 1, "TPEX": 1})
        self.assertEqual(result["volumeScopes"]["TPEX"], "tpex_round_lot_shares")
        self.assertEqual(result["sourceDateEvidence"]["TWSE"], "explicit_response_date")
        self.assertEqual({x["code"] for x in result["stocks"]}, {"2330", "6488"})
        self.assertEqual(result["stocks"][1]["volume"], 30000)

    def test_no_date_field_is_not_lied_about(self):
        x = tpex()
        del x["date"]
        data = records(x, "TPEX", "2026-11-04", roster()["markets"]["TPEX"])
        self.assertEqual(data["sourceDateEvidence"], "query_only_unverified")

    def test_mixed_or_wrong_response_date_rejected(self):
        wrong = twse(day="20261105")
        with self.assertRaisesRegex(PilotError, "official_response_date_mismatch"):
            combine("2026-11-04", roster(), {"TWSE": wrong, "TPEX": tpex()})

    def test_unknown_schema_is_never_guessed(self):
        x=twse()
        x["tables"][1]["fields"][4]="金額"
        with self.assertRaisesRegex(PilotError, "unknown_or_ambiguous_quote_table"):
            tables(x, "TWSE")

    def test_duplicate_codes_rejected(self):
        x=twse()
        x["tables"][1]["data"].append(list(x["tables"][1]["data"][0]))
        with self.assertRaisesRegex(PilotError,"duplicate_quote_symbol"):
            records(x,"TWSE","2026-11-04",roster()["markets"]["TWSE"])

    def test_missing_close_is_not_zero(self):
        x=twse()
        x["tables"][1]["data"][0][8]="--"
        with self.assertRaisesRegex(PilotError,"incomplete_historical_coverage"):
            records(x,"TWSE","2026-11-04",roster()["markets"]["TWSE"])

    def test_invalid_ohlc_rejected(self):
        x=tpex()
        x["tables"][0]["data"][0][5]="499"
        with self.assertRaisesRegex(PilotError,"invalid_ohlc"):
            records(x,"TPEX","2026-11-04",roster()["markets"]["TPEX"])

    def test_unknown_status_rejected(self):
        x=twse()
        x["stat"]="很抱歉 沒有資料"
        with self.assertRaisesRegex(PilotError,"source_not_ok"):
            tables(x,"TWSE")

    def test_normalizes_html_and_fullwidth_parentheses(self):
        self.assertEqual(normalize_header("成交金額（元）"), "成交金額(元)")
        self.assertEqual(normalize_header("最後買量<br>(張數)"), "最後買量(張數)")

    def test_legacy_twse_fields_n_supported(self):
        x=twse()
        x["fields9"]=x["tables"][1]["fields"]
        x["data9"]=x["tables"][1]["data"]
        del x["tables"]
        self.assertEqual(len(tables(x,"TWSE")[1]),1)

    def test_bounded_pilot_and_existing_archive_protection(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            live=root/"market_daily"
            live.mkdir()
            (live/"2026-11-11.json.gz").write_bytes(b"legacy")
            days=pilot_dates("2026-11-04","2026-11-10",root/"pilot",live)
            self.assertEqual(days,["2026-11-04","2026-11-05","2026-11-06",
                                   "2026-11-09","2026-11-10"])
            with self.assertRaisesRegex(PilotError,"prearchive"):
                pilot_dates("2026-11-09","2026-11-11",root/"pilot",live)
            with self.assertRaisesRegex(PilotError,"day_count_out_of_bounds"):
                pilot_dates("2026-11-02","2026-11-10",root/"pilot",live)

    def test_idempotent_already_present(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            live=root/"market_daily";live.mkdir()
            (live/"2026-11-11.json.gz").write_bytes(b"data")
            pilot=root/"pilot";pilot.mkdir()
            (pilot/"2026-11-04.json.gz").write_bytes(b"archived")
            dates=pilot_dates("2026-11-04","2026-11-04",pilot,live)
            self.assertEqual(dates, [])


if __name__=="__main__":
    unittest.main()
