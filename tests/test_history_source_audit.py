"""Offline cross-source safety tests; no access to external APIs required."""
import gzip
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import audit_history_sources
from audit_history_sources import AuditError, audit_day, compare_market, run
from backfill_market_pilot import MINIMUM_ROSTER


DAY = "2026-11-11"


def twse(close="101", volume="1,234", day="20261111"):
    return {"stat": "OK", "date": day, "tables": [{
        "fields": ["證券代號", "成交股數", "成交金額", "開盤價", "最高價", "最低價", "收盤價"],
        "data": [["2330", volume, "123,400", "100", "102", "99", close]]
    }]}


def tpex(close="505", volume="29,000", day="1151111"):
    return {"stat": "ok", "date": day, "tables": [{
        "fields": ["代號", "成交股數", "成交金額(元)", "開盤", "最高", "最低", "收盤"],
        "data": [["6488", volume, "14,800,000", "500", "510", "495", close]]
    }]}


def archive(day=DAY):
    return {"schemaVersion": 1, "asOf": day, "priceAdjustment": "raw_unadjusted",
            "marketCounts": {"TWSE": 1, "TPEX": 1},
            "stocks": [
                {"code": "2330", "market": "TWSE", "open": 100., "high": 102.,
                 "low": 99., "close": 101., "volume": 1234, "turnover": 123400},
                {"code": "6488", "market": "TPEX", "open": 500., "high": 510.,
                 "low": 495., "close": 505., "volume": 30000, "turnover": 15000000},
            ]}


class CrossSourceAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.patch_min = patch.dict(MINIMUM_ROSTER, {"TWSE": 1, "TPEX": 1})
        cls.patch_min.start()
        cls.patch_overlap = patch.dict(audit_history_sources.MIN_SHARED, {"TWSE": 1, "TPEX": 1})
        cls.patch_overlap.start()

    @classmethod
    def tearDownClass(cls):
        cls.patch_overlap.stop()
        cls.patch_min.stop()

    def get_day(self, t=None, p=None):
        return audit_day(archive(), {"TWSE": t or twse(), "TPEX": p or tpex()},
                         min_shared={"TWSE": 1, "TPEX": 1})

    def test_both_sources_prices_match_no_integration(self):
        result = self.get_day()
        self.assertEqual(result["markets"]["TWSE"]["ohlcMatchRate"], 1)
        self.assertEqual(result["markets"]["TPEX"]["ohlcMatchRate"], 1)
        self.assertTrue(result["bothMarketsOhlcAtLeast99Percent"])
        self.assertFalse(result["integrationAllowed"])
        self.assertEqual(result["markets"]["TPEX"]["datedToLiveMedianVolumeRatio"], round(29000/30000, 6))
        self.assertFalse(result["markets"]["TPEX"]["historicalVolumeCompatible"])

    def test_twse_same_volume_compatible(self):
        self.assertTrue(self.get_day()["markets"]["TWSE"]["historicalVolumeCompatible"])

    def test_ohlc_difference_detected_not_papered_over(self):
        result = self.get_day(t=twse(close="100"))
        self.assertFalse(result["bothMarketsOhlcAtLeast99Percent"])
        self.assertEqual(result["markets"]["TWSE"]["sampleOhlcDifferences"][0]["code"], "2330")
        self.assertFalse(result["integrationAllowed"])

    def test_tpex_query_only_date_never_verified(self):
        q = tpex()
        del q["date"]
        r = self.get_day(p=q)
        self.assertEqual(r["markets"]["TPEX"]["sourceDateEvidence"], "query_only_unverified")
        self.assertFalse(r["bothResponseDatesExplicit"])

    def test_mismatched_tpex_date_blocked(self):
        with self.assertRaisesRegex(AuditError, "dated_source_invalid_TPEX"):
            self.get_day(p=tpex(day="1151112"))

    def test_unknown_schema_blocked(self):
        t = twse()
        t["tables"][0]["fields"][6] = "假收盤"
        with self.assertRaisesRegex(AuditError, "unknown_or_ambiguous"):
            self.get_day(t=t)

    def test_overlap_guard(self):
        s = archive()
        with self.assertRaisesRegex(AuditError, "insufficient_cross_source_overlap"):
            compare_market(s["stocks"], s["stocks"], "TWSE", min_shared=2)

    def test_compare_by_code_not_array_position(self):
        s = archive()
        dated = list(reversed(s["stocks"]))
        result = compare_market(s["stocks"], dated, "TWSE", min_shared=1)
        self.assertEqual(result["ohlcMatchRate"], 1)

    def test_volume_zero_does_not_divide_by_zero(self):
        a = archive()["stocks"]
        a[0]["volume"] = 0
        b = [x.copy() for x in a]
        self.assertIsNone(compare_market(a, b, "TWSE", min_shared=1)["datedToLiveMedianVolumeRatio"])

    def test_bounded_network_reconciliation(self):
        s = archive()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/(DAY+".json.gz")).write_bytes(gzip.compress(json.dumps(s).encode("utf-8")))
            seen = []
            def fetch(url):
                seen.append(url)
                return json.dumps(tpex() if "tpex.org.tw" in url else twse())
            report = run(root, fetch, lambda seconds: None, days=1)
            self.assertEqual(report["daysAudited"], 1)
            self.assertEqual(len(seen), 2)
            self.assertFalse(report["publishable"])
            self.assertIsNone(report["top10"])

    def test_over_three_days_refused(self):
        with self.assertRaisesRegex(AuditError, "audit_limited_to_three_dates"):
            run(Path("/tmp/no-archives"), lambda url: "", lambda x: None, days=4)


if __name__ == "__main__":
    unittest.main()
