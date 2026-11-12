import copy
import sys
import unittest
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from market_pipeline.clock import TAIPEI
from market_pipeline.telegram_delivery import DeliveryError, candidates, deliver, validate


def report():
    stocks = [{"code": str(x), "alerts": []} for x in range(22)]
    stocks[0]["code"] = "2303"
    stocks[0]["alerts"] = [{"date": "2026-11-11", "rule": "cross_below_ma20", "riskLevel": "中"}]
    return {"riskModelVersion": 1, "reportStatus": "partial",
            "summary": {"stockCount": 22, "completeCount": 20, "asOf": "2026-11-11",
                        "manualCheckCount": 1, "riskCounts": {"高": 0, "中": 1}},
            "stocks": stocks, "marketMonitor": {"items": []}}


NOW = datetime(2026, 11, 12, 8, tzinfo=TAIPEI)


class Store:
    def __init__(self):
        self.state = {"version": 1, "events": {}}
        self.version = 0
        self.history = []
    def load(self):
        return copy.deepcopy(self.state), self.version
    def save(self, state, sha):
        assert sha == self.version
        self.version += 1
        self.state = copy.deepcopy(state)
        self.history.append(copy.deepcopy(state))
        return self.version


class DeliveryTests(unittest.TestCase):
    def test_preview_does_not_need_credentials(self):
        self.assertEqual(deliver(report(), dry_run=True, now=NOW)["events"], 2)

    def test_private_pending_then_sent_and_deduped(self):
        store = Store()
        out = []
        def send(message):
            out.append(message)
            return 123
        self.assertEqual(deliver(report(), store, send, False, NOW)["messages"], 1)
        self.assertTrue(all(v["status"] == "pending" for v in store.history[0]["events"].values()))
        self.assertEqual(deliver(report(), store, send, False, NOW)["messages"], 0)
        p = report()
        p["stocks"][0]["alerts"][0]["riskLevel"] = "高"
        self.assertEqual(deliver(p, store, send, False, NOW)["messages"], 1)
        self.assertEqual(len(out), 2)

    def test_network_unknown_prevents_blind_resend(self):
        store = Store()
        def fail(_):
            raise DeliveryError("telegram_delivery_unknown")
        with self.assertRaisesRegex(DeliveryError, "telegram_delivery_unknown"):
            deliver(report(), store, fail, False, NOW)
        self.assertTrue(all(v["status"] == "unknown" for v in store.state["events"].values()))
        self.assertEqual(deliver(report(), store, lambda _: 7, False, NOW)["messages"], 0)

    def test_rejected_request_is_retryable(self):
        store = Store()
        with self.assertRaisesRegex(DeliveryError, "telegram_rejected"):
            deliver(report(), store, lambda _: (_ for _ in ()).throw(DeliveryError("telegram_rejected_429")), False, NOW)
        self.assertTrue(all(v["status"] == "failed" for v in store.state["events"].values()))
        self.assertEqual(deliver(report(), store, lambda _: 1, False, NOW)["messages"], 1)

    def test_quality_and_privacy(self):
        p = report()
        p["summary"]["completeCount"] = 0
        with self.assertRaisesRegex(DeliveryError, "insufficient_market_data"):
            validate(p, NOW)
        p = report()
        p["stocks"][0]["shares"] = 3
        with self.assertRaises(ValueError):
            validate(p, NOW)
        p = report()
        p["summary"]["asOf"] = "2026-10-01"
        with self.assertRaisesRegex(DeliveryError, "stale_or_future_report"):
            validate(p, NOW)


if __name__ == "__main__":
    unittest.main()
