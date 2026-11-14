"""Offline TWSE/TPEx official historical flow accounting invariants."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import collect_institutional_history as inst


DAY = "2026-11-13"
TWSE_FIELDS = [
    "證券代號", "證券名稱",
    "外陸資買進股數(不含外資自營商)",
    "外陸資賣出股數(不含外資自營商)",
    "外陸資買賣超股數(不含外資自營商)",
    "外資自營商買進股數", "外資自營商賣出股數", "外資自營商買賣超股數",
    "投信買進股數", "投信賣出股數", "投信買賣超股數",
    "自營商買賣超股數", "自營商買進股數(自行買賣)",
    "自營商賣出股數(自行買賣)", "自營商買賣超股數(自行買賣)",
    "自營商買進股數(避險)", "自營商賣出股數(避險)", "自營商買賣超股數(避險)",
    "三大法人買賣超股數",
]


def twse_row():
    return ["2330", "台積電", "200", "100", "100", "10", "5", "5",
            "20", "10", "10", "7", "15", "12", "3", "7", "3", "4", "117"]


def tpex_row():
    return ["6488", "環球晶", "200", "100", "100", "5", "2", "3",
            "205", "102", "103", "30", "20", "10",
            "15", "12", "3", "11", "7", "4",
            "26", "19", "7", "117"]


def twse(row=None, day="20261113"):
    return {"stat": "OK", "date": day, "fields": TWSE_FIELDS,
            "data": [row if row is not None else twse_row()]}


def tpex(row=None, day="115/11/13"):
    return {"stat": "ok", "date": day, "tables": [
        {"fields": inst.TPEX_HEADERS,
         "data": [row if row is not None else tpex_row()]}]}


def roster():
    return {"errors": {}, "markets": {"TWSE": {"2330": {}}, "TPEX": {"6488": {}}}}


class InstitutionalHistoryTests(unittest.TestCase):
    def test_exact_source_position_accounting(self):
        x = inst.normalized_rows(twse(), "TWSE", DAY, {"2330": {}}, min_coverage=1)[0]
        self.assertEqual((x["foreignNet"], x["trustNet"], x["dealerNet"], x["totalNet"]),
                         (100, 10, 7, 117))
        self.assertEqual(x["foreignDealerNetNotAddedToForeign"], 5)
        y = inst.normalized_rows(tpex(), "TPEX", DAY, {"6488": {}}, min_coverage=1)[0]
        self.assertEqual((y["foreignNet"], y["trustNet"], y["dealerNet"], y["totalNet"]),
                         (100, 10, 7, 117))
        self.assertEqual((y["dealerSelfNet"], y["dealerHedgeNet"]), (3, 4))

    def test_tpex_total_and_triples_fail_closed(self):
        row = tpex_row()
        row[23] = "118"
        with self.assertRaisesRegex(inst.InstitutionalError, "accounting_invariant_failed"):
            inst.normalized_rows(tpex(row), "TPEX", DAY, {"6488": {}}, min_coverage=1)
        row = tpex_row()
        row[7] = "9"
        with self.assertRaisesRegex(inst.InstitutionalError, "accounting_invariant_failed"):
            inst.normalized_rows(tpex(row), "TPEX", DAY, {"6488": {}}, min_coverage=1)

    def test_twse_foreign_gross_not_used_as_net(self):
        row = twse_row()
        row[4] = "200"
        with self.assertRaisesRegex(inst.InstitutionalError, "accounting_invariant_failed"):
            inst.normalized_rows(twse(row), "TWSE", DAY, {"2330": {}}, min_coverage=1)

    def test_tpex_repeated_column_order_is_mandatory(self):
        data = tpex()
        data["tables"][0]["fields"][4] = "外資買賣超股數"
        with self.assertRaisesRegex(inst.InstitutionalError, "positions_changed"):
            inst.normalized_rows(data, "TPEX", DAY, {"6488": {}}, min_coverage=1)

    def test_missing_net_not_fabricated_zero(self):
        row = twse_row()
        row[10] = "--"
        with self.assertRaisesRegex(inst.InstitutionalError, "coverage_insufficient"):
            inst.normalized_rows(twse(row), "TWSE", DAY, {"2330": {}}, min_coverage=1)

    def test_historical_investor_date_mismatch_blocks(self):
        with self.assertRaisesRegex(inst.InstitutionalError, "date_mismatch"):
            inst.normalized_rows(tpex(day="115/11/12"), "TPEX",
                                 DAY, {"6488": {}}, min_coverage=1)

    def test_duplicate_stock_code_fails(self):
        payload = twse()
        payload["data"].append(twse_row())
        with self.assertRaisesRegex(inst.InstitutionalError, "duplicate"):
            inst.normalized_rows(payload, "TWSE", DAY, {"2330": {}}, min_coverage=1)

    def test_both_markets_research_only_not_top10(self):
        with patch.object(inst, "official_universe", return_value=roster()):
            urls = []
            def fetch(url):
                urls.append(url)
                return json.dumps(tpex() if "tpex.org.tw" in url else twse())
            result = inst.official_institutional_day(
                DAY, fetch=fetch, sleep=lambda _: None, min_coverage=1)
        self.assertEqual(len(urls), 2)
        self.assertEqual(result["marketCounts"], {"TWSE": 1, "TPEX": 1})
        self.assertEqual(len(result["rows"]), 2)
        self.assertEqual(result["asOf"], DAY)
        self.assertEqual(result["status"], "institutional_history_research_only")
        self.assertTrue(result["institutionalAccountIdentitiesVerified"])
        self.assertFalse(result["historicalPointInTimeCompanyUniverse"])
        self.assertIsNone(result["top10"])
        self.assertFalse(result["publishable"])


if __name__ == "__main__":
    unittest.main()
