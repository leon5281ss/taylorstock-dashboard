import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from market_pipeline.quant_screen import WEIGHTS, metrics, official_universe, roster, screen


def days(n=130):
    out = []
    day = date(2026, 5, 15)
    while len(out) < n:
        if day.weekday() < 5:
            out.append(day.isoformat())
        day += timedelta(days=1)
    return out


DAYS = days()
AS_OF = DAYS[-1]


def stock_data(code, market, tilt=0):
    prices = [{"date": day, "close": 50 + i * (0.1 + tilt),
               "volume": 1000 + i, "turnover": 20000000} for i, day in enumerate(DAYS)]
    inst = [{"date": day, "foreign": 50 + tilt * 20, "trust": 5 + tilt} for day in DAYS[-5:]]
    margin = [{"date": day, "balance": 200 - i} for i, day in enumerate(DAYS[-5:])]
    borrow = [{"date": day, "balance": 100 - i} for i, day in enumerate(DAYS[-5:])]
    return {"asOf": AS_OF, "market": market, "corporateActionsChecked": True,
            "prices": prices, "institutional": inst, "margin": margin, "borrow": borrow,
            "tdcc": {"date": AS_OF, "largeHolderRatio": 0.5},
            "fundamentals": {"eps5y": [5, 6, 7, 8, 9],
                             "epsTTM": 10, "roe": 0.12 + tilt / 100,
                             "revenueYoY": 0.2, "operatingMargin": 0.16,
                             "financialPublishedAt": AS_OF, "revenuePublishedAt": AS_OF},
            "valuation": {"date": AS_OF, "pe": 15, "pb": 2, "dividendYield": 0.05}}


def official():
    return {"markets": {"TWSE": {"2303": {"code": "2303", "name": "聯電", "market": "TWSE"}},
                        "TPEX": {"1815": {"code": "1815", "name": "富喬", "market": "TPEX"}}},
            "sources": {}, "errors": {}}


class QuantScreenTests(unittest.TestCase):
    def test_weights_exact_and_no_neutral_imputation(self):
        self.assertEqual(WEIGHTS, {"technical": .35, "chips": .25,
                                   "fundamental": .25, "valuationRisk": .15})
        result = screen(official(), {}, AS_OF, minimum=(1, 1))
        self.assertEqual(result["status"], "not_publishable")
        self.assertIsNone(result["top10"])
        self.assertEqual(result["missingCount"], 2)

    def test_full_market_guard_rejects_small_watchlist(self):
        data = {"2303": stock_data("2303", "TWSE"), "1815": stock_data("1815", "TPEX")}
        self.assertIsNone(screen(official(), data, AS_OF)["top10"])

    def test_verified_toy_fixture_only_when_test_minimum_explicit(self):
        data = {"2303": stock_data("2303", "TWSE", 0.2),
                "1815": stock_data("1815", "TPEX", 0)}
        result = screen(official(), data, AS_OF, minimum=(1, 1))
        self.assertEqual(result["status"], "ready")
        self.assertEqual(len(result["top10"]), 2)
        self.assertAlmostEqual(sum(result["top10"][0]["factorScores"][k] * WEIGHTS[k]
                                   for k in WEIGHTS), result["top10"][0]["score"], places=1)

    def test_missing_tdcc_borrow_fundamentals_and_date_blocks(self):
        checks = [("tdcc", None), ("borrow", []), ("fundamentals", {}), ("valuation", {})]
        for key, value in checks:
            with self.subTest(key=key):
                data = {"2303": stock_data("2303", "TWSE"), "1815": stock_data("1815", "TPEX")}
                data["2303"][key] = value
                result = screen(official(), data, AS_OF, minimum=(1, 1))
                self.assertIsNone(result["top10"])
                self.assertEqual(result["factorCompleteCount"], 1)
        data = {"2303": stock_data("2303", "TWSE"), "1815": stock_data("1815", "TPEX")}
        data["1815"]["valuation"]["date"] = "2026-01-01"
        self.assertIsNone(screen(official(), data, AS_OF, minimum=(1, 1))["top10"])

    def test_official_roster_filters_funds_and_cross_market_overlap(self):
        rows = [{"公司代號": "2303", "公司簡稱": "聯電"},
                {"公司代號": "0050", "公司簡稱": "ETF"},
                {"公司代號": "00685L", "公司簡稱": "ETF"},
                {"公司代號": "1802", "公司簡稱": "台玻"}]
        self.assertEqual(set(roster(rows, "TWSE")), {"2303", "1802"})
        source = official_universe(
            lambda url: rows if "t187ap03_L" in url else [
                {"SecuritiesCompanyCode": "1815", "CompanyName": "富喬"}],
            minimum=(2, 1))
        self.assertEqual(source["errors"], {})
        self.assertEqual(sum(len(x) for x in source["markets"].values()), 3)

    def test_invalid_future_disclosure_and_low_quality_history(self):
        row = stock_data("2303", "TWSE")
        row["fundamentals"]["financialPublishedAt"] = "2027-01-01"
        with self.assertRaises(ValueError):
            metrics(row, AS_OF)
        row = stock_data("2303", "TWSE")
        row["corporateActionsChecked"] = False
        with self.assertRaises(ValueError):
            metrics(row, AS_OF)

    def test_if_one_official_market_unavailable_no_top10(self):
        official_input = official()
        official_input["errors"]["TPEX"] = "official_roster_unavailable"
        d = {"2303": stock_data("2303", "TWSE"), "1815": stock_data("1815", "TPEX")}
        self.assertEqual(screen(official_input, d, AS_OF, minimum=(1, 1))["status"],
                         "not_publishable")


if __name__ == "__main__":
    unittest.main()
