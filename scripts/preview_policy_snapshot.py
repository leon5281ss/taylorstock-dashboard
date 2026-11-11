import json
from urllib.request import urlopen

from market_pipeline.alerts import evaluate
from market_pipeline.monitor import market_monitor
from market_pipeline.pipeline import assert_public
from market_pipeline.risk import classify_stock


def preview(payload):
    assert_public(payload)
    before = payload["summary"]["manualCheckCount"]
    calendar = payload["calendar"]
    target = calendar["targetDate"]
    for stock in payload["stocks"]:
        blocked = [kind for kind, quality in stock["quality"].items() if quality["status"] in ("mismatch", "invalid_or_incomplete")]
        if calendar["issues"] or target not in calendar["dates"]:
            blocked = ["price", "institutional", "margin"]
        stock["alerts"], stock["technical"], stock["unavailableRules"] = evaluate(stock["history"]["price"], stock["history"]["institutional"], stock["history"]["margin"], calendar["dates"], target, blocked)
        classify_stock(stock)
    return {"snapshotGeneratedAt": payload["generatedAt"], "stockCount": len(payload["stocks"]), "beforeManual": before, "afterManual": sum(stock["manualCheck"] == "是" for stock in payload["stocks"]), "riskCounts": {level: sum(stock["riskLevel"] == level for stock in payload["stocks"]) for level in ("高", "中", "一般觀察")}, "marketItems": len(market_monitor(payload["policyNews"])["items"])}


if __name__ == "__main__":
    with urlopen("https://leon5281ss.github.io/taylorstock-dashboard/data/stocks.json", timeout=30) as response:
        payload = json.load(response)
    print(json.dumps(preview(payload), ensure_ascii=False, indent=2))
