"""Offline checks for non-tradable official valuation history source probes."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"scripts"))
import probe_valuation_history as p


def twse(tag="10"):
    fields = ["證券代號","證券名稱","收盤價","殖利率(%)","股利年度","本益比","股價淨值比","財報年/季"]
    return {"stat":"OK", "fields":fields,
            "data":[[str(i).zfill(4),"公司","50","3.4","114",tag,"1.5","115/3"]
                    for i in range(1000,1400)]}


def tpex(tag="10"):
    rows = [[str(i).zfill(4),"公司",tag,"1.0","114","3.5","1.3"] for i in range(2000,2400)]
    return {"iTotalRecords":len(rows), "aaData":rows}


class DatedValuationProbeTests(unittest.TestCase):
    def test_twse_and_tpex_endpoint_dates(self):
        self.assertIn("date=20261113", p.source_url("TWSE","2026-11-13"))
        self.assertIn("d=115%2F11%2F13", p.source_url("TPEX","2026-11-13"))
        with self.assertRaises(p.ValuationProbeError):
            p.source_url("NYSE","2026-11-13")

    def test_valuation_sources_valid_without_fundamental_disclosure_claim(self):
        a=p.inspect(twse(),"TWSE","2026-11-13")
        b=p.inspect(tpex(),"TPEX","2026-11-13")
        self.assertEqual(a["fourDigitSymbols"],400)
        self.assertEqual(b["fourDigitSymbols"],400)
        self.assertFalse(a["issuerStatementPublicReleaseDatesVerified"])
        self.assertFalse(b["dailyValuationReadyToRank"])

    def test_reject_tpex_truncation(self):
        data=tpex();data["iTotalRecords"]=999
        with self.assertRaisesRegex(p.ValuationProbeError,"schema_or_coverage"):
            p.inspect(data,"TPEX","2026-11-13")

    def test_reject_unknown_twse_columns(self):
        data=twse();data["fields"][5]="未知"
        with self.assertRaisesRegex(p.ValuationProbeError,"columns_changed"):
            p.inspect(data,"TWSE","2026-11-13")

    def test_reject_duplicate_trading_days(self):
        with self.assertRaisesRegex(p.ValuationProbeError,"requires_two_sorted_days"):
            p.run("2026-11-13","2026-11-13",sleep=lambda _:None)

    def test_offline_source_variation_required(self):
        def fetch(url):
            market="TPEX" if "tpex.org" in url else "TWSE"
            tag="15" if "20261113" in url or "11%2F13" in url else "12"
            return json.dumps(tpex(tag) if market=="TPEX" else twse(tag))
        result=p.run("2026-11-12","2026-11-13",fetch=fetch,sleep=lambda _:None)
        self.assertTrue(result["bothHistoricalDatesDiffer"])
        self.assertFalse(result["issuerFinancialDisclosureTimingVerified"])
        self.assertFalse(result["rankable"])
        self.assertIsNone(result["top10"])

    def test_if_two_dates_identical_report_not_valid(self):
        def fetch(url):
            return json.dumps(tpex() if "tpex.org" in url else twse())
        with self.assertRaisesRegex(p.ValuationProbeError,"indistinguishable"):
            p.run("2026-11-12","2026-11-13",fetch=fetch,sleep=lambda _:None)

    def test_no_unbounded_rate(self):
        with self.assertRaises(p.ValuationProbeError):
            p.run("2026-11-12","2026-11-13",delay=0.1)


if __name__=="__main__":
    unittest.main()
