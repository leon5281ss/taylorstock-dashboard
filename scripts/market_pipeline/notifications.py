import hashlib
import json

from .risk import LEVELS


def notification_plan(payload, delivered):
    candidates = []
    for stock in payload["stocks"]:
        for alert in stock["alerts"]:
            if alert.get("riskLevel", "一般觀察") == "一般觀察":
                continue
            candidates.append({"scope": "stock", "symbol": stock["code"], "rule": alert["rule"], "date": alert["date"], "article": alert.get("url", ""), "level": alert["riskLevel"]})
    for item in payload.get("marketMonitor", {}).get("items", []):
        if item.get("isRecent") and item.get("publishedDate"):
            candidates.append({"scope": "market", "symbol": "", "rule": "policy_news", "date": item["publishedDate"], "article": item["eventId"], "level": "中"})
    planned = {}
    for event in candidates:
        identity = {key: value for key, value in event.items() if key != "level"}
        key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        prior = delivered.get(key)
        if prior and LEVELS[event["level"]] <= LEVELS[prior]:
            continue
        planned[key] = {**event, "eventKey": key, "action": "escalation" if prior else "new"}
    return list(planned.values())
