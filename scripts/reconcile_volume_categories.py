"""Research reconciliation of independently sourced TPEx share volumes."""
from datetime import date

COMPONENTS = ("intradayOddLot", "afterHoursOddLot", "afterHoursFixedPrice", "block")
SOURCES = {
    "intradayOddLot": "https://www.tpex.org.tw/zh-tw/mainboard/trading/info/odd-lot/pricing.html",
    "afterHoursOddLot": "https://www.tpex.org.tw/zh-tw/mainboard/trading/info/odd-lot/post-pricing/day.html",
    "afterHoursFixedPrice": "https://www.tpex.org.tw/zh-tw/mainboard/trading/info/post.html",
    "block": "https://www.tpex.org.tw/zh-tw/mainboard/trading/block-trading/pricing.html",
}


def reconcile(day, code, historical_shares, daily_shares, components):
    """Compute a diagnostic residual only for complete, aligned observations."""
    day = date.fromisoformat(day).isoformat()
    missing, rejected, accepted = [], [], {}
    for category in COMPONENTS:
        item = components.get(category)
        if item is None:
            missing.append(category)
        elif (not isinstance(item, dict) or item.get("market") != "TPEX"
              or item.get("date") != day or item.get("code") != code
              or item.get("unit") != "shares" or item.get("source") != SOURCES[category]
              or type(item.get("quantity")) is not int or item["quantity"] < 0):
            rejected.append(category)
        else:
            accepted[category] = item["quantity"]
    observed = (
        daily_shares - historical_shares
        if all(type(n) is int and n >= 0 for n in (historical_shares, daily_shares)) else None
    )
    residual = observed - sum(accepted.values()) if observed is not None and not (missing or rejected) else None
    return {"market": "TPEX", "date": day, "code": code,
            "dailyMinusHistoricalShares": observed, "componentShares": accepted,
            "missingComponents": missing, "rejectedComponents": rejected,
            "arithmeticResidualShares": residual, "scopeEquivalenceVerified": False,
            "v5v60": None, "top10": None, "publishable": False}
