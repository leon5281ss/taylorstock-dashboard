import copy
import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from market_pipeline.monitor import market_monitor, related_industry_news
from market_pipeline.notifications import notification_plan
from market_pipeline.pipeline import ROOT, TAIPEI, collect, load_watchlist
from market_pipeline.risk import classify_stock
from test_pipeline import FixtureClient


def stock(alerts=()):
    return {"code": "2303", "alerts": list(alerts), "quality": {"price": {"status": "ok", "officialCheck": {"status": "verified"}}}, "unavailableRules": []}


def event(rule="cross_below_ma20", **kwargs):
    return {"rule": rule, "date": "2026-11-11", "message": rule, "source": "fixture", **kwargs}


def feeds():
    item = {"title": "國安基金穩定市場公告", "url": "https://www.mof.gov.tw/singlehtml/test", "publishedDate": "2026-11-11", "isRecent": True}
    return [{"source": name, "url": "https://www.mof.gov.tw/", "status": "ok", "checkedAt": "2026-11-11", "items": [copy.deepcopy(item)]} for name in ("財政部", "國安基金官方公告")]


class PolicyRiskTests(unittest.TestCase):
    def test_policy_not_multiplied_by_22(self):
        with patch("market_pipeline.pipeline.collect_news", return_value=feeds()):
            payload = collect(FixtureClient(), load_watchlist(ROOT / "config/watchlist_public.json"), datetime(2026, 11, 11, tzinfo=TAIPEI))
        self.assertEqual(len(payload["stocks"]), 22)
        self.assertEqual(len(payload["marketMonitor"]["items"]), 1)
        self.assertTrue(all(not any(alert["rule"] == "policy_news" for alert in item["alerts"]) for item in payload["stocks"]))
        self.assertEqual(payload["summary"]["manualCheckCount"], sum(item["manualCheck"] == "是" for item in payload["stocks"]))

    def test_duplicate_cross_feed_and_tracking_url(self):
        reports = feeds()
        reports[1]["items"][0]["url"] += "?utm_source=test#top"
        monitor = market_monitor(reports)
        self.assertEqual(len(monitor["items"]), 1)
        self.assertEqual(len(monitor["items"][0]["sources"]), 2)
        self.assertEqual(monitor["governmentBank"]["label"], "無權限")

    def test_manual_and_levels(self):
        general = classify_stock(stock([event("foreign_streak", direction="buy"), event("policy_news")]))
        self.assertEqual((general["riskLevel"], general["manualCheck"]), ("一般觀察", "否"))
        medium = classify_stock(stock([event("trust_streak", direction="sell")]))
        self.assertEqual((medium["riskLevel"], medium["manualCheck"]), ("中", "是"))
        high = classify_stock(stock([event("deleveraging_drop"), event("deleveraging_drop")]))
        self.assertEqual(high["riskLevel"], "高")
        self.assertEqual(len(high["alerts"]), 1)

    def test_quality_is_separate_not_fake_high_risk(self):
        item = stock()
        item["quality"]["price"]["status"] = "missing"
        classify_stock(item)
        self.assertEqual(item["manualCheck"], "是")
        self.assertEqual(item["riskLevel"], "一般觀察")
        self.assertEqual(item["riskAssessment"], "limited")
        item = stock()
        item["quality"]["price"]["officialCheck"]["status"] = "unverified"
        classify_stock(item)
        self.assertEqual(item["manualCheck"], "否")
        self.assertTrue(item["qualityNotices"])
        item["quality"]["price"]["officialCheck"]["status"] = "mismatch"
        classify_stock(item)
        self.assertEqual(item["manualCheck"], "是")

    def test_industry_requires_evidence_and_symbol(self):
        article = {"scope": "industry", "relatedSymbols": ["2303"], "relevanceEvidence": "公告明確提及聯電", "isRecent": True, "publishedDate": "2026-11-11", "source": "fixture", "url": "https://example.com/a", "title": "fixture"}
        self.assertEqual(len(related_industry_news(stock(), [article, article])), 1)
        self.assertFalse(related_industry_news({"code": "2009"}, [article]))
        self.assertFalse(related_industry_news(stock(), [{**article, "scope": "market"}]))
        self.assertFalse(related_industry_news(stock(), [{**article, "relevanceEvidence": ""}]))

    def test_three_runs_dedupe_and_escalation(self):
        payload = {"stocks": [classify_stock(stock([event()]))], "marketMonitor": market_monitor(feeds())}
        pending = notification_plan(payload, {})
        self.assertEqual(len(pending), 2)
        ledger = {item["eventKey"]: item["level"] for item in pending}
        for time in ("21:20", "21:40"):
            payload["generatedAt"] = time
            self.assertFalse(notification_plan(payload, ledger))
        payload["stocks"][0]["alerts"][0]["riskLevel"] = "高"
        self.assertEqual(notification_plan(payload, ledger)[0]["action"], "escalation")
        self.assertEqual(len(notification_plan(payload, {})), 2)

    def test_new_date_and_no_unknown_date_policy_push(self):
        payload = {"stocks": [classify_stock(stock([event()]))], "marketMonitor": market_monitor(feeds())}
        pending = notification_plan(payload, {})
        ledger = {item["eventKey"]: item["level"] for item in pending}
        payload["stocks"][0]["alerts"][0]["date"] = "2026-11-12"
        payload["marketMonitor"]["items"][0]["publishedDate"] = None
        self.assertEqual(len(notification_plan(payload, ledger)), 1)


if __name__ == "__main__":
    unittest.main()
