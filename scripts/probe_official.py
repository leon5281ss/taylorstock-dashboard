import json
from datetime import datetime

from market_pipeline.news import collect_news
from market_pipeline.pipeline import ROOT, TAIPEI, calendar_context, load_watchlist
from market_pipeline.sources import HttpClient, official_record, official_snapshots


def main():
    now = datetime.now(TAIPEI)
    client = HttpClient(attempts=1)
    target = now.date().isoformat()
    snapshots = official_snapshots(client, target)
    results = {}
    for item in load_watchlist(ROOT / "config/watchlist_public.json"):
        results[item["code"]] = {}
        for kind in ("price", "institutional", "margin"):
            snapshot = snapshots[item["market"] + "_" + kind]
            record = official_record(snapshot, item["market"], kind, item["code"])
            results[item["code"]][kind] = {"status": snapshot["status"], "record": record}
    payload = {"checkedAt": now.isoformat(), "official": results, "calendar": calendar_context(client, target, target[:4] + "-01-01"), "news": collect_news(client, now)}
    print(json.dumps(payload, ensure_ascii=True))


if __name__ == "__main__":
    main()

