"""TWSE/TPEx date-verified margin balances cannot be interpreted as shares."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"scripts"))
import collect_margin_research as margin


DAY = "2026-11-13"


def twse():
    return {"stat": "OK", "date": "20261113", "tables": [{
        "fields": list(margin.TWSE_FIELDS),
        "data": [[str(1000+i), "上市公司", "10", "5", "1", "100",
                  "104", "10000", "3", "2", "0", "20", "21",
                  "1000", "0", ""] for i in range(200)]}]}


def tpex():
    return {"stat": "ok", "date": "115/11/13", "tables": [{
        "fields": list(margin.TPEX_FIELDS),
        "data": [[str(6000+i), "上櫃公司", "100", "10", "5", "1",
                  "104", "5", "10.5", "10000", "20",
                  "2", "3", "0", "21", "1", "8", "1000", "0", ""]
                 for i in range(200)]}]}


def universe():
    return {"errors": {}, "markets": {
        "TWSE": {str(1000+i): {} for i in range(200)},
        "TPEX": {str(6000+i): {} for i in range(200)}}}


class MarginResearchTests(unittest.TestCase):
    def test_report_balances_keep_source_units(self):
        a = margin.parse_market(twse(), "TWSE", DAY,
                                universe()["markets"]["TWSE"])
        b = margin.parse_market(tpex(), "TPEX", DAY,
                                universe()["markets"]["TPEX"])
        self.assertEqual(len(a), 200)
        self.assertEqual(len(b), 200)
        self.assertEqual(a[0]["marginPrevious"], 100)
        self.assertEqual(a[0]["marginCurrent"], 104)
        self.assertEqual(b[0]["marginPrevious"], 100)
        self.assertEqual(b[0]["shortCurrent"], 21)
        self.assertEqual(a[0]["sourceBalanceUnit"],
                         "twse_trading_unit_not_proven_shares")
        self.assertEqual(b[0]["sourceBalanceUnit"], "tpex_explicit_lots")

    def test_source_column_order_changed_fails_closed(self):
        data = twse()
        data["tables"][0]["fields"][6] = "不存在"
        with self.assertRaisesRegex(margin.MarginHistoryError, "column_order_changed"):
            margin.parse_market(data, "TWSE", DAY, universe()["markets"]["TWSE"])

    def test_date_mismatch_blocks(self):
        data = tpex()
        data["date"] = "115/11/12"
        with self.assertRaisesRegex(margin.MarginHistoryError, "source_invalid"):
            margin.parse_market(data, "TPEX", DAY, universe()["markets"]["TPEX"])

    def test_invalid_balance_not_fabricated_zero(self):
        data = tpex()
        for row in data["tables"][0]["data"][:120]:
            row[14] = "--"
        with self.assertRaisesRegex(margin.MarginHistoryError, "coverage_low"):
            margin.parse_market(data, "TPEX", DAY, universe()["markets"]["TPEX"])

    def test_duplicate_code_blocks(self):
        data = twse()
        data["tables"][0]["data"][1][0] = data["tables"][0]["data"][0][0]
        with self.assertRaisesRegex(margin.MarginHistoryError, "duplicate_margin_symbol"):
            margin.parse_market(data, "TWSE", DAY, universe()["markets"]["TWSE"])

    def test_offline_collect_blocks_trade_use(self):
        with patch.object(margin, "official_universe", return_value=universe()):
            def fetch(url):
                return json.dumps(tpex() if "tpex.org.tw" in url else twse())
            result = margin.collect(DAY, fetch=fetch, sleep=lambda _: None)
        self.assertEqual(result["marketCounts"], {"TWSE": 200, "TPEX": 200})
        self.assertTrue(result["unitsNotCrossMarketNormalized"])
        self.assertFalse(result["sourceBalanceSharesConverted"])
        self.assertFalse(result["currentBalanceAvailableDuringTradingSession"])
        self.assertFalse(result["marginFactorReady"])
        self.assertFalse(result["publishable"])
        self.assertIsNone(result["top10"])


if __name__ == "__main__":
    unittest.main()
