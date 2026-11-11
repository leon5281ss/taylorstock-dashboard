import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from market_pipeline.pipeline import ROOT, TAIPEI
from market_pipeline.sources import DATASETS, HttpClient, SourceError, normalize_finmind

DIAGNOSTIC_PATH = ROOT / "diagnostics" / "finmind-smoke.json"


def smoke(token, client_factory=HttpClient, now=None):
    now = now or datetime.now(TAIPEI)
    end = (now.date() - timedelta(days=1)).isoformat()
    start = (now.date() - timedelta(days=15)).isoformat()
    result = {"symbol": "2303", "startDate": start, "endDate": end, "authentication": "bearer_header", "checks": [], "status": "failed"}
    if not token.strip():
        result["checks"].append({"dataset": DATASETS["price"], "category": "missing_token"})
        return result
    client = client_factory(token, attempts=2)
    for kind, dataset in [*DATASETS.items(), ("calendar", "TaiwanStockTradingDate")]:
        try:
            rows = client.dataset(dataset, start, end, None if kind == "calendar" else "2303")
            if kind != "calendar":
                rows, issues = normalize_finmind(kind, rows, "2303", start, end)
                if issues:
                    raise SourceError("invalid_response")
            else:
                rows = [row for row in rows if isinstance(row.get("date"), str) and start <= row["date"] <= end]
            if not rows:
                raise SourceError("empty_data")
            result["checks"].append({"dataset": dataset, "category": "ok", "rowCount": len(rows), "latestDate": max(row["date"] for row in rows)})
        except SourceError as exc:
            result["checks"].append({"dataset": dataset, **exc.diagnostic()})
            if kind == "price":
                try:
                    rows = client_factory("", attempts=1).dataset(dataset, start, end, "2303")
                    result["anonymousControl"] = {"category": "ok" if rows else "empty_data"}
                except SourceError as control:
                    result["anonymousControl"] = control.diagnostic()
            break
    if len(result["checks"]) == 4 and all(check["category"] == "ok" for check in result["checks"]):
        result["status"] = "passed"
    return result


def main():
    try:
        result = smoke(os.environ.get("FINMIND_TOKEN", ""))
    except Exception:
        result = {"status": "failed", "checks": [{"category": "unexpected_diagnostic_error"}]}
    DIAGNOSTIC_PATH.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(result, ensure_ascii=True, indent=2)
    DIAGNOSTIC_PATH.write_text(content + "\n", encoding="utf-8")
    print(content)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
