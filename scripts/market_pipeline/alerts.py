from statistics import mean


def evaluate(price, institutional, margin, calendar, target, blocked=()):
    alerts, unavailable, indicators = [], [], {}
    days = sorted(day for day in calendar if day <= target)
    prices = {row["date"]: row for row in price}
    institutions = {row["date"]: row for row in institutional}
    margins = {row["date"]: row for row in margin}

    def emit(rule, message, source):
        alerts.append({"rule": rule, "message": message, "date": target, "source": source})

    for field in ("foreign", "trust"):
        streak = 0
        sign = None
        if "institutional" not in blocked:
            for day in reversed(days):
                value = institutions.get(day, {}).get(field)
                if value is None or value == 0:
                    break
                direction = 1 if value > 0 else -1
                if sign is not None and sign != direction:
                    break
                sign, streak = direction, streak + 1
        if not days or target not in institutions or "institutional" in blocked:
            unavailable.append(field + "_streak")
        elif streak >= 3:
            emit(field + "_streak", f"{'外資' if field == 'foreign' else '投信'}連續 {streak} 個交易日{'買超' if sign == 1 else '賣超'}", "TaiwanStockInstitutionalInvestorsBuySell")
    current = prices.get(target)
    previous = prices.get(days[-2]) if len(days) >= 2 else None
    if not current or "price" in blocked or not days or days[-1] != target:
        return alerts, {"ma20": None, "ma60": None}, sorted(set(unavailable + ["price_rules"]))
    for window in (20, 60):
        recent = days[-window:]
        before = days[-window - 1:-1]
        current_ma = mean(prices[day]["close"] for day in recent) if len(recent) == window and all(day in prices for day in recent) else None
        previous_ma = mean(prices[day]["close"] for day in before) if len(before) == window and all(day in prices for day in before) else None
        indicators["ma" + str(window)] = current_ma
        if current_ma is None or previous_ma is None or previous is None:
            unavailable.append("ma" + str(window))
        elif current["close"] < current_ma and previous["close"] >= previous_ma:
            emit("cross_below_ma" + str(window), f"收盤價跌破 MA{window}", "TaiwanStockPrice")
    baseline_days = days[-21:-1]
    if len(baseline_days) == 20 and all(day in prices for day in baseline_days):
        baseline = mean(prices[day]["volume"] for day in baseline_days)
        indicators["volumeRatio"] = current["volume"] / baseline if baseline else None
        if baseline and (current["volume"] >= baseline * 2 or current["volume"] <= baseline * 0.5):
            emit("abnormal_volume", f"成交量為前 20 個交易日均量的 {current['volume'] / baseline:.2f} 倍", "TaiwanStockPrice")
    else:
        unavailable.append("abnormal_volume")
    balance = margins.get(target, {})
    prior_balance = balance.get("marginPrevious")
    change = balance.get("marginChange")
    if "margin" in blocked or prior_balance is None or change is None:
        unavailable.extend(["margin_surge", "deleveraging_drop"])
    else:
        if prior_balance > 0 and change >= 100 and change / prior_balance >= 0.1:
            emit("margin_surge", "融資日增至少 10% 且增加至少 100 張", "TaiwanStockMarginPurchaseShortSale")
        if previous and change < 0 and current["close"] / previous["close"] - 1 <= -0.05:
            emit("deleveraging_drop", "融資減少且收盤價日跌至少 5%（需排除除權息等因素）", "TaiwanStockPrice + TaiwanStockMarginPurchaseShortSale")
        elif previous is None:
            unavailable.append("deleveraging_drop")
    return alerts, indicators, sorted(set(unavailable))

