import io
import json
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from market_pipeline.alerts import evaluate
from market_pipeline.news import AnnouncementParser, collect_news
from market_pipeline.pipeline import ROOT, TAIPEI, assert_public, calendar_context, collect, load_watchlist, write_outputs
from market_pipeline.private_pnl import liquidation_pnl
from market_pipeline.sources import DATASETS, FINMIND, HOLIDAYS, HttpClient, SourceError, compare_official, government_bank, iso_date, normalize_finmind, official_record, official_snapshots


def sessions(count=80):
    days = []
    current = date(2026, 6, 1)
    while len(days) < count:
        if current.weekday() < 5:
            days.append(current.isoformat())
        current += timedelta(days=1)
    return days


def history(days):
    return [{"date": day, "close": 100, "volume": 1000} for day in days]


class FixtureClient:
    token = "TEST_ONLY_NOT_A_REAL_TOKEN"

    def dataset(self, dataset, start, end, code=None):
        if dataset == "TaiwanStockTradingDate":
            return [{"date": "2026-11-09"}, {"date": "2026-11-10"}]
        if dataset == DATASETS["price"]:
            return [{"date": "2026-11-10", "stock_id": code, "close": 10, "open": 10, "max": 10, "min": 10, "Trading_Volume": 1000}]
        if dataset == DATASETS["institutional"]:
            return [{"date": "2026-11-10", "stock_id": code, "name": name, "buy": 1000, "sell": 1000} for name in ("Foreign_Investor", "Foreign_Dealer_Self", "Investment_Trust", "Dealer_self", "Dealer_Hedging")]
        if dataset == DATASETS["margin"]:
            return []
        raise AssertionError(dataset)

    def get(self, url, params=None, **kwargs):
        if url == HOLIDAYS:
            return [{"Date": "1150101", "Name": "元旦", "Description": "放假"}]
        raise SourceError("network_error")


class PipelineTests(unittest.TestCase):
    def test_latest_22_symbols(self):
        items = load_watchlist(ROOT / "config/watchlist_public.json")
        self.assertEqual({row["code"] for row in items}, set("3231 3481 3706 4585 6197 6213 6753 1815 2303 2317 2327 2382 2455 2478 2481 3090 00685L 00981A 1301 1312 2009 2301".split()))
        self.assertEqual(next(row["market"] for row in items if row["code"] == "1815"), "TPEX")

    def test_old_16_watchlist_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "watchlist.json"
            path.write_text(json.dumps([{"code": str(index)} for index in range(16)]))
            with self.assertRaises(ValueError):
                load_watchlist(path)

    def test_date_formats(self):
        for value in ("1151110", "20261110", "115/11/10", "2026-11-10"):
            self.assertEqual(iso_date(value), "2026-11-10")

    def test_margin_change_uses_balances(self):
        records = [{"date": "2026-11-10", "stock_id": "2009", "MarginPurchaseTodayBalance": 100, "MarginPurchaseYesterdayBalance": 130, "ShortSaleTodayBalance": 2, "ShortSaleYesterdayBalance": 1}]
        rows, issues = normalize_finmind("margin", records, "2009", "2026-11-01", "2026-11-10")
        self.assertEqual((rows[0]["marginChange"], rows[0]["shortChange"]), (-30, 1))
        self.assertEqual(issues, [])

    def test_missing_institution_is_not_zero(self):
        records = [{"date": "2026-11-10", "stock_id": "2009", "name": "Dealer_self", "buy": 100, "sell": 0}]
        rows, issues = normalize_finmind("institutional", records, "2009", "2026-11-01", "2026-11-10")
        self.assertIsNone(rows[0]["dealer"])
        self.assertIsNone(rows[0]["foreign"])
        self.assertTrue(issues)

    def test_institution_aggregation_and_zero(self):
        records = FixtureClient().dataset(DATASETS["institutional"], "", "", "2009")
        records[0]["buy"] = 1100
        records[1]["sell"] = 1200
        records[3]["buy"] = 1010
        records[4]["sell"] = 1050
        rows, issues = normalize_finmind("institutional", records, "2009", "2026-11-01", "2026-11-10")
        self.assertEqual([rows[0][key] for key in ("foreign", "trust", "dealer")], [-100, 0, -40])
        self.assertEqual(issues, [])

    def test_duplicates_wrong_symbol_invalid_prices(self):
        row = FixtureClient().dataset(DATASETS["price"], "", "", "2009")[0]
        rows, issues = normalize_finmind("price", [row, row], "2009", "2026-11-01", "2026-11-10")
        self.assertFalse(rows)
        self.assertIn("2026-11-10:duplicate", issues)
        for overrides in ({"close": "NaN"}, {"stock_id": "2303"}, {"Trading_Volume": -1}, {"max": 1}):
            rows, issues = normalize_finmind("price", [{**row, **overrides}], "2009", "2026-11-01", "2026-11-10")
            self.assertFalse(rows)
            self.assertTrue(issues)

    def test_official_mismatch_not_verified(self):
        source = {"url": "https://www.twse.com.tw", "status": "ok"}
        latest = {"date": "2026-11-10", "close": 100, "volume": 1000}
        self.assertEqual(compare_official(latest, {**latest, "volume": 2000}, source)["status"], "mismatch")
        self.assertEqual(compare_official(latest, {**latest, "date": "2026-11-09"}, source)["reason"], "date_mismatch")
        self.assertEqual(compare_official(latest, latest, source)["status"], "verified")

    def test_tpex_fields_and_units(self):
        snapshot = {"rows": [{"Date": "1151110", "SecuritiesCompanyCode": "1815", "Close": "12.50", "TradingShares": "12,345"}]}
        row = official_record(snapshot, "TPEX", "price", "1815")
        self.assertEqual(row, {"date": "2026-11-10", "close": 12.5, "volume": 12345})
        snapshot["rows"][0].update({"ForeignInvestorsInclude MainlandAreaInvestors-Difference": "1,000", "SecuritiesInvestmentTrustCompanies-Difference": "-2", "Dealers-Difference": "0"})
        self.assertEqual(official_record(snapshot, "TPEX", "institutional", "1815")["foreign"], 1000)

    def test_dated_twse_price_and_margin_schema(self):
        class OfficialClient:
            def get(self, url, params=None):
                if "afterTrading/MI_INDEX" in url:
                    return {"stat": "OK", "date": "20261110", "tables": [{"fields": ["證券代號", "收盤價", "成交股數"], "data": [["2009", "33.65", "1,666,513"]]}]}
                if "marginTrading/MI_MARGN" in url:
                    return {"stat": "OK", "date": "20261110", "tables": [{"fields": ["代號", "名稱"] + ["balance"] * 14, "data": [["2009", "第一銅", 0, 0, 0, 5398, 5434, 0, 0, 0, 0, 4, 7, 0, 0, ""]]}]}
                if "fund/T86" in url:
                    return {"stat": "OK", "date": "20261110", "fields": ["證券代號"], "data": []}
                return []
        snapshots = official_snapshots(OfficialClient(), "2026-11-10")
        self.assertEqual(official_record(snapshots["TWSE_price"], "TWSE", "price", "2009")["volume"], 1666513)
        record = official_record(snapshots["TWSE_margin"], "TWSE", "margin", "2009")
        self.assertEqual((record["margin"], record["marginPrevious"], record["short"], record["shortPrevious"]), (5434, 5398, 7, 4))

    def test_continuous_buy_sell_breaks_on_gap(self):
        days = sessions(5)
        institutional = [{"date": day, "foreign": 100, "trust": -50} for day in days]
        alerts, _, _ = evaluate([], institutional, [], days, days[-1])
        self.assertEqual({alert["rule"] for alert in alerts}, {"foreign_streak", "trust_streak"})
        institutional.pop(-2)
        alerts, _, _ = evaluate([], institutional, [], days, days[-1])
        self.assertEqual(alerts, [])

    def test_stale_data_does_not_trigger_current_streak(self):
        days = sessions(5)
        alerts, _, missing = evaluate([], [{"date": day, "foreign": 1} for day in days[:-1]], [], days, days[-1])
        self.assertEqual(alerts, [])
        self.assertIn("foreign_streak", missing)

    def test_ma_cross_and_volume_anomaly(self):
        days = sessions()
        prices = history(days)
        prices[-1].update(close=90, volume=3000)
        alerts, indicators, _ = evaluate(prices, [], [], days, days[-1])
        rules = {alert["rule"] for alert in alerts}
        self.assertTrue({"cross_below_ma20", "cross_below_ma60", "abnormal_volume"} <= rules)
        self.assertEqual(indicators["volumeRatio"], 3)
        self.assertAlmostEqual(indicators["ma20"], 99.5)

    def test_insufficient_history_has_no_fake_ma(self):
        days = sessions(5)
        alerts, indicators, missing = evaluate(history(days), [], [], days, days[-1])
        self.assertEqual(alerts, [])
        self.assertIsNone(indicators["ma20"])
        self.assertIn("ma60", missing)

    def test_margin_surge_and_deleveraging(self):
        days = sessions()
        prices = history(days)
        margin = [{"date": days[-1], "marginPrevious": 1000, "marginChange": 101}]
        alerts, _, _ = evaluate(prices, [], margin, days, days[-1])
        self.assertIn("margin_surge", {alert["rule"] for alert in alerts})
        prices[-1]["close"] = 90
        margin[0]["marginChange"] = -1
        alerts, _, _ = evaluate(prices, [], margin, days, days[-1])
        self.assertIn("deleveraging_drop", {alert["rule"] for alert in alerts})

    def test_blocked_price_suppresses_price_alerts(self):
        days = sessions()
        prices = history(days)
        prices[-1]["close"] = 10
        alerts, _, missing = evaluate(prices, [], [], days, days[-1], ["price"])
        self.assertFalse(alerts)
        self.assertIn("price_rules", missing)

    def test_closed_day_and_delayed_day_distinct(self):
        client = FixtureClient()
        self.assertEqual(calendar_context(client, "2026-11-14", "2026-01-01")["status"], "non_trading_day")
        self.assertEqual(calendar_context(client, "2026-11-11", "2026-01-01")["status"], "awaiting_confirmation")
        original = client.get
        client.get = lambda url, **kwargs: [{"Date": "1151111", "Name": "休市", "Description": "放假"}] if url == HOLIDAYS else original(url, **kwargs)
        context = calendar_context(client, "2026-11-11", "2026-01-01")
        self.assertEqual(context["targetDate"], "2026-11-10")
        self.assertEqual(context["status"], "non_trading_day")

    def test_bank_permission_placeholder_does_not_query(self):
        class Forbidden:
            def dataset(self, *args):
                raise AssertionError("disabled provider must not query")
        result = government_bank(Forbidden(), "2009", "2026-11-01", "2026-11-10")
        self.assertEqual(result["label"], "無權限")
        self.assertIsNone(result["netBuy"])

    def test_bank_permission_recheck(self):
        class Denied:
            def dataset(self, *args):
                raise SourceError("permission_denied")
        self.assertEqual(government_bank(Denied(), "2009", "2026-11-01", "2026-11-10", True)["label"], "無權限")

    def test_public_rejects_private_fields_and_token(self):
        for payload in ({"nested": {"shares": 1}}, {"unrealizedPnlRate": 1}, {"nested": ["a SECRET b"]}):
            with self.assertRaises(ValueError):
                assert_public(payload, "SECRET")

    def test_token_header_never_query_or_error(self):
        requests = []
        def fake_open(request, **kwargs):
            requests.append(request)
            raise URLError("SECRET sensitive")
        with patch("market_pipeline.sources.urlopen", fake_open):
            with self.assertRaisesRegex(SourceError, "^network_error$"):
                HttpClient("SECRET", attempts=1).dataset("TaiwanStockPrice", "2026-11-01", "2026-11-10", "2009")
        self.assertNotIn("SECRET", requests[0].full_url)
        self.assertEqual(requests[0].get_header("Authorization"), "Bearer SECRET")

    def test_retry_and_permission_error(self):
        failures = [HTTPError(FINMIND, 429, "limited SECRET", {}, None), HTTPError(FINMIND, 503, "SECRET", {}, None)]
        with patch("market_pipeline.sources.urlopen", side_effect=failures), patch("time.sleep") as sleep:
            with self.assertRaisesRegex(SourceError, "^http_503$"):
                HttpClient("SECRET", attempts=2, sleep=sleep).get(FINMIND)
            sleep.assert_called_once()
        denied = HTTPError(FINMIND, 400, "SECRET", {}, io.BytesIO(b"Your level is register. Please update your user level."))
        with patch("market_pipeline.sources.urlopen", side_effect=denied):
            with self.assertRaisesRegex(SourceError, "^permission_denied$"):
                HttpClient("SECRET").get(FINMIND, authenticated=True)

    def test_end_to_end_22_etfs_partial_and_outputs(self):
        payload = collect(FixtureClient(), load_watchlist(ROOT / "config/watchlist_public.json"), datetime(2026, 11, 11, 21, tzinfo=TAIPEI))
        self.assertEqual(len(payload["stocks"]), 22)
        self.assertEqual(payload["reportStatus"], "partial")
        for stock in payload["stocks"]:
            self.assertIsNone(stock["totalScore"])
            self.assertIsNone(stock["latest"]["margin"])
            self.assertEqual(stock["quality"]["price"]["status"], "delayed")
        etfs = [stock for stock in payload["stocks"] if stock["code"] in ("00685L", "00981A")]
        self.assertTrue(all(stock["fundamentals"]["status"] == "not_applicable" for stock in etfs))
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            write_outputs(payload, destination, FixtureClient.token)
            self.assertEqual(len(json.loads((destination / "stocks.json").read_text(encoding="utf-8"))["stocks"]), 22)
            self.assertNotIn(FixtureClient.token, (destination / "daily-report.md").read_text(encoding="utf-8"))

    def test_news_failure_not_no_news(self):
        reports = collect_news(FixtureClient(), datetime(2026, 11, 11, tzinfo=TAIPEI))
        self.assertTrue(all(report["status"] == "network_error" for report in reports))

    def test_news_unknown_date_not_today(self):
        parser = AnnouncementParser("https://www.mof.gov.tw/multiplehtml/383")
        parser.feed('<a href="/singlehtml/example">國安基金委員會決議</a>')
        self.assertIsNone(parser.links[0]["publishedDate"])

    def test_official_news_row_date_and_navigation(self):
        parser = AnnouncementParser("https://www.fsc.gov.tw/ch/home.jsp")
        parser.feed('<a href="/ch/home.jsp?id=1">重大政策</a><li><span>115-11-06</span><a href="/ch/home.jsp?dataserno=123">調整融券保證金成數</a></li>')
        self.assertEqual(len(parser.links), 1)
        self.assertEqual(parser.links[0]["publishedDate"], "2026-11-06")

    def test_fees_and_tax_private_only(self):
        result = liquidation_pnl(1000, 100, 110, buy_fee_rate=0.001425, sell_fee_rate=0.001425, sell_tax_rate=0.003)
        self.assertEqual(result["pnl"], 9370)
        self.assertEqual(result["sell_tax"], 330)
        etf = liquidation_pnl(1000, 100, 110, buy_fee_rate=0.001425, sell_fee_rate=0.001425, sell_tax_rate=0.001)
        self.assertEqual(etf["pnl"], 9590)
        with self.assertRaises(ValueError):
            liquidation_pnl(0, 100, 110, buy_fee_rate=0, sell_fee_rate=0, sell_tax_rate=0)

    def test_workflow_has_no_secret_for_prs(self):
        tests = (ROOT / ".github/workflows/tests.yml").read_text()
        self.assertNotIn("secrets.", tests)
        daily = (ROOT / ".github/workflows/daily-report.yml").read_text()
        self.assertIn('0,20,40 13 * * 1-5', daily)
        self.assertIn("refs/heads/main", daily)
        self.assertNotIn("git push", daily)


if __name__ == "__main__":
    unittest.main()

