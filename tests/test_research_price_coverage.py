"""Safe close-price presence counts without mixing market volume scopes."""
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from collect_market_history import compressed_snapshot
from research_price_coverage import CoverageError, audit_coverage, load_snapshot


def payload(day, *, historical=False, missing_tpex=False):
    rows = [
        {"market": "TWSE", "code": "2330", "open": 100,
         "high": 102, "low": 99, "close": 101, "volume": 10000, "turnover": 1010000}]
    if not missing_tpex:
        rows.append({"market": "TPEX", "code": "6488", "open": 40,
                     "high": 42, "low": 39, "close": 41, "volume": 3000,
                     "turnover": 123000})
    s = {"schemaVersion": 1, "asOf": day, "priceAdjustment": "raw_unadjusted",
         "marketCounts": {"TWSE": 1, "TPEX": 0 if missing_tpex else 1},
         "stocks": rows}
    if historical:
        s.update({"status": "historical_pilot_research_only",
                  "pointInTimeUniverse": False,
                  "mixedVolumeWithDailyOpenAPI": False,
                  "volumeScopes": {"TWSE": "twse_all_trades_shares",
                                   "TPEX": "tpex_round_lot_shares"},
                  "sourceDateEvidence": {"TWSE": "explicit_response_date",
                                         "TPEX": "query_only_unverified"}})
    return s


class ResearchPriceCoverageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.daily = self.root/"daily"
        self.history = self.root/"history"
        self.daily.mkdir(); self.history.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, day, *, history=False, missing_tpex=False):
        directory = self.history if history else self.daily
        path = directory/(day + ".json.gz")
        path.write_bytes(compressed_snapshot(
            payload(day, historical=history, missing_tpex=missing_tpex)))
        return path

    def audit(self):
        return audit_coverage(self.daily, self.history,
                              today=date(2026, 11, 14), minimum=(1, 1))

    def test_one_day_only_never_invents_five_or_121(self):
        self.put("2026-11-13")
        result = self.audit()
        self.assertEqual(result["productionDays"], 1)
        self.assertEqual(result["historicalResearchDays"], 0)
        self.assertEqual(result["pricePresenceByWindow"]["121"],
                         {"TWSE": 0, "TPEX": 0})
        self.assertIsNone(result["top10"])
        self.assertFalse(result["publishable"])

    def test_historical_close_prices_are_counted_without_volume_blending(self):
        for day in ("2026-11-04", "2026-11-05", "2026-11-06",
                    "2026-11-09", "2026-11-10"):
            self.put(day, history=True)
        self.put("2026-11-11")
        result = self.audit()
        self.assertEqual(result["totalObservedDates"], 6)
        self.assertEqual(result["productionDays"], 1)
        self.assertEqual(result["historicalResearchDays"], 5)
        self.assertEqual(result["historicalSourceDateNotExplicitCount"], 5)
        self.assertEqual(result["pricePresenceByWindow"]["5"],
                         {"TWSE": 1, "TPEX": 1})
        self.assertEqual(result["pricePresenceByWindow"]["121"],
                         {"TWSE": 0, "TPEX": 0})
        self.assertFalse(result["volumeScopeCompatible"])
        self.assertFalse(result["corporateActionAdjusted"])

    def test_intermittent_absence_does_not_fill_missing_symbols(self):
        day = date(2026, 11, 4)
        for n in range(4):
            self.put((day + timedelta(days=n)).isoformat(),
                     history=True, missing_tpex=(n == 1))
        self.put("2026-11-11")
        result = self.audit()
        self.assertEqual(result["pricePresenceByWindow"]["5"]["TWSE"], 1)
        self.assertEqual(result["pricePresenceByWindow"]["5"]["TPEX"], 0)

    def test_histories_never_overlap_production_without_manual_review(self):
        self.put("2026-11-11", history=True)
        self.put("2026-11-11")
        with self.assertRaisesRegex(CoverageError, "overlapping_source_dates"):
            self.audit()

    def test_reject_mislabelled_adjustment_status(self):
        p = payload("2026-11-10", historical=True)
        p["pointInTimeUniverse"] = True
        path = self.history/"2026-11-10.json.gz"
        path.write_bytes(compressed_snapshot(p))
        with self.assertRaisesRegex(CoverageError, "point_in_time_claim_invalid"):
            load_snapshot(path, historical=True, minimum=(1, 1))

    def test_reject_tpex_volume_scope_misrepresentation(self):
        p = payload("2026-11-10", historical=True)
        p["volumeScopes"]["TPEX"] = "tpex_openapi_all_sessions_shares"
        path = self.history/"2026-11-10.json.gz"
        path.write_bytes(compressed_snapshot(p))
        with self.assertRaisesRegex(CoverageError, "missing_tpex_volume_scope"):
            load_snapshot(path, historical=True, minimum=(1, 1))

    def test_reject_bad_price_and_duplicate_market_code(self):
        p = payload("2026-11-13")
        p["stocks"][0]["close"] = float("nan")
        path = self.daily/"2026-11-13.json.gz"
        path.write_bytes(compressed_snapshot(p)) if False else path.write_bytes(__import__("gzip").compress(
            __import__("json").dumps(p, allow_nan=True).encode()))
        with self.assertRaisesRegex(CoverageError, "invalid_ohlc"):
            load_snapshot(path, historical=False, minimum=(1, 1))
        p = payload("2026-11-13")
        p["stocks"].append(dict(p["stocks"][0]))
        p["marketCounts"]["TWSE"] = 2
        path.write_bytes(compressed_snapshot(p))
        with self.assertRaisesRegex(CoverageError, "duplicate_market_code"):
            load_snapshot(path, historical=False, minimum=(1, 1))

    def test_reject_bad_gzip(self):
        p = self.daily/"2026-11-13.json.gz"
        p.write_bytes(b"not gzip")
        with self.assertRaisesRegex(CoverageError, "corrupt_or_incomplete_gzip"):
            load_snapshot(p, historical=False)

    def test_reject_future_and_missing_live_snapshots(self):
        self.put("2026-11-10", history=True)
        with self.assertRaisesRegex(CoverageError, "required_production_snapshots_missing"):
            self.audit()
        self.put("2026-11-20")
        with self.assertRaisesRegex(CoverageError, "future_observation_date"):
            self.audit()


if __name__ == "__main__":
    unittest.main()
