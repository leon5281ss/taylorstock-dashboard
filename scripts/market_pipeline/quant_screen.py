"""Full-market, evidence-gated multi-factor ranker. No imputation or fake Top 10."""
import math
import re
from datetime import date
from statistics import mean, pstdev

WEIGHTS = {"technical": 0.35, "chips": 0.25, "fundamental": 0.25, "valuationRisk": 0.15}
ROSTER_URLS = {
    "TWSE": "https://openapi.twse.com.tw/v1/opendata/t187ap03_L",
    "TPEX": "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O",
}
ROSTER_FALLBACK = "https://mopsfin.twse.com.tw/opendata/t187ap03_O.csv"
REQUIRED_MARKETS = {"TWSE", "TPEX"}


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _number(value):
    try:
        item = float(str(value).replace(",", "").strip())
        return item if math.isfinite(item) else None
    except (TypeError, ValueError):
        return None


def roster(rows, market):
    """Only four-digit ordinary-company stock codes, never ETF/ETN/funds."""
    result = {}
    for row in rows:
        code = str(next((row[k] for k in (
            "公司代號", "公司代碼", "CompanyCode", "SecuritiesCompanyCode", "Code", "公司代號(股票代號)"
        ) if row.get(k) is not None), "")).strip()
        if not re.fullmatch(r"[1-9]\d{3}", code):
            continue
        name = str(next((row[k] for k in (
            "公司簡稱", "公司名稱", "CompanyName", "CompanyShortName", "SecuritiesCompanyName"
        ) if row.get(k)), code)).strip()
        if code in result:
            raise ValueError("duplicate_official_roster_code")
        result[code] = {"code": code, "name": name, "market": market}
    return result


def official_universe(fetch_json, fetch_csv=None, minimum=(1000, 700)):
    markets, errors, sources = {}, {}, {}
    for market, url in ROSTER_URLS.items():
        used = url
        try:
            rows = fetch_json(url)
            items = roster(rows, market)
            if len(items) < dict(zip(("TWSE", "TPEX"), minimum))[market]:
                raise ValueError("official_roster_incomplete")
        except (ValueError, KeyError, OSError, TypeError):
            if market != "TPEX" or fetch_csv is None:
                markets[market] = {}
                errors[market] = "official_roster_unavailable"
                continue
            try:
                used = ROSTER_FALLBACK
                items = roster(fetch_csv(used), market)
                if len(items) < minimum[1]:
                    raise ValueError("official_roster_incomplete")
            except (ValueError, KeyError, OSError, TypeError):
                markets[market] = {}
                errors[market] = "official_roster_unavailable"
                continue
        markets[market] = items
        sources[market] = used
    overlap = set(markets.get("TWSE", {})) & set(markets.get("TPEX", {}))
    if overlap:
        errors["crossMarket"] = "duplicate_company_code"
    return {"markets": markets, "errors": errors, "sources": sources}


def _ema(seq, period):
    factor = 2 / (period + 1)
    values = []
    prior = None
    for value in seq:
        prior = value if prior is None else prior + factor * (value - prior)
        values.append(prior)
    return values


def _rsi(closes):
    gains = [max(0, b - a) for a, b in zip(closes[-15:-1], closes[-14:])]
    drops = [max(0, a - b) for a, b in zip(closes[-15:-1], closes[-14:])]
    rise, fall = mean(gains), mean(drops)
    return 100 if fall == 0 else 100 - 100 / (1 + rise / fall)


def _rows(record, key, n, dates):
    rows = record.get(key)
    if not isinstance(rows, list) or len(rows) < n:
        raise ValueError(key + "_insufficient_history")
    tail = rows[-n:]
    if [row.get("date") for row in tail] != dates[-n:]:
        raise ValueError(key + "_date_gap")
    return tail


def metrics(record, as_of):
    """Fail closed if any required 35/25/25/15 component lacks evidence."""
    prices = record.get("prices", [])
    if len(prices) < 121 or prices[-1].get("date") != as_of or not record.get("corporateActionsChecked"):
        raise ValueError("price_history_or_adjustments_missing")
    dates = [row.get("date") for row in prices]
    if dates != sorted(set(dates)):
        raise ValueError("price_dates_invalid")
    close = [row.get("close") for row in prices]
    if not all(_finite(v) and v > 0 for v in close):
        raise ValueError("price_values_invalid")
    if not all(_finite(row.get("volume")) and row["volume"] >= 0 and
               _finite(row.get("turnover")) and row["turnover"] >= 0 for row in prices[-20:]):
        raise ValueError("liquidity_values_missing")
    institutions = _rows(record, "institutional", 5, dates)
    margins = _rows(record, "margin", 5, dates)
    borrows = _rows(record, "borrow", 5, dates)
    if not all(all(_finite(row.get(k)) for k in ("foreign", "trust")) for row in institutions):
        raise ValueError("institutional_fields_missing")
    if not all(_finite(row.get("balance")) and row["balance"] >= 0 for row in borrows):
        raise ValueError("borrow_balance_missing")
    if not all(_finite(row.get("balance")) and row["balance"] >= 0 for row in margins):
        raise ValueError("margin_balance_missing")
    tdcc = record.get("tdcc") or {}
    if not _finite(tdcc.get("largeHolderRatio")) or not 0 <= tdcc["largeHolderRatio"] <= 1:
        raise ValueError("tdcc_concentration_missing")
    try:
        tdcc_age = (date.fromisoformat(as_of) - date.fromisoformat(tdcc["date"])).days
    except (KeyError, ValueError, TypeError):
        raise ValueError("tdcc_date_invalid") from None
    if tdcc_age < 0 or tdcc_age > 14:
        raise ValueError("tdcc_stale")
    f = record.get("fundamentals") or {}
    v = record.get("valuation") or {}
    if not isinstance(f.get("eps5y"), list) or len(f["eps5y"]) != 5 or not all(_finite(x) for x in f["eps5y"]):
        raise ValueError("five_year_eps_missing")
    if not all(_finite(f.get(k)) for k in ("revenueYoY", "roe", "operatingMargin", "epsTTM")):
        raise ValueError("fundamentals_missing")
    if not all(_finite(v.get(k)) for k in ("pe", "pb", "dividendYield")) or v["pe"] <= 0 or v["pb"] <= 0:
        raise ValueError("valuation_missing")
    if v.get("date") != as_of:
        raise ValueError("valuation_date_not_current")
    for key, limit in (("financialPublishedAt", 430), ("revenuePublishedAt", 75)):
        try:
            age = (date.fromisoformat(as_of) - date.fromisoformat(f[key])).days
        except (KeyError, ValueError, TypeError):
            raise ValueError(key + "_invalid") from None
        if age < 0 or age > limit:
            raise ValueError(key + "_stale_or_future")
    sum_volume = sum(row["volume"] for row in prices[-5:])
    if sum_volume <= 0:
        raise ValueError("zero_recent_volume")
    ma = lambda n: mean(close[-n:])
    ema12, ema26 = _ema(close, 12), _ema(close, 26)
    macd = [a - b for a, b in zip(ema12, ema26)]
    histogram = macd[-1] - _ema(macd, 9)[-1]
    mean20 = mean(close[-20:])
    volatility = pstdev([(b / a - 1) for a, b in zip(close[-21:-1], close[-20:])])
    margin5 = margins[-1]["balance"] - margins[0]["balance"]
    borrow5 = borrows[-1]["balance"] - borrows[0]["balance"]
    avg_turnover = mean(row["turnover"] for row in prices[-20:])
    return {
        "technical": {
            "momentum5": close[-1] / close[-6] - 1,
            "momentum20": close[-1] / close[-21] - 1,
            "trend": (close[-1] / ma(20) - 1) + (ma(20) / ma(60) - 1) +
                     (ma(60) / ma(120) - 1),
            "macdHistogram": histogram / close[-1],
            "rsi14": _rsi(close),
        },
        "chips": {
            "foreign5": sum(row["foreign"] for row in institutions) / sum_volume,
            "trust5": sum(row["trust"] for row in institutions) / sum_volume,
            "marginDeleveraging": -margin5 / max(1, margins[0]["balance"]),
            "borrowReduction": -borrow5 / max(1, borrows[0]["balance"]),
            "largeHolderRatio": tdcc["largeHolderRatio"],
        },
        "fundamental": {
            "eps5yAverage": mean(f["eps5y"]), "epsTTM": f["epsTTM"],
            "revenueYoY": f["revenueYoY"], "roe": f["roe"],
            "operatingMargin": f["operatingMargin"],
        },
        "valuationRisk": {
            "inversePe": 1 / v["pe"], "inversePb": 1 / v["pb"],
            "dividendYield": v["dividendYield"],
            "inverseVolatility": 1 / max(volatility, 0.000001),
        },
        "liquidity": avg_turnover,
        "reference": {"ma5": ma(5), "ma20": ma(20), "ma60": ma(60),
                      "ma120": ma(120), "rsi14": _rsi(close), "volatility20": volatility},
    }


def _percentiles(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [None] * len(values)
    i = 0
    while i < len(order):
        j = i + 1
        while j < len(order) and values[order[i]] == values[order[j]]:
            j += 1
        score = 50 if len(order) == 1 else 100 * ((i + j - 1) / 2) / (len(order) - 1)
        for idx in order[i:j]:
            ranks[idx] = score
        i = j
    return ranks


def screen(official, enrichment, as_of, minimum=(1000, 700)):
    """Never return a Top10 unless both official markets and every factor are complete."""
    markets = official["markets"]
    expected = {code: row for market in ("TWSE", "TPEX") for code, row in markets.get(market, {}).items()}
    errors = dict(official.get("errors", {}))
    complete = {}
    reasons = {}
    if len(markets.get("TWSE", {})) < minimum[0] or len(markets.get("TPEX", {})) < minimum[1]:
        errors["universe"] = "incomplete_official_twse_tpex"
    if not expected:
        errors["universe"] = "no_official_universe"
    if set(enrichment) - set(expected):
        errors["unknownInputSymbols"] = "enrichment_contains_unlisted_codes"
    for code in sorted(expected):
        if code not in enrichment:
            reasons[code] = "enrichment_missing"
            continue
        record = enrichment[code]
        if record.get("market") != expected[code]["market"] or record.get("asOf") != as_of:
            reasons[code] = "market_or_date_mismatch"
            continue
        try:
            complete[code] = metrics(record, as_of)
        except (ValueError, TypeError, KeyError, ZeroDivisionError) as exc:
            reasons[code] = str(exc)
    status = "ready" if not errors and len(complete) == len(expected) and len(expected) >= sum(minimum) else "not_publishable"
    result = {"asOf": as_of, "status": status,
              "weights": {k: int(w * 100) for k, w in WEIGHTS.items()},
              "officialUniverseCount": len(expected),
              "marketCounts": {m: len(markets.get(m, {})) for m in ("TWSE", "TPEX")},
              "factorCompleteCount": len(complete),
              "missingCount": len(reasons), "errorReasons": errors,
              "missingReasons": {k: sum(1 for r in reasons.values() if r == k) for k in set(reasons.values())},
              "top10": None}
    if status != "ready":
        return result
    codes = sorted(complete)
    factor_scores = {code: {} for code in codes}
    for factor in WEIGHTS:
        components = list(complete[codes[0]][factor])
        for key in components:
            scores = _percentiles([complete[c][factor][key] for c in codes])
            for code, score in zip(codes, scores):
                factor_scores[code].setdefault(factor, []).append(score)
    total = []
    for code in codes:
        factors = {f: round(mean(factor_scores[code][f]), 2) for f in WEIGHTS}
        score = round(sum(WEIGHTS[f] * factors[f] for f in WEIGHTS), 2)
        total.append({"code": code, "name": expected[code]["name"],
                      "market": expected[code]["market"],
                      "score": score, "factorScores": factors})
    result["top10"] = sorted(total, key=lambda row: (-row["score"], row["code"]))[:10]
    return result
