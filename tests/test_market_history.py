"""Offline ingestion tests. No network access, tokens, or market-data guessing."""
import gzip
import sys
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from collect_market_history import (IngestionError, compressed_snapshot,
                                    make_snapshot, number, parse_market,
                                    roc_to_iso, row_to_price)


def universe():
    return {"markets": {
        "TWSE": {"2330": {"code": "2330", "name": "台積電", "market": "TWSE"}},
        "TPEX": {"6488": {"code": "6488", "name": "環球晶", "market": "TPEX"}}
    }, "errors": {}, "sources": {}}


def twse(day="1151111", code="2330"):
    return {"Date": day, "Code": code, "Name": "台積電", "OpeningPrice": "100",
            "HighestPrice": "103", "LowestPrice": "99", "ClosingPrice": "101.5",
            "TradeVolume": "1,234", "TradeValue": "125,000",
            "Transaction": "100"}


def tpex(day="1151111", code="6488"):
    return {"Date": day, "SecuritiesCompanyCode": code, "CompanyName": "環球晶",
            "Open": "500.0 ", "High": "511", "Low": "498", "Close": "505",
            "TradingShares": "30,000", "TransactionAmount": "15,100,000",
            "TransactionNumber": "200"}


NOW = datetime(2026, 11, 12, 12, tzinfo=ZoneInfo("Asia/Taipei"))


class MarketHistoryTests(unittest.TestCase):
    def setUp(self):
        self.universe = universe()
        self.rows = {"TWSE": [twse()], "TPEX": [tpex()]}

    def snapshot(self):
        return make_snapshot(self.universe, self.rows, NOW,
                             minimum={"TWSE": 1, "TPEX": 1})

    def test_roc_dates_strict(self):
        self.assertEqual(roc_to_iso("1151111"), "2026-11-11")
        self.assertEqual(roc_to_iso("115/11/11"), "2026-11-11")
        self.assertEqual(roc_to_iso("20261111"), "2026-11-11")
        for text in ("", "1151131", "1151", "115/1/1", "garbage"):
            with self.subTest(text=text), self.assertRaises(IngestionError):
                roc_to_iso(text)

    def test_numeric_missing_and_finite(self):
        self.assertEqual(number("1,234", integer=True), 1234)
        self.assertEqual(number("101.50"), 101.5)
        for x in ("-", "", None, "nan", "Infinity", "not-price", True):
            self.assertIsNone(number(x))

    def test_convert_both_markets(self):
        s = self.snapshot()
        self.assertEqual(s["asOf"], "2026-11-11")
        self.assertEqual(s["marketCounts"], {"TWSE": 1, "TPEX": 1})
        self.assertEqual(len(s["stocks"]), 2)
        self.assertEqual(s["priceAdjustment"], "raw_unadjusted")
        self.assertEqual({x["code"] for x in s["stocks"]}, {"2330", "6488"})
        self.assertEqual(next(x for x in s["stocks"] if x["code"] == "2330")["volume"], 1234)

    def test_filter_unlisted_etfs_and_warrants(self):
        rows = [twse(), twse(code="0050"), twse(code="23030")]
        result = parse_market(rows, "TWSE", self.universe, minimum=1)
        self.assertEqual([r["code"] for r in result["stocks"]], ["2330"])

    def test_suspended_price_not_filled_with_zero(self):
        row = twse()
        row["ClosingPrice"] = "--"
        self.assertIsNone(row_to_price(row, "TWSE"))

    def test_negative_volume_rejected(self):
        row = twse()
        row["TradeVolume"] = "-10"
        self.assertIsNone(row_to_price(row, "TWSE"))

    def test_invalid_ohlc_rejected(self):
        row = twse()
        row["HighestPrice"] = "100"
        with self.assertRaisesRegex(IngestionError, "ohlc_invariant_broken"):
            row_to_price(row, "TWSE")

    def test_exchange_date_mismatch_fails_closed(self):
        self.rows["TPEX"][0]["Date"] = "1151110"
        with self.assertRaisesRegex(IngestionError, "exchange_dates_mismatch"):
            self.snapshot()

    def test_mixed_date_same_market_fails_closed(self):
        self.universe["markets"]["TWSE"]["2303"] = {"code": "2303", "name": "聯電", "market": "TWSE"}
        self.rows["TWSE"].append(twse(day="1151110", code="2303"))
        with self.assertRaisesRegex(IngestionError, "mixed_or_missing_official_dates"):
            self.snapshot()

    def test_duplicate_official_code_fails_closed(self):
        self.rows["TWSE"].append(twse())
        with self.assertRaisesRegex(IngestionError, "duplicate_official_code"):
            self.snapshot()

    def test_coverage_insufficient_does_not_publish(self):
        self.universe["markets"]["TWSE"].update({
            x: {"code": x, "market": "TWSE"} for x in ("2303", "2317", "2324")
        })
        with self.assertRaisesRegex(IngestionError, "insufficient_valid_quotes"):
            self.snapshot()

    def test_missing_official_market_fails_closed(self):
        self.universe["errors"]["TPEX"] = "official_roster_unavailable"
        with self.assertRaisesRegex(IngestionError, "official_roster_errors"):
            self.snapshot()

    def test_future_or_stale_snapshot_rejected(self):
        for day in ("1151113", "1151102"):
            with self.subTest(day=day):
                self.rows["TWSE"][0]["Date"] = day
                self.rows["TPEX"][0]["Date"] = day
                with self.assertRaisesRegex(IngestionError, "stale_or_future_quote"):
                    self.snapshot()

    def test_deterministic_gzip_json_roundtrip(self):
        s = self.snapshot()
        a, b = compressed_snapshot(s), compressed_snapshot(s)
        self.assertEqual(a, b)
        self.assertEqual(__import__("json").loads(gzip.decompress(a))["asOf"],
                         "2026-11-11")

    def test_no_private_keys_or_holdings_in_schema(self):
        s = self.snapshot()
        for forbidden in ("token", "chatId", "costBasis", "sharesHeld", "account"):
            self.assertNotIn(forbidden, str(s))

    def test_market_overlap_fails_closed(self):
        self.universe["markets"]["TPEX"]["2330"] = {"code": "2330", "market": "TPEX"}
        with self.assertRaisesRegex(IngestionError, "duplicate_company_in_universe"):
            self.snapshot()


if __name__ == "__main__":
    unittest.main()
