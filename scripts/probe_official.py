import json
from datetime import datetime, timedelta

from market_pipeline.news import collect_news
from market_pipeline.pipeline import ROOT, TAIPEI, calendar_context, load_watchlist
from market_pipeline.sources import HttpClient, official_record, official_snapshots


def main():
    now = datetime.now(TAIPEI)
    client = HttpClient(attempts=1)
    calendar = calendar_context(client, now, (now.date() - timedelta(days=240)).isoformat())
    target = calendar["targetDate"]
    if target is None:
        raise ValueError("calendar_target_unavailable")
    snapshots = official_snapshots(client, target)
    results = {}
    for item in load_watchlist(ROOT / "config/watchlist_public.json"):
        results[item["code"]] = {}
        for kind in ("price", "institutional", "margin"):
            snapshot = snapshots[item["market"] + "_" + kind]
            record = official_record(snapshot, item["market"], kind, item["code"])
            results[item["code"]][kind] = {"status": snapshot["status"], "record": record}
    payload = {"checkedAt": now.isoformat(), "official": results, "calendar": calendar, "news": collect_news(client, now)}
    print(json.dumps(payload, ensure_ascii=True))


if __name__ == "__main__":
    main()

