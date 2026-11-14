"""Margin batch only accepts verifiable dated public research data."""
import gzip
import json
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import backfill_margin_research as batch


def good_margin(day):
    rows = []
    for market, count in (("TWSE", 700), ("TPEX", 550)):
        for i in range(count):
            rows.append({
                "market": market, "code": str(1000 + i),
                "marginPrevious": 10, "marginCurrent": 12,
                "shortPrevious": 5, "shortCurrent": 4,
                "sourceBalanceUnit": ("twse_trading_unit_not_proven_shares"
                                      if market == "TWSE" else "tpex_explicit_lots"),
                "currentBalancePublicationTimingVerified": False,
            })
    return {"schemaVersion": 1, "status": "margin_balance_history_research_only",
            "asOf": day, "officialSourceDateExplicit": True,
            "unitsNotCrossMarketNormalized": True,
            "marginFactorReady": False, "publishable": False, "top10": None,
            "pointInTimeCompanyUniverseVerified": False,
            "currentBalanceAvailableDuringTradingSession": False,
            "marketCounts": {"TWSE": 700, "TPEX": 550}, "rows": rows}


class MarginBackfillTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.daily, self.price, self.margin = (
            self.root / "daily", self.root / "price", self.root / "margin")
        for directory in (self.daily, self.price, self.margin):
            directory.mkdir()
        for day, root in (("2026-11-11", self.daily),
                          ("2026-11-12", self.daily),
                          ("2026-11-10", self.price)):
            (root / (day + ".json.gz")).write_bytes(b"verified-price-name")

    def tearDown(self):
        self.tmp.cleanup()

    def test_uses_verified_price_archive_dates_newest_first(self):
        plan = batch.candidate_dates(self.daily, self.price, self.margin)
        self.assertEqual(plan["dates"], ["2026-11-12", "2026-11-11", "2026-11-10"])
        self.assertEqual(plan["priceDays"], 3)

    def test_rerun_skips_existing_margin(self):
        (self.margin / "2026-11-12.json.gz").write_bytes(b"original")
        plan = batch.candidate_dates(self.daily, self.price, self.margin)
        self.assertEqual(plan["dates"][0], "2026-11-11")
        self.assertEqual((self.margin / "2026-11-12.json.gz").read_bytes(), b"original")

    def test_limited_batch_and_safe_status(self):
        requests = []
        report = batch.archive_margin_batch(
            self.daily, self.price, self.margin,
            fetch_day=lambda day: requests.append(day) or good_margin(day),
            sleep=lambda sec: None, max_successes=2, max_attempts=2)
        self.assertEqual(report["newCount"], 2)
        self.assertEqual(requests, ["2026-11-12", "2026-11-11"])
        self.assertFalse(report["marginFactorReady"])
        self.assertFalse(report["publishable"])
        self.assertIsNone(report["top10"])
        saved = json.loads(gzip.decompress(
            (self.margin/"2026-11-11.json.gz").read_bytes()))
        self.assertTrue(saved["officialSourceDateExplicit"])

    def test_bad_margin_date_rejected_not_saved(self):
        report = batch.archive_margin_batch(
            self.daily, self.price, self.margin,
            fetch_day=lambda day: good_margin("2026-11-01"),
            sleep=lambda sec: None, max_successes=1, max_attempts=1)
        self.assertEqual(report["newCount"], 0)
        self.assertEqual(len(report["errors"]), 1)
        self.assertEqual(list(self.margin.iterdir()), [])

    def test_unverified_balance_units_rejected(self):
        def bad(day):
            payload = good_margin(day)
            payload["unitsNotCrossMarketNormalized"] = False
            return payload
        result = batch.archive_margin_batch(
            self.daily, self.price, self.margin,
            fetch_day=bad, sleep=lambda sec: None,
            max_successes=1, max_attempts=1)
        self.assertEqual(result["newCount"], 0)
        self.assertFalse(result["publishable"])

    def test_bad_market_counts_not_archived(self):
        def bad(day):
            payload = good_margin(day)
            payload["marketCounts"]["TPEX"] = 15
            return payload
        result = batch.archive_margin_batch(
            self.daily, self.price, self.margin, fetch_day=bad,
            sleep=lambda sec: None, max_successes=1, max_attempts=1)
        self.assertEqual(result["newCount"], 0)

    def test_wrong_delay_and_budget_refused(self):
        with self.assertRaises(batch.MarginBackfillError):
            batch.archive_margin_batch(
                self.daily, self.price, self.margin, delay=1)
        for a, b in ((13, 20), (2, 1), (1, 25)):
            with self.subTest(a=a, b=b), self.assertRaises(batch.MarginBackfillError):
                batch.candidate_dates(self.daily, self.price, self.margin,
                                      max_successes=a, max_attempts=b)

    def test_archive_day_invalid_refused(self):
        (self.price/"2026-55-01.json.gz").write_bytes(b"untrusted")
        with self.assertRaisesRegex(batch.MarginBackfillError, "price_archive_date_invalid"):
            batch.candidate_dates(self.daily, self.price, self.margin)

    def test_no_verified_dates_is_fatal(self):
        for folder in (self.daily, self.price):
            for file in folder.iterdir():
                file.unlink()
        with self.assertRaisesRegex(batch.MarginBackfillError, "verified_price_archives_missing"):
            batch.candidate_dates(self.daily, self.price, self.margin)


if __name__ == "__main__":
    unittest.main()
