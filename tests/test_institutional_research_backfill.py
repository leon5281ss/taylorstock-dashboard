"""Offline tests for bounded institutional history accumulation and provenance."""
import gzip
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import backfill_institutional_research as backfill
from collect_market_history import compressed_snapshot
from collect_institutional_history import InstitutionalError


def price_archive(day, historical=False):
    rows = []
    for market, lo, hi in (("TWSE", 1000, 1700), ("TPEX", 6000, 6500)):
        rows.extend({"market": market, "code": str(n),
                     "open": 10., "high": 12., "low": 9., "close": 11.,
                     "volume": 1000, "turnover": 11000}
                    for n in range(lo, hi))
    d = {"schemaVersion": 1, "asOf": day, "priceAdjustment": "raw_unadjusted",
         "marketCounts": {"TWSE": 700, "TPEX": 500}, "stocks": rows}
    if historical:
        d.update({"status": "historical_pilot_research_only",
                  "pointInTimeUniverse": False,
                  "mixedVolumeWithDailyOpenAPI": False,
                  "volumeScopes": {"TWSE": "twse_all_trades_shares",
                                   "TPEX": "tpex_round_lot_shares"},
                  "sourceDateEvidence": {"TWSE": "explicit_response_date",
                                         "TPEX": "explicit_response_date"}})
    return compressed_snapshot(d)


def institutional_archive(day):
    return compressed_snapshot({
        "schemaVersion": 1, "asOf": day,
        "status": "institutional_history_research_only",
        "sourceDateEvidence": {"TWSE": "explicit_response_date",
                               "TPEX": "explicit_response_date"},
        "marketCounts": {"TWSE": 700, "TPEX": 500},
        "publishable": False,
    })


class InstitutionalBackfillTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.daily = self.root/"daily"
        self.price = self.root/"price"
        self.insti = self.root/"insti"
        for folder in (self.daily, self.price, self.insti):
            folder.mkdir()
        (self.daily/"2026-11-11.json.gz").write_bytes(price_archive("2026-11-11"))
        (self.daily/"2026-11-12.json.gz").write_bytes(price_archive("2026-11-12"))
        (self.price/"2026-11-10.json.gz").write_bytes(price_archive("2026-11-10", True))

    def tearDown(self):
        self.tmp.cleanup()

    def plan(self):
        return backfill.plan_dates(self.daily, self.price, self.insti)

    def test_only_official_price_dates_and_recent_first(self):
        plan = self.plan()
        self.assertEqual(plan["priceCalendarDates"], 3)
        self.assertEqual(plan["pending"],
                         ["2026-11-12", "2026-11-11", "2026-11-10"])
        self.assertNotIn("2026-11-09", plan["pending"])

    def test_idempotent_existing_institutional_day_skipped(self):
        (self.insti/"2026-11-12.json.gz").write_bytes(
            institutional_archive("2026-11-12"))
        self.assertEqual(self.plan()["pending"], ["2026-11-11", "2026-11-10"])

    def test_corrupt_existing_institutional_archive_rejected(self):
        (self.insti/"2026-11-12.json.gz").write_bytes(b"not gzip")
        with self.assertRaisesRegex(backfill.InstitutionalBackfillError,
                                    "existing_institutional_archive_corrupt"):
            self.plan()

    def test_duplicate_price_source_day_rejected(self):
        (self.price/"2026-11-11.json.gz").write_bytes(
            price_archive("2026-11-11", True))
        with self.assertRaisesRegex(backfill.InstitutionalBackfillError,
                                    "overlapping_price_calendar_date"):
            self.plan()

    def test_price_schema_failure_fails_closed(self):
        (self.price/"2026-11-10.json.gz").write_bytes(b"broken")
        with self.assertRaisesRegex(backfill.InstitutionalBackfillError,
                                    "price_calendar_source_invalid"):
            self.plan()

    def test_mismatched_saved_institutional_date_rejected(self):
        (self.insti/"2026-11-11.json.gz").write_bytes(
            institutional_archive("2026-11-12"))
        with self.assertRaisesRegex(backfill.InstitutionalBackfillError,
                                    "existing_institutional_archive_not_verified"):
            self.plan()

    def test_offline_batch_once_does_not_modify_price_data(self):
        saved = (self.daily/"2026-11-11.json.gz").read_bytes()
        calls = []
        def collect(day, **kwargs):
            calls.append((day, kwargs["company_universe"]))
            return {"asOf": day, "publishable": False,
                    "marketCounts": {"TWSE": 700, "TPEX": 500},
                    "status": "institutional_history_research_only"}
        with (patch.object(backfill, "official_universe",
                           return_value={"errors": {}, "markets": {}}),
              patch.object(backfill, "official_institutional_day", side_effect=collect)):
            result = backfill.run(self.daily, self.price, self.insti,
                                  sleep=lambda _: None, max_successes=1,
                                  max_attempts=1)
        self.assertEqual(result["newCount"], 1)
        self.assertEqual(result["new"][0]["date"], "2026-11-12")
        self.assertEqual(len(calls), 1)
        self.assertEqual((self.daily/"2026-11-11.json.gz").read_bytes(), saved)
        self.assertFalse(result["publishable"])
        self.assertIsNone(result["top10"])

    def test_bad_source_does_not_forge_empty_or_zero_flow(self):
        with (patch.object(backfill, "official_universe",
                           return_value={"errors": {}, "markets": {}}),
              patch.object(backfill, "official_institutional_day",
                           side_effect=InstitutionalError("bad_formula"))):
            result = backfill.run(self.daily, self.price, self.insti,
                                  sleep=lambda _: None,
                                  max_successes=1, max_attempts=1)
        self.assertEqual(result["newCount"], 0)
        self.assertEqual(result["errors"][0]["reason"], "bad_formula")
        self.assertEqual(list(self.insti.glob("*.json.gz")), [])

    def test_batch_caps_and_rate_limit(self):
        with self.assertRaisesRegex(backfill.InstitutionalBackfillError,
                                    "batch_limits_invalid"):
            backfill.plan_dates(self.daily, self.price, self.insti,
                                max_successes=20)
        with self.assertRaisesRegex(backfill.InstitutionalBackfillError,
                                    "minimum_delay_required"):
            backfill.run(self.daily, self.price, self.insti, delay=0.1)


if __name__ == "__main__":
    unittest.main()
