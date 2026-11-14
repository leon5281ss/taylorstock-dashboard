"""Offline provenance and bounded external TDCC weekly research regression tests."""
import gzip
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import backfill_tdcc_external_history as external
from collect_market_history import compressed_snapshot


def official(day="2026-11-13"):
    return {
        "schemaVersion": 1, "asOf": day,
        "status": "tdcc_shareholder_research_only",
        "dataCadence": "weekly",
        "companies": [{"code": str(i), "market": "TWSE"} for i in range(1000, 2200)],
        "publishable": False,
    }


def manifest():
    from datetime import timedelta
    days = [date(2026, 11, 13)-timedelta(days=7*i) for i in range(16)]
    return [{"type": "file", "name": d.isoformat()+".csv"} for d in days]


def parsed(day):
    return {
        "schemaVersion": 1,
        "asOf": day,
        "dataCadence": "weekly",
        "status": "tdcc_shareholder_research_only",
        "companyCount": 1200,
        "companies": [{"code": str(i), "market": "TWSE"} for i in range(1000, 2200)],
        "quarantinedTotalMismatchCount": 0,
        "publishable": False,
    }


class ExternalTdccHistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.off = self.root/"official"
        self.ext = self.root/"external"
        self.off.mkdir()
        self.ext.mkdir()
        (self.off/"2026-11-13.json.gz").write_bytes(compressed_snapshot(official()))

    def tearDown(self):
        self.tmp.cleanup()

    def test_listing_only_earlier_valid_iso_dates(self):
        dates = external.listing(manifest(), "2026-11-13")
        self.assertEqual(dates[0], "2026-11-06")
        self.assertNotIn("2026-11-13", dates)
        self.assertEqual(len(dates), 15)

    def test_latest_week_missing_cannot_approve_history(self):
        source = manifest()[1:]
        with self.assertRaisesRegex(external.ExternalHistoryError,
                                    "mirror_latest_official_week_missing"):
            external.listing(source, "2026-11-13")

    def test_duplicate_week_not_silently_used(self):
        source = manifest()
        source.append(dict(source[0]))
        with self.assertRaisesRegex(external.ExternalHistoryError,
                                    "duplicate_mirror_week"):
            external.listing(source, "2026-11-13")

    def test_historical_artifacts_remain_nonofficial_and_nontrading(self):
        with (patch.object(external, "official_universe",
                           return_value={"errors": {}, "markets": {}}),
              patch.object(external, "parse_csv",
                           side_effect=lambda raw, roster, now: parsed(raw)),
              patch.object(external, "compare",
                           return_value={"sharedCompanies": 1199,
                                         "valueDifferenceCount": 0})):
            result = external.run(
                self.off, self.ext,
                manifest_fetch=manifest,
                mirror_fetch=lambda day: day,
                sleep=lambda _: None, max_successes=2, max_attempts=2)
        self.assertEqual(result["newCount"], 2)
        self.assertEqual(result["new"][0]["week"], "2026-11-06")
        self.assertFalse(result["publishable"])
        saved = json.loads(gzip.decompress(
            (self.ext/"2026-11-06.json.gz").read_bytes()))
        self.assertEqual(saved["status"], external.SOURCE)
        self.assertEqual(saved["sourceKind"], "independent_third_party_mirror")
        self.assertFalse(saved["historicalOfficialDirectAcquisition"])
        self.assertFalse(saved["historicalPublicationTimeVerified"])
        self.assertFalse(saved["pointInTimeCompanyUniverse"])
        self.assertIsNone(saved["top10"])
        self.assertEqual(saved["originUrl"], external.ARCHIVE_BASE+"2026-11-06.csv")
        self.assertEqual(len(saved["originSha256"]), 64)
        self.assertFalse(saved["historicalFactorReady"])
        self.assertFalse(saved["publishable"])
        self.assertEqual(len(list(self.off.glob("*.json.gz"))), 1)

    def test_rejected_external_old_week_is_not_persisted(self):
        def parse(raw, roster, now):
            if raw == "2026-11-06":
                raise ValueError("missing column")
            return parsed(raw)
        with (patch.object(external, "official_universe",
                           return_value={"errors": {}, "markets": {}}),
              patch.object(external, "parse_csv", side_effect=parse),
              patch.object(external, "compare",
                           return_value={"sharedCompanies": 1199,
                                         "valueDifferenceCount": 0})):
            result = external.run(
                self.off, self.ext, manifest_fetch=manifest,
                mirror_fetch=lambda day: day,
                sleep=lambda _: None,
                max_successes=1, max_attempts=2)
        self.assertEqual(result["newCount"], 1)
        self.assertEqual(result["errors"][0]["week"], "2026-11-06")
        self.assertFalse((self.ext/"2026-11-06.json.gz").exists())

    def test_latest_reference_mismatch_blocks_all_history(self):
        with (patch.object(external, "official_universe",
                           return_value={"errors": {}, "markets": {}}),
              patch.object(external, "parse_csv",
                           side_effect=lambda raw, roster, now: parsed(raw)),
              patch.object(external, "compare",
                           side_effect=external.MirrorError("latest_mismatch"))):
            with self.assertRaises(external.MirrorError):
                external.run(
                    self.off, self.ext, manifest_fetch=manifest,
                    mirror_fetch=lambda day: day,
                    sleep=lambda _: None)
        self.assertEqual(list(self.ext.iterdir()), [])

    def test_existing_external_history_requires_exact_provenance(self):
        d = parsed("2026-11-06")
        d.update({"status": external.SOURCE,
                  "historicalOfficialDirectAcquisition": True,
                  "archiveMirrorCurrentWeekValidatedOnly": True,
                  "historicalPublicationTimeVerified": False,
                  "pointInTimeCompanyUniverse": False,
                  "originUrl": external.ARCHIVE_BASE+"2026-11-06.csv",
                  "originSha256": "a"*64, "top10": None})
        (self.ext/"2026-11-06.json.gz").write_bytes(compressed_snapshot(d))
        with self.assertRaisesRegex(external.ExternalHistoryError, "provenance_invalid"):
            external.validate_previous(self.ext, set(external.listing(manifest(), "2026-11-13")))

    def test_limits_and_invalid_manifest(self):
        with self.assertRaisesRegex(external.ExternalHistoryError, "safety_limits_invalid"):
            external.run(self.off, self.ext, delay=0)
        with self.assertRaisesRegex(external.ExternalHistoryError, "manifest_incomplete"):
            external.listing([], "2026-11-13")


if __name__ == "__main__":
    unittest.main()
