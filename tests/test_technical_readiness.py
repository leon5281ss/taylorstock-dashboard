import gzip
import json
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from technical_readiness import TechnicalError, features, load_archives, readiness


def archive(day, close=100.0, extra=None):
    row = {"market": "TWSE", "code": "2330", "open": close-1, "high": close+1,
           "low": close-2, "close": close, "volume": 1000, "turnover": 1000000}
    if extra:
        row.update(extra)
    return {"schemaVersion": 1, "asOf": day, "priceAdjustment": "raw_unadjusted",
            "marketCounts": {"TWSE": 1, "TPEX": 0}, "stocks": [row]}


NOW = datetime(2026, 11, 12, 12, tzinfo=ZoneInfo("Asia/Taipei"))


class TechnicalReadinessTests(unittest.TestCase):
    def test_first_day_never_fakes_ranking(self):
        x = readiness([archive("2026-11-11")], NOW)
        self.assertEqual(x["status"], "history_building")
        self.assertEqual(x["archivedTradingDays"], 1)
        self.assertEqual(x["daysUntil121"], 120)
        self.assertEqual(x["latestQuotedStocks"], 1)
        self.assertEqual(x["technicalCompleteCount"], 0)
        self.assertIsNone(x["top10"])
        self.assertFalse(x["publishable"])

    def test_empty_archive_safe(self):
        x = readiness([], NOW)
        self.assertEqual(x["status"], "no_archive")
        self.assertIsNone(x["asOf"])

    def test_exact_121_days_research_only(self):
        day = date(2026, 6, 2)
        snaps = []
        for i in range(121):
            snaps.append(archive(day.isoformat(), 100 + i * 0.1))
            day += timedelta(days=1)
        x = readiness(snaps, NOW)
        self.assertEqual(x["status"], "research_only")
        self.assertEqual(x["technicalCompleteCount"], 1)
        self.assertAlmostEqual(x["rawTechnicalResearch"][0]["ma5"], 111.8)
        self.assertAlmostEqual(x["rawTechnicalResearch"][0]["ma120"], 106.05)
        self.assertFalse(x["publishable"])
        self.assertIsNone(x["top10"])

    def test_missing_latest_day_not_ready(self):
        snaps = []
        day = date(2026, 6, 2)
        for i in range(121):
            snapshot = archive(day.isoformat())
            if i == 100:
                snapshot["stocks"] = []
                snapshot["marketCounts"] = {"TWSE": 0, "TPEX": 0}
            snaps.append(snapshot)
            day += timedelta(days=1)
        x = readiness(snaps, NOW)
        self.assertEqual(x["technicalCompleteCount"], 0)

    def test_rsi_flat_is_fifty(self):
        f = features([{"close":100.0, "turnover":10.0}] * 121)
        self.assertEqual(f["rsi14"], 50.0)
        self.assertEqual(f["volatility20"], 0.0)
        self.assertEqual(f["macdHistogram"], 0.0)

    def test_insufficient_technical_history_rejected(self):
        with self.assertRaisesRegex(TechnicalError, "insufficient_technical_history"):
            features([{"close":100.0, "turnover":10.0}] * 120)

    def test_future_archive_blocked(self):
        with self.assertRaisesRegex(TechnicalError, "future_archive_date"):
            readiness([archive("2026-11-13")], NOW)

    def test_load_gzip_roundtrip_and_filename_check(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder/"2026-11-11.json.gz").write_bytes(gzip.compress(
                json.dumps(archive("2026-11-11")).encode()))
            s = load_archives(folder)
            self.assertEqual(s[0]["asOf"], "2026-11-11")
            (folder/"2026-11-10.json.gz").write_bytes(gzip.compress(
                json.dumps(archive("2026-11-11")).encode()))
            with self.assertRaisesRegex(TechnicalError, "archive_filename_date_mismatch"):
                load_archives(folder)

    def test_duplicate_code_and_market_count_guard(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            data = archive("2026-11-11")
            data["stocks"].append(data["stocks"][0].copy())
            (folder/"2026-11-11.json.gz").write_bytes(gzip.compress(json.dumps(data).encode()))
            with self.assertRaisesRegex(TechnicalError, "duplicate_market_code_in_archive"):
                load_archives(folder)

    def test_invalid_data_and_schema_guard(self):
        for extra, expected in [
            ({"close": float("nan")}, "nonfinite_market_price_or_volume"),
            ({"high": 95.0}, "invalid_ohlc_archive"),
            ({"volume": -1}, "invalid_market_price_or_volume")]:
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as temp:
                folder = Path(temp)
                (folder/"2026-11-11.json.gz").write_bytes(gzip.compress(json.dumps(
                    archive("2026-11-11", extra=extra)).encode()))
                with self.assertRaisesRegex(TechnicalError, expected):
                    load_archives(folder)

    def test_missing_or_invalid_gzip_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)
            (folder/"2026-11-11.json.gz").write_bytes(b"bad archive")
            with self.assertRaisesRegex(TechnicalError, "invalid_archived_snapshot"):
                load_archives(folder)


if __name__ == "__main__":
    unittest.main()
