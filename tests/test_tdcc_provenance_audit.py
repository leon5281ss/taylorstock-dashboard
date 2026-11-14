"""TDCC historical mirror cannot become an official snapshot silently."""
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"scripts"))
from collect_market_history import compressed_snapshot
from audit_tdcc_provenance import TdccProvenanceError, audit, MIRROR_BASE


def one(day, official=False):
    common = {"schemaVersion": 1, "asOf": day, "dataCadence": "weekly",
              "companyCount": 1000,
              "companies": [{"code": str(x)} for x in range(1000, 2000)],
              "top10": None, "publishable": False}
    if official:
        common.update({"status": "tdcc_shareholder_research_only",
                       "source": "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5"})
    else:
        common.update({
            "status": "external_third_party_mirror_unverified_historical",
            "sourceKind": "independent_third_party_mirror",
            "originUrl": MIRROR_BASE+day+".csv",
            "originSha256": "a"*64,
            "historicalOfficialDirectAcquisition": False,
            "historicalPublicationTimeVerified": False,
            "pointInTimeCompanyUniverse": False,
            "historicalFactorReady": False,
            "archiveMirrorCurrentWeekValidatedOnly": True,
        })
    return common


class TdccProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.official = self.root/"official"
        self.external = self.root/"mirror"
        self.official.mkdir(); self.external.mkdir()
        self.store("2026-11-13", official=True)
        self.store("2026-11-06")

    def tearDown(self):
        self.tmp.cleanup()

    def store(self, day, official=False, payload=None):
        folder = self.official if official else self.external
        target = folder/(day+".json.gz")
        target.write_bytes(compressed_snapshot(payload or one(day, official)))
        return target

    def check(self):
        return audit(self.official, self.external)

    def test_separate_official_and_external_counts_never_publish(self):
        r = self.check()
        self.assertEqual(r["officialWeeks"], 1)
        self.assertEqual(r["externalUnverifiedHistoricalWeeks"], 1)
        self.assertFalse(r["externalResearchEligibleForQuantFactors"])
        self.assertFalse(r["externalHistoricalWeeksDirectlyOfficialSourced"])
        self.assertFalse(r["publishable"])
        self.assertIsNone(r["top10"])

    def test_external_claiming_official_provenance_is_refused(self):
        data = one("2026-11-06")
        data["historicalOfficialDirectAcquisition"] = True
        self.store("2026-11-06", payload=data)
        with self.assertRaisesRegex(TdccProvenanceError, "external_tdcc_provenance_invalid"):
            self.check()

    def test_unverified_historical_publication_flag_cannot_be_true(self):
        data = one("2026-11-06")
        data["historicalPublicationTimeVerified"] = True
        self.store("2026-11-06", payload=data)
        with self.assertRaisesRegex(TdccProvenanceError, "external_tdcc_provenance_invalid"):
            self.check()

    def test_mirror_cannot_overlap_official_week(self):
        self.store("2026-11-13")
        with self.assertRaisesRegex(TdccProvenanceError, "external_tdcc_provenance_invalid"):
            self.check()

    def test_unauthorized_top10_rejected(self):
        data = one("2026-11-06")
        data["top10"] = [{"code": "2330"}]
        self.store("2026-11-06", payload=data)
        with self.assertRaisesRegex(TdccProvenanceError, "tdcc_provenance_trading_guard_invalid"):
            self.check()


if __name__ == "__main__":
    unittest.main()
