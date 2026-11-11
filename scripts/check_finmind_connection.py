import os
from datetime import datetime, timedelta

from market_pipeline.pipeline import TAIPEI
from market_pipeline.sources import HttpClient, SourceError


def main():
    token = os.environ.get("FINMIND_TOKEN", "").strip()
    if not token:
        print("FINMIND_TOKEN 未設定")
        return 2
    today = datetime.now(TAIPEI).date()
    try:
        rows = HttpClient(token).dataset("TaiwanStockPrice", (today - timedelta(days=14)).isoformat(), today.isoformat(), "2303")
        print("FinMind HTTP connected" if rows else "FinMind HTTP connected；查詢區間無資料")
        return 0
    except SourceError as exc:
        print("FinMind connection: " + str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

