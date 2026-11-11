LEVELS = {"一般觀察": 0, "中": 1, "高": 2}


def classify_stock(stock):
    alerts = []
    seen = set()
    for alert in stock["alerts"]:
        if alert["rule"] == "policy_news":
            continue
        key = (alert["rule"], alert.get("date"), alert.get("url", ""))
        if key in seen:
            continue
        seen.add(key)
        rule = alert["rule"]
        level = "一般觀察"
        if rule in ("deleveraging_drop", "cross_below_ma60"):
            level = "高"
        elif rule in ("cross_below_ma20", "margin_surge", "abnormal_volume", "industry_news"):
            level = "中"
        elif rule in ("foreign_streak", "trust_streak") and alert.get("direction") == "sell":
            level = "中"
        alerts.append({**alert, "riskLevel": level})
    stock["alerts"] = alerts
    stock["riskLevel"] = max((alert["riskLevel"] for alert in alerts), key=LEVELS.get, default="一般觀察")
    quality_reasons = []
    quality_notices = []
    for kind, quality in stock["quality"].items():
        if quality["status"] != "ok":
            quality_reasons.append(kind + ":" + quality["status"])
        check = quality["officialCheck"]
        if check["status"] == "mismatch":
            quality_reasons.append(kind + ":official_mismatch")
        elif check["status"] != "verified":
            quality_notices.append(kind + ":official_" + check["status"])
    quality_notices.extend(stock["unavailableRules"])
    stock["qualityReviewRequired"] = bool(quality_reasons)
    stock["qualityNotices"] = sorted(set(quality_notices))
    stock["riskAssessment"] = "limited" if quality_reasons or quality_notices else "available"
    stock["manualCheckReasons"] = [alert["message"] for alert in alerts if alert["riskLevel"] != "一般觀察"] + sorted(set(quality_reasons))
    stock["manualCheck"] = "是" if stock["manualCheckReasons"] else "否"
    stock["riskReasons"] = stock["manualCheckReasons"]
    return stock
