from market_pipeline.pipeline import ROOT, load_watchlist, write_outputs
from market_pipeline.sources import DATASETS, FINMIND, OFFICIAL, government_bank


def main():
    stocks = []
    for item in load_watchlist(ROOT / "config/watchlist_public.json"):
        quality = {kind: {"status": "not_collected", "date": None, "source": source, "endpoint": FINMIND, "issues": [], "missingDates": [], "officialCheck": {"source": OFFICIAL.get(item["market"] + "_" + kind, "https://www.twse.com.tw"), "status": "unverified", "officialDate": None, "reason": "not_collected"}} for kind, source in DATASETS.items()}
        stocks.append({
            **item, "instrumentType": item.get("instrumentType", "stock"),
            "price": None, "updatedAt": None, "totalScore": None,
            "status": "資料不足", "manualCheck": "是", "dataQualityStatus": "尚未收集",
            "riskReasons": ["等待首次 Actions 收集"], "technical": {"ma20": None, "ma60": None},
            "latest": {kind: None for kind in DATASETS}, "history": {kind: [] for kind in DATASETS},
            "quality": quality, "alerts": [], "unavailableRules": ["尚未收集"],
            "fundamentals": {"status": "not_applicable" if item["code"] in ("00685L", "00981A") else "not_collected", "score": None, "reason": "尚未收集；ETF 不適用公司基本面評分"},
            "governmentBank": government_bank(None, item["code"], "", ""),
        })
    write_outputs({
        "schemaVersion": 3, "generatedAt": None, "reportStatus": "not_collected",
        "calendar": {"requestedDate": None, "targetDate": None, "status": "not_collected", "dates": [], "issues": [], "sources": []},
        "summary": {"stockCount": 22, "completeCount": 0, "asOf": None, "oldestDataDate": None, "latestDataDate": None, "averageScore": None, "exitCount": 0, "reduceCount": 0, "manualCheckCount": 22, "positionAmountsPublished": False},
        "stocks": stocks, "policyNews": [], "disclaimer": "初始化空資料；等待首次成功收集，不代表真實報價。",
    }, ROOT / "docs/data")


if __name__ == "__main__":
    main()

