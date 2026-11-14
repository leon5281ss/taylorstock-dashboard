"""Isolated, offline tests of bounded unattended official historical backfill."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import backfill_research_history as batch
from backfill_market_pilot import MINIMUM_ROSTER


def twse(day):
    return {"stat": "OK", "date": day.replace("-", ""), "tables": [
        {"fields": ["證券代號", "成交股數", "成交金額", "開盤價", "最高價", "最低價", "收盤價"],
         "data": [["2330", "1234", "123400", "100", "102", "99", "101"]]}]}


def tpex(day):
    y, m, d = day.split("-")
    return {"stat": "ok", "date": str(int(y)-1911) + m + d, "tables": [
        {"fields": ["代號", "成交股數", "成交金額(元)", "開盤", "最高", "最低", "收盤"],
         "data": [["6488", "30000", "15000000", "500", "510", "495", "505"]]}]}


def universe():
    return {"markets": {"TWSE": {"2330": {"code": "2330"}},
                        "TPEX": {"6488": {"code": "6488"}}},
            "errors": {}}


class ResearchHistoryBatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.minimum_patch = patch.dict(MINIMUM_ROSTER, {"TWSE": 1, "TPEX": 1})
        cls.minimum_patch.start()

    @classmethod
    def tearDownClass(cls):
        cls.minimum_patch.stop()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.daily = self.root / "daily"
        self.research = self.root / "research"
        self.daily.mkdir()
        self.research.mkdir()
        (self.daily / "2026-11-11.json.gz").write_bytes(b"existing-safe-daily-bytes")
        self.original = (self.daily / "2026-11-11.json.gz").read_bytes()

    def tearDown(self):
        self.temp.cleanup()

    def test_bounded_recent_first_and_existing_pilot_skip(self):
        (self.research / "2026-11-10.json.gz").write_bytes(b"unchanged")
        plan = batch.archive_plan(self.daily, self.research, lookback_days=220,
                                  max_successes=2, max_attempts=3)
        self.assertEqual(plan["candidates"][0], "2026-11-09")
        self.assertEqual(plan["maxSuccesses"], 2)

    def test_cap_and_minimum_constraints(self):
        for kw in ({"lookback_days": 1}, {"max_successes": 40},
                   {"max_successes": 10, "max_attempts": 3},
                   {"max_attempts": 50}):
            with self.subTest(kw=kw), self.assertRaises(batch.BackfillError):
                batch.archive_plan(self.daily, self.research, **kw)
        with self.assertRaises(batch.BackfillError):
            batch.run_batch(self.daily, self.research, delay=0.5)

    def test_one_valid_date_archived_without_touching_daily(self):
        fetched = []
        def fetch(url):
            from urllib.parse import parse_qs, urlparse
            query = parse_qs(urlparse(url).query)
            d = query["date"][0].replace("/", "-")
            if len(d) == 8:
                d = d[:4] + "-" + d[4:6] + "-" + d[6:]
            fetched.append(url)
            return json.dumps(tpex(d) if "tpex.org.tw" in url else twse(d))
        with patch.object(batch, "official_universe", return_value=universe()):
            report = batch.run_batch(self.daily, self.research,
                                     fetch=fetch, sleep=lambda _: None,
                                     delay=2.5, max_successes=1, max_attempts=1)
        self.assertEqual(report["newCount"], 1)
        self.assertEqual(report["new"][0]["date"], "2026-11-10")
        self.assertEqual(report["researchDaysNow"], 1)
        self.assertEqual(len(fetched), 2)
        self.assertFalse(report["publishable"])
        self.assertFalse(report["volumeScopesCompatibleForDirectMerge"])
        self.assertEqual((self.daily / "2026-11-11.json.gz").read_bytes(), self.original)
        self.assertTrue((self.research / "2026-11-10.json.gz").is_file())
        self.assertEqual(json.loads(__import__("gzip").decompress(
            (self.research / "2026-11-10.json.gz").read_bytes()))["status"],
            "historical_pilot_research_only")

    def test_same_day_idempotent_no_network_if_existing(self):
        (self.research / "2026-11-10.json.gz").write_bytes(b"not-overwritten")
        plan = batch.archive_plan(self.daily, self.research)
        self.assertNotIn("2026-11-10", plan["candidates"])
        self.assertEqual((self.research / "2026-11-10.json.gz").read_bytes(),
                         b"not-overwritten")

    def test_source_failure_cannot_forge_new_date(self):
        def fail(_):
            raise ValueError("source down")
        with patch.object(batch, "official_universe", return_value=universe()):
            out = batch.run_batch(self.daily, self.research, fetch=fail,
                                  sleep=lambda _: None, max_successes=1, max_attempts=1)
        self.assertEqual(out["newCount"], 0)
        self.assertEqual(out["unverifiedDays"], 1)
        self.assertFalse(out["publishable"])
        self.assertEqual(list(self.research.iterdir()), [])

    def test_official_roster_rejection(self):
        with patch.object(batch, "official_universe",
                          return_value={"errors": {"TWSE": "source_invalid"}}):
            with self.assertRaisesRegex(batch.BackfillError, "official_roster_unavailable"):
                batch.run_batch(self.daily, self.research, sleep=lambda _: None,
                                max_successes=1, max_attempts=1)

    def test_missing_live_archive_is_fatal(self):
        self.daily.joinpath("2026-11-11.json.gz").unlink()
        with self.assertRaisesRegex(batch.BackfillError, "daily_archive_is_missing"):
            batch.archive_plan(self.daily, self.research)


    def test_official_holidays_skip_only_genuinely_closed_days(self):
        fixtures = [
            {"Name": "國慶日", "Date": "1151009", "Description": "補假1日"},
            {"Name": "紀念日", "Date": "1151026", "Description": "補假1日"},
            {"Name": "市場無交易，僅辦理結算交割作業", "Date": "1150212", "Description": ""},
            {"Name": "國曆新年開始交易日", "Date": "1150102", "Description": "開始交易。"},
            {"Name": "農曆春節前最後交易日", "Date": "1150211", "Description": "最後交易。"},
            {"Name": "其他", "Date": "1150620", "Description": ""},
            {"Name": "其他", "Date": "1150621", "Description": ""},
            {"Name": "其他", "Date": "1150622", "Description": ""},
            {"Name": "其他", "Date": "1150623", "Description": ""},
        ]
        closed = batch.scheduled_market_closures(fixtures, 2026)
        self.assertIn("2026-10-09", closed)
        self.assertIn("2026-10-26", closed)
        self.assertIn("2026-02-12", closed)
        self.assertNotIn("2026-01-02", closed)
        self.assertNotIn("2026-02-11", closed)
        self.assertNotIn("2026-10-23", closed)
        plan = batch.archive_plan(self.daily, self.research,
                                  official_closed_dates=closed)
        self.assertNotIn("2026-10-09", plan["candidates"])
        self.assertNotIn("2026-10-26", plan["candidates"])
        self.assertIn("2026-10-23", plan["candidates"])

    def test_unavailable_calendar_does_not_invent_market_closure(self):
        with self.assertRaisesRegex(batch.BackfillError, "official_holiday_calendar"):
            batch.scheduled_market_closures([], 2026)
        with patch.object(batch, "official_universe", return_value=universe()):
            report = batch.run_batch(self.daily, self.research,
                                     holiday_fetch=lambda _: [],
                                     fetch=lambda _: "{}",
                                     sleep=lambda _: None,
                                     max_successes=1, max_attempts=1)
        self.assertEqual(report["holidayCalendarStatus"], "unavailable_not_assumed_open")
        self.assertEqual(report["newCount"], 0)
        self.assertEqual(report["unverifiedDays"], 1)

if __name__ == "__main__":
    unittest.main()
