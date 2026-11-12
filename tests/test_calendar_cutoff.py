import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from market_pipeline.clock import TAIPEI
from market_pipeline.pipeline import ROOT, calendar_context, collect, load_watchlist
from market_pipeline.sources import DATASETS, HOLIDAYS, SourceError
from test_pipeline import FixtureClient


class CalendarClient(FixtureClient):
    days = ["2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13"]
    holidays = [{"Date": "1150101", "Name": "元旦", "Description": "放假"}]

    def dataset(self, dataset, start, end, code=None):
        if dataset == "TaiwanStockTradingDate":
            return [{"date": day} for day in self.days]
        rows = super().dataset(dataset, start, end, code)
        return [{**row, "date": "2026-11-11"} for row in rows]

    def get(self, url, *args, **kwargs):
        if url == HOLIDAYS:
            return self.holidays
        raise SourceError("network_error")


class CalendarCutoffTests(unittest.TestCase):
    def context(self, day=12, hour=0, minute=6, client=None, overrides=None):
        return calendar_context(client or CalendarClient(), datetime(2026, 11, day, hour, minute, tzinfo=TAIPEI), "2026-01-01", overrides or [])

    def test_required_times(self):
        for hour, minute, target in [(0, 6, "11"), (9, 0, "11"), (13, 30, "11"), (15, 29, "11"), (15, 30, "12"), (21, 0, "12")]:
            with self.subTest(hour=hour, minute=minute):
                context = self.context(hour=hour, minute=minute)
                self.assertEqual(context["targetDate"], "2026-11-" + target)
                self.assertTrue(all(day <= context["targetDate"] for day in context["dates"]))
                if target == "11":
                    self.assertNotIn("2026-11-12", context["dates"])

    def test_utc_normalized_before_date_selection(self):
        context = calendar_context(CalendarClient(), datetime(2026, 11, 11, 16, 6, tzinfo=timezone.utc), "2026-01-01", [])
        self.assertEqual(context["requestedDate"], "2026-11-12")
        self.assertEqual(context["targetDate"], "2026-11-11")
        self.assertEqual(context["timezone"], "Asia/Taipei")

    def test_weekend_and_monday_morning(self):
        for day in (14, 15, 16):
            self.assertEqual(self.context(day=day)["targetDate"], "2026-11-13")

    def test_holiday_and_temporary_closure_override(self):
        client = CalendarClient()
        client.holidays = [{"Date": "1151112", "Name": "測試休市", "Description": "全日休市"}]
        for hour in (0, 21):
            context = self.context(hour=hour, client=client)
            self.assertEqual(context["targetDate"], "2026-11-11")
            self.assertNotIn("2026-11-12", context["dates"])
        overrides = [{"date": "2026-11-12", "reason": "測試臨時休市，不代表真實公告", "source": "https://www.twse.com.tw/test-only"}]
        self.assertEqual(self.context(hour=21, overrides=overrides)["targetDate"], "2026-11-11")
        self.assertNotIn("2026-11-12", self.context(day=13, hour=21, overrides=overrides)["dates"])

    def test_new_year_uses_previous_year_session(self):
        client = CalendarClient()
        client.days = ["2025-12-31", "2026-01-01", "2026-01-02"]
        context = calendar_context(client, datetime(2026, 1, 1, 21, tzinfo=TAIPEI), "2025-06-01", [])
        self.assertEqual(context["targetDate"], "2025-12-31")

    def test_missing_calendar_never_guesses_today_before_cutoff(self):
        client = CalendarClient()
        client.days = []
        self.assertIsNone(self.context(client=client)["targetDate"])
        with self.assertRaisesRegex(SourceError, "calendar_target_unavailable"):
            collect(client, load_watchlist(ROOT / "config/watchlist_public.json"), datetime(2026, 11, 12, 0, 6, tzinfo=TAIPEI))

    def test_post_cutoff_absent_today_is_pending_not_fake_holiday(self):
        client = CalendarClient()
        client.days = ["2026-11-11"]
        context = self.context(hour=21, client=client)
        self.assertEqual(context["targetDate"], "2026-11-12")
        self.assertEqual(context["status"], "awaiting_confirmation")

    def test_naive_time_and_unofficial_closure_rejected(self):
        with self.assertRaisesRegex(ValueError, "timezone_required"):
            calendar_context(CalendarClient(), datetime(2026, 11, 12), "2026-01-01")
        with self.assertRaises(ValueError):
            self.context(overrides=[{"date": "2026-11-12", "reason": "test", "source": "https://example.com"}])

    def test_22_symbols_before_and_after_cutoff(self):
        watchlist = load_watchlist(ROOT / "config/watchlist_public.json")
        with patch("market_pipeline.pipeline.collect_news", return_value=[]):
            early = collect(CalendarClient(), watchlist, datetime(2026, 11, 12, 0, 6, tzinfo=TAIPEI))
            late = collect(CalendarClient(), watchlist, datetime(2026, 11, 12, 15, 30, tzinfo=TAIPEI))
        self.assertEqual(early["summary"]["asOf"], "2026-11-11")
        self.assertEqual(early["summary"]["completeCount"], 22)
        self.assertEqual(early["summary"]["manualCheckCount"], 0)
        for stock in early["stocks"]:
            self.assertNotIn("2026-11-12", stock["quality"]["price"]["missingDates"])
        self.assertEqual(late["summary"]["completeCount"], 0)
        for stock in late["stocks"]:
            self.assertTrue(all(quality["status"] == "delayed" for quality in stock["quality"].values()))

    def test_each_dataset_has_its_own_publication_date(self):
        class MixedClient(CalendarClient):
            def dataset(self, dataset, start, end, code=None):
                rows = super().dataset(dataset, start, end, code)
                if dataset == DATASETS["price"]:
                    rows = [{**row, "date": "2026-11-12"} for row in rows]
                return rows
        with patch("market_pipeline.pipeline.collect_news", return_value=[]):
            payload = collect(MixedClient(), load_watchlist(ROOT / "config/watchlist_public.json"), datetime(2026, 11, 12, 21, tzinfo=TAIPEI))
        for stock in payload["stocks"]:
            self.assertEqual(stock["quality"]["price"]["status"], "ok")
            self.assertEqual(stock["quality"]["institutional"]["status"], "delayed")
            self.assertEqual(stock["latest"]["margin"]["date"], "2026-11-11")
