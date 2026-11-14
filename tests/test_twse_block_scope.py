"""Single-security rows do not certify aggregate block coverage."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from audit_twse_block_scope import FIELDS, inspect


class TwseBlockScopeTests(unittest.TestCase):
    def test_multiple_rows_for_one_symbol_are_preserved_without_aggregation(self):
        data = {"stat":"OK", "date":"20261111", "title":"鉅額交易日成交資訊-單一證券",
                "fields":FIELDS, "data":[["2317","name","pair","242","167,000","0"],
                                        ["2317","name","pair","242","2,000","0"]]}
        result = inspect(json.dumps(data).encode(), "2026-11-11")
        self.assertEqual([r["shares"] for r in result["transactions"]], [167000,2000])
        self.assertFalse(result["allBlockCoverageVerified"])
        self.assertFalse(result["publicAggregateInclusionVerified"])
        self.assertIsNone(result["v5v60"])
        with self.assertRaisesRegex(ValueError, "identity_mismatch"):
            inspect(json.dumps(data).encode(), "2026-11-12")

    def test_lots_cannot_pass_share_schema(self):
        data = {"stat":"OK", "date":"20261111", "title":"鉅額交易日成交資訊-單一證券",
                "fields":[*FIELDS[:4],"成交張數",FIELDS[-1]], "data":[]}
        with self.assertRaisesRegex(ValueError, "schema_mismatch"):
            inspect(json.dumps(data).encode(), "2026-11-11")
