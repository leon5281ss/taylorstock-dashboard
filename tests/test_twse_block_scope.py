"""Single-security rows do not certify aggregate block coverage."""
import json
from pathlib import Path
import sys
import unittest
from hashlib import sha256
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from audit_twse_block_scope import FIELDS, inspect, replay, source_url


class TwseBlockScopeTests(unittest.TestCase):
    def test_multiple_rows_for_one_symbol_are_preserved_without_aggregation(self):
        data = {"stat":"OK", "date":"20261111", "title":"鉅額交易日成交資訊-單一證券",
                "fields":FIELDS, "data":[["2317","name","配對交易","242","167,000","40,414,000"],
                                        ["2317","name","配對交易","242","2,000","484,000"]]}
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

    def test_abnormal_fields_and_indistinguishable_duplicate(self):
        row = ["2317","name","配對交易","242.00","1000","242000"]
        data = {"stat":"OK","date":"20261111","title":"鉅額交易日成交資訊-單一證券",
                "fields":FIELDS,"data":[row]}
        for index, value in ((0,"23X7"), (2,"unknown"), (3,"NaN"), (4,"1.5"),
                             (4,True), (5,"-1"), (5,"12,34")):
            with self.subTest(index=index,value=value), self.assertRaises(ValueError):
                changed = row.copy()
                changed[index] = value
                inspect(json.dumps(dict(data,data=[changed])).encode(), "2026-11-11")
        with self.assertRaisesRegex(ValueError, "duplicate_block_trade"):
            inspect(json.dumps(dict(data,data=[row,row])).encode(), "2026-11-11")

    def test_replay_rejects_modified_or_corrupt_raw(self):
        day = "2026-11-11"
        with TemporaryDirectory() as folder:
            path = Path(folder)/"raw.json"
            raw = b"broken"
            manifest = {day: {"requestedDate":day,"responseDate":day,"source":source_url(day),
                              "rawFile":path.name,"sha256":sha256(raw).hexdigest()}}
            path.write_bytes(raw+b" ")
            with self.assertRaisesRegex(ValueError, "sha256_mismatch"):
                replay(path,day,manifest)
            path.write_bytes(raw)
            with self.assertRaises(json.JSONDecodeError):
                replay(path,day,manifest)

    def test_official_summary_is_separate_and_must_match_trade_rows(self):
        data = {"stat":"OK", "date":"20261111", "title":"鉅額交易日成交資訊-單一證券",
                "fields":FIELDS, "data":[["2317","name","配對交易","242","1000","242000"],
                                       ["總計","","","","1000","242000"]]}
        result = inspect(json.dumps(data).encode(), "2026-11-11")
        self.assertEqual(len(result["transactions"]), 1)
        self.assertEqual(result["summaryRows"], 1)
        data["data"][-1][-1] = "242001"
        with self.assertRaisesRegex(ValueError, "totals_mismatch"):
            inspect(json.dumps(data).encode(), "2026-11-11")
