import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from test_calendar_cutoff import CalendarClient
from test_pipeline import annual_fixture_rows
from market_pipeline.clock import TAIPEI
from market_pipeline.pipeline import ROOT, calendar_context, collect, load_watchlist
from market_pipeline.official_calendar import official_schedule
from market_pipeline.sources import HOLIDAYS, SourceError


def annual_row(day, name, description=""):
    return {"Date": day, "Name": name, "Description": description}


class RolloverClient(CalendarClient):
    authentic_examples = [
        annual_row("1160101", "中華民國開國紀念日", "依規定放假1日。"),
        annual_row("1160104", "國曆新年開始交易日"),
        annual_row("1160201", "農曆春節前最後交易日", "2月2日及2月3日市場無交易。"),
        annual_row("1160202", "市場無交易，僅辦理結算交割作業。"),
        annual_row("1160203", "市場無交易，僅辦理結算交割作業。"),
        annual_row("1160204", "農曆除夕及春節", "依規定放假。"),
        annual_row("1160211", "農曆春節後開始交易日"),
        annual_row("1161224", "行憲紀念日", "依規定補假。"),
        annual_row("1161231", "117年開國紀念日", "依規定補假。"),
    ]



examples = {row["Date"]: row for row in RolloverClient.authentic_examples}
RolloverClient.holidays = [examples.get(row["Date"], row) for row in annual_fixture_rows(2027)]


def context(client, today):
    now = datetime.fromisoformat(today + "T21:00:00").replace(tzinfo=TAIPEI)
    return calendar_context(client, now, (now.date() - timedelta(days=240)).isoformat())


class RolloverTests(unittest.TestCase):
    def test_prior_year_retains_closures_and_live_current_year_overrides_pin(self):
        client = RolloverClient()
        client.days = ["2026-12-24", "2026-12-25", "2026-12-31", "2027-01-01", "2027-01-04",
                       "2027-02-01", "2027-02-02", "2027-02-03", "2027-02-11"]
        client.holidays = [*client.holidays, annual_row("1160111", "臨時休市")]
        for today, target in [("2026-12-25", "2026-12-24"), ("2027-01-01", "2026-12-31"),
                              ("2027-01-04", "2027-01-04"), ("2027-01-11", "2027-01-04"),
                              ("2027-02-01", "2027-02-01"), ("2027-02-02", "2027-02-01"),
                              ("2027-02-03", "2027-02-01"), ("2027-02-11", "2027-02-11")]:
            with self.subTest(today=today):
                result = context(client, today)
                self.assertEqual(result["targetDate"], target)
                self.assertEqual(result["issues"], [])
                self.assertNotIn("2026-12-25", result["dates"])
        self.assertNotIn("2027-02-02", result["dates"])
        self.assertNotIn("2027-02-03", result["dates"])

    def test_live_open_label_never_supplies_missing_finmind_session(self):
        client = RolloverClient()
        client.days = ["2026-12-31", "2027-02-01"]
        result = context(client, "2027-02-11")
        self.assertEqual(result["status"], "awaiting_confirmation")
        self.assertNotIn(result["targetDate"], result["dates"])

    def test_malformed_and_duplicate_conflicting_live_never_create_closures(self):
        for invalid_row in [annual_row("garbage", "放假"), annual_row("1160112", None),
                            annual_row("1160211", "臨時休市"), annual_row("1160112", "正常交易暨休市")]:
            with self.subTest(invalid=invalid_row):
                client = RolloverClient()
                client.holidays = [*client.holidays, annual_row("1160111", "臨時休市"), invalid_row]
                client.days = ["2026-12-31", "2027-01-11"]
                result = context(client, "2027-01-11")
                self.assertEqual(result["status"], "trading_day")
                self.assertEqual(result["issues"], [])
                self.assertTrue(any("115008038711-1.pdf" in source for source in result["sources"]))

    def test_uncovered_history_year_flags_report_and_does_not_guess(self):
        client = RolloverClient()
        client.days = ["2027-12-31", "2028-01-04"]
        result = context(client, "2028-01-04")
        self.assertEqual(result["issues"], ["official_calendar_year_unverified"])
        self.assertIn("2028-01-04", result["dates"])
        self.assertNotIn("2027-12-31", result["dates"])

    def test_unreadable_unpinned_source_preserves_diagnostics_and_blocks_rules(self):
        client = RolloverClient()
        client.days = ["2028-11-13", "2028-11-14"]
        original_data = client.dataset
        def dataset(kind, start, end, code=None):
            rows = original_data(kind, start, end, code)
            return rows if kind == "TaiwanStockTradingDate" else [{**row, "date": end} for row in rows]
        client.dataset = dataset
        original = client.get
        def get(url, *args, **kwargs):
            if url == HOLIDAYS:
                raise SourceError("network_error")
            return original(url, *args, **kwargs)
        client.get = get
        with patch("market_pipeline.pipeline.collect_news", return_value=[]):
            payload = collect(client, load_watchlist(ROOT / "config/watchlist_public.json"),
                              datetime(2028, 11, 14, 21, tzinfo=TAIPEI))
        self.assertEqual(payload["calendar"]["issues"], ["official_calendar_year_unverified"])
        self.assertEqual(payload["summary"]["completeCount"], 22)
        self.assertEqual(payload["reportStatus"], "partial")
        self.assertTrue(all("price_rules" in stock["unavailableRules"] for stock in payload["stocks"]))

    def test_rollover_entrypoint_full_22_names_and_real_history_gap(self):
        client = RolloverClient()
        watchlist = load_watchlist(ROOT / "config/watchlist_public.json")
        client.days = ["2026-11-11"]
        now = datetime(2026, 11, 11, 21, tzinfo=TAIPEI)
        original = client.dataset
        with patch("market_pipeline.pipeline.collect_news", return_value=[]):
            ready = collect(client, watchlist, now)
            client.days = ["2026-10-22", "2026-10-23", "2026-11-10", "2026-11-11"]
            def dataset(kind, start, end, code=None):
                rows = original(kind, start, end, code)
                if kind != "TaiwanStockTradingDate":
                    rows += [{**row, "date": "2026-10-22"} for row in rows]
                return rows
            client.dataset = dataset
            gap = collect(client, watchlist, now)
        self.assertEqual(ready["calendar"]["targetDate"], "2026-11-11")
        self.assertEqual(ready["calendar"]["issues"], [])
        self.assertEqual(ready["summary"]["completeCount"], 22)
        self.assertEqual(ready["reportStatus"], "complete")
        self.assertEqual(gap["reportStatus"], "partial")
        for stock in gap["stocks"]:
            self.assertEqual(stock["quality"]["price"]["missingDates"], ["2026-11-10"])
            self.assertEqual(stock["quality"]["price"]["status"], "history_gaps")

    def test_truncated_year_without_pin_is_unverified(self):
        client = RolloverClient()
        client.holidays = [annual_row("1190101", "元旦放假")]
        dates, _, missing, _ = official_schedule(client, ROOT / "config", 2030, 2030)
        self.assertEqual(dates, {})
        self.assertEqual(missing, [2030])

    def test_midyear_truncation_preserves_pins_and_ignores_partial_extras(self):
        client = RolloverClient()
        client.holidays = [row for row in client.holidays if row["Date"] != "1160609"]
        client.holidays.append(annual_row("1160608", "臨時休市"))
        client.days = ["2027-06-07", "2027-06-08", "2027-06-09"]
        result = context(client, "2027-06-09")
        self.assertEqual(result["targetDate"], "2027-06-08")
        self.assertEqual(result["issues"], [])
        self.assertNotIn("2027-06-09", result["dates"])

    def test_full_calendar_contradiction_is_unresolved_not_a_closure(self):
        client = RolloverClient()
        client.holidays = [annual_row("1160609", "正常交易") if row["Date"] == "1160609"
                           else row for row in client.holidays]
        client.days = ["2027-06-08", "2027-06-09"]
        result = context(client, "2027-06-09")
        self.assertEqual(result["targetDate"], "2027-06-09")
        self.assertEqual(result["status"], "awaiting_confirmation")
        self.assertNotIn("2027-06-09", result["dates"])
        self.assertIn("official_calendar_conflicting_dates", result["issues"])
