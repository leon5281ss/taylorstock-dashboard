"""Coverage and alignment checks for volume reconciliation."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from reconcile_volume_categories import SOURCES, reconcile


class VolumeCategoryTests(unittest.TestCase):
    def test_complete_arithmetic_match_does_not_validate_scope(self):
        rows = {kind: dict(date="2026-11-13", code="6488", market="TPEX",
                           unit="shares", quantity=25, source=source)
                for kind, source in SOURCES.items()}
        result = reconcile("2026-11-13", "6488", 1000, 1100, rows)
        self.assertEqual(result["arithmeticResidualShares"], 0)
        self.assertFalse(result["scopeEquivalenceVerified"])
        self.assertIsNone(result["v5v60"])
        self.assertFalse(result["publishable"])

    def test_missing_and_misaligned_components_are_not_zero(self):
        rows = {"intradayOddLot": dict(date="2026-11-12", code="6488", market="TPEX",
                                      unit="lots", quantity=25,
                                      source=SOURCES["intradayOddLot"])}
        result = reconcile("2026-11-13", "6488", 1000, 1100, rows)
        self.assertEqual(result["rejectedComponents"], ["intradayOddLot"])
        self.assertEqual(len(result["missingComponents"]), 3)
        self.assertIsNone(result["arithmeticResidualShares"])
