"""Immutable next-open paper-trading recommendations, verified after maturity."""
from collections import Counter, defaultdict
from datetime import date
from math import isfinite, sqrt

HORIZONS = (5, 20)
FEE = 0.0004275
STOCK_TAX = 0.003


def _valid(v):
    return isinstance(v, (float, int)) and not isinstance(v, bool) and isfinite(v)


def _wilson(wins, n):
    if not n:
        return None
    p, z = wins / n, 1.96
    den = 1 + z*z/n
    midpoint = (p + z*z/(2*n)) / den
    spread = z * sqrt(p*(1-p)/n + z*z/(4*n*n)) / den
    return [round(max(0, midpoint-spread), 4), round(min(1, midpoint+spread), 4)]


def audit(signals, official_sessions, history, as_of, taiwan_targets=None):
    """Selection-day close signal fills NEXT trading session open; exit at H-th close."""
    date.fromisoformat(as_of)
    if not official_sessions or official_sessions != sorted(set(official_sessions)):
        raise ValueError("invalid_official_sessions")
    index = {day: n for n, day in enumerate(official_sessions)}
    if official_sessions[-1] < as_of:
        raise ValueError("calendar_outdated")
    seen, trades, unresolved = set(), [], Counter()
    for signal in signals:
        required = ("selectionDate", "publishedAt", "code", "strategyId",
                    "strategyVersion", "horizon", "shares", "source")
        if any(not signal.get(k) for k in required):
            raise ValueError("signal_schema_invalid")
        key = tuple(signal[k] for k in ("selectionDate", "code", "strategyId",
                                        "strategyVersion", "horizon"))
        if key in seen:
            raise ValueError("duplicate_signal")
        seen.add(key)
        selected = signal["selectionDate"]
        if signal["horizon"] not in HORIZONS or type(signal["shares"]) is not int or signal["shares"] <= 0:
            raise ValueError("unsupported_horizon_or_shares")
        if signal.get("instrumentType", "stock") != "stock":
            raise ValueError("tax_model_stock_only")
        if not signal["publishedAt"].startswith(selected + "T") or not signal["publishedAt"].endswith("+08:00"):
            raise ValueError("taipei_publication_time_required")
        if selected not in index or selected > as_of:
            unresolved["unknown_selection_day"] += 1
            continue
        first, last = index[selected] + 1, index[selected] + signal["horizon"]
        if last >= len(official_sessions) or official_sessions[last] > as_of:
            unresolved["unmatured"] += 1
            continue
        stock = history.get(signal["code"]) or {}
        if stock.get("corporateActionsChecked") is not True:
            unresolved["unverified_corporate_actions"] += 1
            continue
        rows = {p["date"]: p for p in stock.get("prices", []) if "date" in p}
        entry, exit = rows.get(official_sessions[first]), rows.get(official_sessions[last])
        if not entry or not exit:
            unresolved["missing_executable_prices"] += 1
            continue
        buy, sell = entry.get("open"), exit.get("close")
        if not _valid(buy) or not _valid(sell) or buy <= 0 or sell <= 0:
            unresolved["invalid_executable_prices"] += 1
            continue
        shares = signal["shares"]
        buy_amount, sell_amount = buy*shares, sell*shares
        buy_fee = round(buy_amount*FEE)
        sell_fee = round(sell_amount*FEE)
        tax = round(sell_amount*STOCK_TAX)
        net = round(sell_amount-buy_amount-buy_fee-sell_fee-tax)
        gross = round(sell_amount-buy_amount)
        reasons = []
        if sell < buy:
            reasons.append("price_decline")
        if gross > 0 and net <= 0:
            reasons.append("fee_tax_erased_profit")
        if net < -0.05*buy_amount:
            reasons.append("large_adverse_move")
        if signal.get("inputQuality") == "partial":
            reasons.append("weak_input_quality")
        trades.append({"code": signal["code"], "selectionDate": selected,
                       "strategyId": signal["strategyId"], "strategyVersion": signal["strategyVersion"],
                       "horizon": signal["horizon"], "entryDate": official_sessions[first],
                       "exitDate": official_sessions[last], "entryPrice": buy, "exitPrice": sell,
                       "buyFeeEstimate": buy_fee, "sellFeeEstimate": sell_fee,
                       "taxEstimate": tax, "grossPnl": gross, "netPnl": net,
                       "netReturn": round(net/(buy_amount+buy_fee), 6),
                       "win": net > 0, "diagnosis": reasons})
    grouped = defaultdict(list)
    for t in trades:
        grouped[(t["strategyId"], t["strategyVersion"], t["horizon"])].append(t)
    stats = []
    for (sid, version, horizon), rows in sorted(grouped.items()):
        n = len(rows)
        wins = sum(t["win"] for t in rows)
        wr = wins/n
        ci = _wilson(wins, n)
        reference = (taiwan_targets or {}).get(sid)
        decision = "no_taiwan_benchmark"
        if reference is not None:
            if not _valid(reference) or not 0 <= reference <= 1:
                raise ValueError("invalid_taiwan_reference_win_rate")
            if n < 100:
                decision = "sample_insufficient"
            elif ci[1] < reference-0.05:
                decision = "statistically_below_baseline"
            elif wr < reference-0.05:
                decision = "degradation_watch"
            else:
                decision = "within_tolerance"
        reasons = Counter(code for t in rows if not t["win"] for code in t["diagnosis"])
        stats.append({"strategyId": sid, "strategyVersion": version, "horizon": horizon,
                      "trades": n, "wins": wins, "winRate": round(wr, 4),
                      "wilson95": ci, "totalNetPnl": sum(t["netPnl"] for t in rows),
                      "avgNetReturn": round(sum(t["netReturn"] for t in rows)/n, 6),
                      "referenceWinRate": reference, "assessment": decision,
                      "failureDrivers": dict(reasons)})
    return {"asOf": as_of, "status": "evaluated" if trades else "no_matured_recommendations",
            "netOfCosts": True, "feeBasis": "estimated Yuanta 0.04275pct per side, stock 0.3pct sale tax",
            "maturedTrades": len(trades), "unresolved": dict(unresolved),
            "byStrategy": stats, "trades": trades}
