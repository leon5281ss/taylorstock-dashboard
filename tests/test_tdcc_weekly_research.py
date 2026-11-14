"""Offline TDCC official weekly CSV cohort and accounting tests."""
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import collect_tdcc_weekly_research as tdcc


HEADER = "資料日期,證券代號,持股分級,人數,股數,占集保庫存數比例%"


def roster():
    return {"markets": {"TWSE": {"2330": {}},
                        "TPEX": {"6488": {}}}, "errors": {}}


def fixture(corruption=None):
    rows = [HEADER]
    for code in ("2330", "6488"):
        for tier in range(1, 18):
            shares = 100 if tier < 16 else (0 if tier == 16 else 1500)
            pct = "6.67" if tier <= 15 else ("0" if tier == 16 else "100")
            if corruption == "sum" and code == "2330" and tier == 15:
                shares = 101
            if corruption == "missing" and code == "6488" and tier == 14:
                continue
            dt = "20261113" if not (corruption == "mixed" and tier == 2 and code == "6488") else "20261106"
            rows.append(",".join(map(str, (dt, code, tier, 10, shares, pct))))
    # Official dataset covers many ETF and other issuers; only company stocks
    # are retained. Pad a test fixture to the real minimum raw-row threshold.
    rows.extend("20261113,0050,1,1,10,1" for _ in range(25000))
    return "\n".join(rows) + "\n"


class TdccWeeklyTests(unittest.TestCase):
    def parse(self, corruption=None):
        return tdcc.parse_csv(fixture(corruption), roster(),
                              now=date(2026, 11, 15), min_companies=1)

    def test_validate_weekly_cohorts_and_never_emit_daily_signals(self):
        result = self.parse()
        self.assertEqual(result["asOf"], "2026-11-13")
        self.assertEqual(result["dataCadence"], "weekly")
        self.assertEqual(result["companyCount"], 2)
        self.assertTrue(result["dailyValueImputationForbidden"])
        self.assertIsNone(result["top10"])
        self.assertFalse(result["publishable"])
        self.assertEqual(result["companies"][0]["depositoryShares"], 1500)

    def test_one_issuer_mismatch_is_quarantined_not_fabricated(self):
        result = self.parse("sum")
        self.assertEqual(result["companyCount"], 1)
        self.assertEqual(result["companies"][0]["code"], "6488")
        self.assertEqual(result["quarantinedTotalMismatchCount"], 1)
        self.assertEqual(result["quarantinedTotalMismatchExampleCodes"], ["2330"])
        self.assertFalse(result["publishable"])

    def test_widespread_mismatch_cannot_publish_snapshot(self):
        source = fixture().splitlines()
        base = ["20261113", "1111", "", "10", "", "6.67"]
        market = {str(x): {} for x in range(2000, 2030)}
        for code in market:
            for tier in range(1, 18):
                row = base[:]
                row[1] = code
                row[2] = str(tier)
                row[4] = str(101 if tier == 15 else
                             100 if tier <= 15 else 0 if tier == 16 else 1500)
                if tier == 17:
                    row[5] = "100"
                elif tier == 16:
                    row[5] = "0"
                source.append(",".join(row))
        groups = roster()
        groups["markets"]["TWSE"].update(market)
        with self.assertRaisesRegex(tdcc.TdccError, "widespread_share_total_mismatch"):
            tdcc.parse_csv("\n".join(source), groups,
                           now=date(2026, 11, 15), min_companies=1)

    def test_missing_holder_tier_is_not_forged(self):
        result = self.parse("missing")
        self.assertEqual(result["companyCount"], 1)
        self.assertEqual(result["companies"][0]["code"], "2330")

    def test_mixed_week_dates_fail_closed(self):
        with self.assertRaisesRegex(tdcc.TdccError, "mixed_week_dates"):
            self.parse("mixed")

    def test_unknown_header_rejected(self):
        s = fixture().replace("持股分級", "股權類型", 1)
        with self.assertRaisesRegex(tdcc.TdccError, "schema_changed"):
            tdcc.parse_csv(s, roster(), now=date(2026, 11, 15), min_companies=1)

    def test_stale_date_rejected(self):
        s = fixture().replace("20261113", "20261001")
        with self.assertRaisesRegex(tdcc.TdccError, "future_or_stale"):
            tdcc.parse_csv(s, roster(), now=date(2026, 11, 15), min_companies=1)

    def test_percent_and_nonfinite_rejected(self):
        s = fixture().replace("6.67", "nan", 1)
        with self.assertRaisesRegex(tdcc.TdccError, "percentage_out_of_range"):
            tdcc.parse_csv(s, roster(), now=date(2026, 11, 15), min_companies=1)

    def test_strict_integer_missing_and_negative(self):
        for v in ("--", "1.5", "", "nan"):
            with self.assertRaises(tdcc.TdccError):
                tdcc.integer(v)
        with self.assertRaises(tdcc.TdccError):
            tdcc.integer("-1")
        self.assertEqual(tdcc.integer("-1", allow_negative=True), -1)

    def test_footnote_percent_normalization(self):
        self.assertEqual(tdcc.header("佔集保庫存數比例％"),
                         "占集保庫存數比例%")
        self.assertEqual(tdcc.percentage("6.67"), 6.67)


if __name__ == "__main__":
    unittest.main()
