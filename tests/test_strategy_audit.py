import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from market_pipeline.strategy_audit import audit


def sessions():
    result = []
    day = date(2026, 10, 1)
    while len(result) < 30:
        if day.weekday() < 5:
            result.append(day.isoformat())
        day += timedelta(days=1)
    return result


DAYS = sessions()
AS_OF = DAYS[18]


def signal(index=1, horizon=5):
    return {"selectionDate": DAYS[index], "publishedAt": DAYS[index]+"T21:00:00+08:00",
            "code": "2303", "strategyId": "rsi14", "strategyVersion": "v1",
            "horizon": horizon, "shares": 1000, "source": "verified_signal"}


def prices(close=101):
    return {"2303": {"corporateActionsChecked": True,
                     "prices": [{"date": day, "open": 100, "close": close} for day in DAYS]}}


class AuditTests(unittest.TestCase):
    def test_next_open_and_cost_adjusted_outcome(self):
        result = audit([signal()], DAYS, prices(), AS_OF)
        trade = result["trades"][0]
        self.assertEqual(trade["entryDate"], DAYS[2])
        self.assertEqual(trade["exitDate"], DAYS[6])
        self.assertEqual(trade["grossPnl"], 1000)
        self.assertEqual(trade["buyFeeEstimate"], 43)
        self.assertEqual(trade["sellFeeEstimate"], 43)
        self.assertEqual(trade["taxEstimate"], 303)
        self.assertEqual(trade["netPnl"], 611)
        self.assertTrue(trade["win"])
        self.assertEqual(result["byStrategy"][0]["assessment"], "no_taiwan_benchmark")

    def test_winning_gross_losing_net_traces_fees(self):
        r = audit([signal()], DAYS, prices(close=100.1), AS_OF)
        self.assertFalse(r["trades"][0]["win"])
        self.assertIn("fee_tax_erased_profit", r["trades"][0]["diagnosis"])

    def test_unmatured_does_not_count_as_loss(self):
        r = audit([signal(index=17, horizon=5)], DAYS, prices(), AS_OF)
        self.assertEqual(r["status"], "no_matured_recommendations")
        self.assertEqual(r["unresolved"]["unmatured"], 1)
        self.assertEqual(r["byStrategy"], [])

    def test_missing_prices_or_adjustment_marked_unknown(self):
        p = prices()
        p["2303"]["corporateActionsChecked"] = False
        self.assertEqual(audit([signal()], DAYS, p, AS_OF)["unresolved"]["unverified_corporate_actions"], 1)
        p = prices()
        p["2303"]["prices"] = []
        self.assertEqual(audit([signal()], DAYS, p, AS_OF)["unresolved"]["missing_executable_prices"], 1)

    def test_duplicate_and_taipei_timestamp_invalid(self):
        with self.assertRaisesRegex(ValueError, "duplicate_signal"):
            audit([signal(), signal()], DAYS, prices(), AS_OF)
        s = signal()
        s["publishedAt"] = DAYS[1]+"T21:00:00Z"
        with self.assertRaisesRegex(ValueError, "taipei_publication_time_required"):
            audit([s], DAYS, prices(), AS_OF)

    def test_reject_etf_as_stock_tax_basis(self):
        s = signal()
        s["instrumentType"] = "etf"
        with self.assertRaisesRegex(ValueError, "tax_model_stock_only"):
            audit([s], DAYS, prices(), AS_OF)

    def test_one_trade_not_enough_to_claim_degradation(self):
        r = audit([signal()], DAYS, prices(close=99), AS_OF, taiwan_targets={"rsi14": 0.81})
        self.assertEqual(r["byStrategy"][0]["assessment"], "sample_insufficient")
        self.assertEqual(r["byStrategy"][0]["winRate"], 0)
        self.assertIn("price_decline", r["byStrategy"][0]["failureDrivers"])

    def test_zero_trades_is_not_a_win_rate(self):
        r = audit([], DAYS, prices(), AS_OF)
        self.assertEqual(r["status"], "no_matured_recommendations")
        self.assertEqual(r["maturedTrades"], 0)
        self.assertEqual(r["byStrategy"], [])


if __name__ == "__main__":
    unittest.main()
