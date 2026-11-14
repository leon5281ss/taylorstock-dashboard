"""Research OHLC and institutional date joins cannot turn into trading signals."""
import gzip
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from collect_market_history import compressed_snapshot
from audit_research_factor_dates import audit_joint_coverage, FactorAuditError


DAY = "2026-11-13"
MARKETS = {"TWSE": range(1000, 1700), "TPEX": range(6000, 6500)}


def price(day=DAY):
    rows = [
        {"market": m, "code": str(code), "open": 10.,
         "high": 12., "low": 9., "close": 11.,
         "volume": 1000, "turnover": 11000}
        for m, codes in MARKETS.items() for code in codes
    ]
    return {"schemaVersion": 1, "asOf": day,
            "priceAdjustment": "raw_unadjusted",
            "marketCounts": {m: len(c) for m, c in MARKETS.items()},
            "stocks": rows}


def institution(day=DAY):
    rows = [
        {"market": m, "code": str(code), "foreignNet": 100,
         "trustNet": 10, "dealerNet": 7, "totalNet": 117,
         "dealerSelfNet": 3, "dealerHedgeNet": 4}
        for m, codes in MARKETS.items() for code in codes
    ]
    return {"schemaVersion": 1, "status": "institutional_history_research_only",
            "asOf": day, "allNetUnits": "shares",
            "sourceDateEvidence": {"TWSE": "explicit_response_date",
                                   "TPEX": "explicit_response_date"},
            "marketCounts": {m: len(c) for m, c in MARKETS.items()},
            "historicalPointInTimeCompanyUniverse": False,
            "publishable": False, "rows": rows}


class JointFactorDateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for folder in ("daily", "research", "inst"):
            (self.root / folder).mkdir()
        self.saved_price = self.root / "daily" / (DAY + ".json.gz")
        self.saved_price.write_bytes(compressed_snapshot(price()))
        self.insti = self.root / "inst" / (DAY + ".json.gz")
        self.insti.write_bytes(compressed_snapshot(institution()))

    def tearDown(self):
        self.temp.cleanup()

    def audit(self):
        return audit_joint_coverage(self.root/"daily", self.root/"research",
                                    self.root/"inst")

    def test_good_joint_day_is_still_research_only(self):
        r = self.audit()
        self.assertEqual(r["jointDates"], 1)
        self.assertEqual(r["jointStocksAcrossDates"], {"TWSE": 700, "TPEX": 500})
        self.assertIsNone(r["top10"])
        self.assertFalse(r["rankingAllowed"])
        self.assertFalse(r["publishable"])
        self.assertFalse(r["dateWindows"]["121"]["tradableSignalReady"])

    def test_missing_company_ratio_denied(self):
        d = institution()
        d["rows"] = [row for row in d["rows"] if not (
            row["market"] == "TWSE" and int(row["code"]) >= 1400)]
        d["marketCounts"]["TWSE"] = 400
        self.insti.write_bytes(compressed_snapshot(d))
        with self.assertRaisesRegex(FactorAuditError, "coverage_or_counts"):
            self.audit()

    def test_wrong_accounting_rejected(self):
        d = institution()
        d["rows"][0]["totalNet"] = 118
        self.insti.write_bytes(compressed_snapshot(d))
        with self.assertRaisesRegex(FactorAuditError, "accounting_mismatch"):
            self.audit()

    def test_an_institutional_date_must_have_an_official_price_day(self):
        d = institution("2026-11-12")
        self.insti.unlink()
        (self.root/"inst"/"2026-11-12.json.gz").write_bytes(compressed_snapshot(d))
        with self.assertRaisesRegex(FactorAuditError, "orphan_institutional"):
            self.audit()

    def test_duplicate_symbol_rejected(self):
        d = institution()
        d["rows"].append(dict(d["rows"][0]))
        d["marketCounts"]["TWSE"] += 1
        self.insti.write_bytes(compressed_snapshot(d))
        with self.assertRaisesRegex(FactorAuditError, "duplicate_or_unknown"):
            self.audit()

    def test_gzip_invalid_does_not_report_success(self):
        self.insti.write_bytes(b"broken")
        with self.assertRaisesRegex(FactorAuditError, "archive_unreadable"):
            self.audit()

    def test_date_overlap_across_production_and_research_blocked(self):
        s = price()
        s.update({"status": "historical_pilot_research_only",
                  "pointInTimeUniverse": False,
                  "mixedVolumeWithDailyOpenAPI": False,
                  "volumeScopes": {"TWSE": "twse_all_trades_shares",
                                   "TPEX": "tpex_round_lot_shares"},
                  "sourceDateEvidence": {"TWSE": "explicit_response_date",
                                         "TPEX": "explicit_response_date"}})
        (self.root/"research"/(DAY+".json.gz")).write_bytes(compressed_snapshot(s))
        with self.assertRaisesRegex(FactorAuditError, "duplicate_price_source_day"):
            self.audit()


if __name__ == "__main__":
    unittest.main()
