"""Historical margin source probe must not invent lots-to-shares conversions."""
import json
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"scripts"))
from probe_margin_history import MarginProbeError, dated_url, inspect_response, probe


def example(diff=100):
    fields = ["股票代號", "股票名稱", "融資買進", "融資賣出",
              "融資前日餘額", "融資今日餘額",
              "融券買進", "融券今日餘額"]
    return {"stat": "OK", "date": "20261113",
            "tables": [{"fields": fields,
                        "data": [[str(2000+i), "公司", "10", "5", "100",
                                  str(diff+i), "3", "20"] for i in range(4)]}]}


class MarginSourceProbeTests(unittest.TestCase):
    def test_date_urls_not_latest_openapi(self):
        self.assertIn("date=20261113", dated_url("TWSE", "2026-11-13"))
        self.assertIn("selectType=ALL", dated_url("TWSE", "2026-11-13"))
        self.assertIn("date=115%2F11%2F13", dated_url("TPEX", "2026-11-13"))
        with self.assertRaises(MarginProbeError):
            dated_url("OTHER", "2026-11-13")

    def test_response_fields_and_unverified_unit(self):
        x = inspect_response(example(), "TWSE", "2026-11-13", minimum=3)
        self.assertEqual(x["rows"], 4)
        self.assertEqual(x["sourceDateEvidence"], "explicit_response_date")
        self.assertFalse(x["unitIdentityVerified"])

    def test_date_mismatch_rejected(self):
        with self.assertRaisesRegex(MarginProbeError, "date_mismatch"):
            inspect_response(example(), "TWSE", "2026-11-12", minimum=3)

    def test_identical_day_payload_rejected_as_history(self):
        def fetch(url):
            x = example()
            x.pop("date")
            return json.dumps(x)
        with self.assertRaisesRegex(MarginProbeError, "historical_dates_not_proven"):
            probe(["2026-11-12", "2026-11-13"],
                  fetch=fetch, sleep=lambda _: None, minimum=3)

    def test_bad_table_row_length_rejected(self):
        x = example()
        x["tables"][0]["data"][0].append("unexpected")
        with self.assertRaisesRegex(MarginProbeError, "row_schema_invalid"):
            inspect_response(x, "TWSE", "2026-11-13", minimum=3)

    def test_rate_limit_and_order_enforced(self):
        with self.assertRaises(MarginProbeError):
            probe(["2026-11-13", "2026-11-12"], delay=2.5)
        with self.assertRaises(MarginProbeError):
            probe(["2026-11-12", "2026-11-13"], delay=1)
        with self.assertRaises(MarginProbeError):
            probe(["2026-11-13", "2026-11-13"], delay=2.5)


if __name__ == "__main__":
    unittest.main()
