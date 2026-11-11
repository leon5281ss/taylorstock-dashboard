import argparse
import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .alerts import evaluate
from .news import collect_news
from .monitor import market_monitor, related_industry_news
from .risk import classify_stock
from .sources import DATASETS, FINMIND, HOLIDAYS, HttpClient, SourceError, compare_official, government_bank, iso_date, normalize_finmind, official_record, official_snapshots

ROOT = Path(__file__).resolve().parents[2]
TAIPEI = timezone(timedelta(hours=8))
PRIVATE_KEYS = {"shares", "quantity", "averagecost", "cost", "average_cost", "gainlossrate", "unrealizedpnlrate", "unrealizedpnl", "marketvalue", "totalmarketvalue", "totalunrealizedpnl", "overallreturnrate", "token", "authorization", "positions", "持有股數", "成本均價", "損益"}


def load_watchlist(path):
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list) or len(rows) != 22 or len({row["code"] for row in rows}) != 22:
        raise ValueError("watchlist_must_have_22_unique_symbols")
    if not {"00685L", "00981A"}.issubset({row["code"] for row in rows}):
        raise ValueError("required_etfs_missing")
    for row in rows:
        if set(row) - {"code", "name", "market", "category", "instrumentType"} or row["market"] not in ("TWSE", "TPEX"):
            raise ValueError("invalid_public_watchlist")
    return rows


def assert_public(payload, token=""):
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key.lower() in PRIVATE_KEYS:
                raise ValueError("private_field_rejected")
            assert_public(value, token)
    elif isinstance(payload, list):
        for value in payload:
            assert_public(value, token)
    elif isinstance(payload, str) and token and token in payload:
        raise ValueError("secret_rejected")


def calendar_context(client, today, start):
    issues, days = [], []
    diagnostic = None
    try:
        rows = client.dataset("TaiwanStockTradingDate", start, today)
        days = sorted({iso_date(row["date"]) for row in rows if start <= iso_date(row["date"]) <= today})
        if not days:
            issues.append("empty_trading_calendar")
    except SourceError as exc:
        diagnostic = exc.diagnostic()
        issues.append("trading_calendar_unavailable")
    except (ValueError, KeyError, TypeError):
        issues.append("trading_calendar_unavailable")
    closures, openings = set(), set()
    covered = False
    try:
        holiday_rows = client.get(HOLIDAYS)
        if not isinstance(holiday_rows, list) or not holiday_rows:
            raise ValueError("invalid_calendar")
        for row in holiday_rows:
            day = iso_date(row["Date"])
            covered = covered or day[:4] == today[:4]
            text = row["Name"] + row.get("Description", "")
            if "開始交易" in text or "最後交易" in text:
                openings.add(day)
            elif "放假" in text or "休市" in text or "無交易" in text or "補假" in text:
                closures.add(day)
    except (SourceError, ValueError, KeyError, TypeError):
        issues.append("official_calendar_unavailable")
    is_closed = today in closures or (date.fromisoformat(today).weekday() >= 5 and today not in openings)
    if is_closed:
        target = max((day for day in days if day < today), default=None)
        status = "non_trading_day"
    else:
        target = today
        status = "trading_day" if today in days else "awaiting_confirmation"
    if not covered:
        issues.append("official_calendar_year_unverified")
    return {"requestedDate": today, "targetDate": target, "status": status, "dates": days, "issues": issues, "diagnostic": diagnostic, "sources": ["FinMind/TaiwanStockTradingDate", HOLIDAYS]}


def collect_stock(client, item, target, start, days, snapshots, calendar_ok):
    histories, qualities, latest = {}, {}, {}
    for kind, dataset in DATASETS.items():
        diagnostic = None
        try:
            raw = client.dataset(dataset, start, target, item["code"])
            rows, issues = normalize_finmind(kind, raw, item["code"], start, target)
            state = "ok" if rows and rows[-1]["date"] == target else "delayed" if rows else "missing"
        except SourceError as exc:
            rows, issues, state = [], [], str(exc)
            diagnostic = exc.diagnostic()
        histories[kind] = rows
        latest[kind] = rows[-1] if rows else None
        source = snapshots[item["market"] + "_" + kind]
        official = official_record(source, item["market"], kind, item["code"])
        comparison = compare_official(latest[kind], official, source)
        if issues and state == "ok":
            state = "invalid_or_incomplete"
        if comparison["status"] == "mismatch":
            state = "mismatch"
        available_dates = {row["date"] for row in rows}
        missing_dates = [day for day in days if rows and rows[0]["date"] <= day <= target and day not in available_dates]
        if missing_dates and state == "ok":
            state = "history_gaps"
        qualities[kind] = {"status": state, "date": rows[-1]["date"] if rows else None, "source": dataset, "endpoint": FINMIND, "issues": issues, "missingDates": missing_dates, "officialCheck": comparison}
        if diagnostic:
            qualities[kind]["diagnostic"] = diagnostic
    blocked = [kind for kind, quality in qualities.items() if quality["status"] in ("mismatch", "invalid_or_incomplete")]
    if not calendar_ok:
        blocked = list(DATASETS)
    alerts, indicators, unavailable = evaluate(histories["price"], histories["institutional"], histories["margin"], days, target, blocked)
    is_etf = item["code"] in ("00685L", "00981A")
    current_price = latest["price"]
    complete = all(quality["status"] == "ok" for quality in qualities.values())
    verified = all(quality["officialCheck"]["status"] == "verified" for quality in qualities.values())
    return {
        **{key: item[key] for key in ("code", "name", "market", "category")},
        "instrumentType": item.get("instrumentType", "stock"),
        "price": current_price["close"] if current_price else None,
        "updatedAt": current_price["date"] if current_price else None,
        "totalScore": None,
        "status": "觀察" if complete else "資料不足",
        "manualCheck": "是" if alerts or not complete or not verified else "否",
        "dataQualityStatus": "資料完整且已核對" if complete and verified else "資料完整／官方待核對" if complete else "缺漏、延遲或核對異常",
        "riskReasons": [alert["message"] for alert in alerts] + [kind + ":" + quality["status"] for kind, quality in qualities.items() if quality["status"] != "ok"],
        "technical": indicators,
        "latest": latest,
        "history": histories,
        "quality": qualities,
        "alerts": alerts,
        "unavailableRules": unavailable,
        "fundamentals": {"status": "not_applicable" if is_etf else "not_collected", "score": None, "reason": "ETF 不套用公司 EPS、營收評分" if is_etf else "本版僅收集價量與籌碼，不計算綜合分數"},
        "governmentBank": government_bank(client, item["code"], start, target),
    }


def collect(client, watchlist, now, industry_items=None):
    today = now.date().isoformat()
    start = (now.date() - timedelta(days=240)).isoformat()
    calendar = calendar_context(client, today, start)
    target = calendar["targetDate"] or today
    snapshots = official_snapshots(client, target)
    stocks = [collect_stock(client, item, target, start, calendar["dates"], snapshots, not calendar["issues"] and target in calendar["dates"]) for item in watchlist]
    news = collect_news(client, now)
    for stock in stocks:
        stock["alerts"].extend(related_industry_news(stock, industry_items or []))
        stock["industryNewsStatus"] = "not_connected" if industry_items is None else "provided_candidates"
        classify_stock(stock)
    complete_count = sum(all(value["status"] == "ok" for value in stock["quality"].values()) for stock in stocks)
    dates = sorted({value["date"] for stock in stocks for value in stock["quality"].values() if value["date"]})
    failed_datasets = [kind for kind in DATASETS if not any(stock["latest"][kind] for stock in stocks)]
    payload = {
        "schemaVersion": 3,
        "generatedAt": now.isoformat(timespec="seconds"),
        "calendar": calendar,
        "summary": {"stockCount": len(stocks), "completeCount": complete_count, "asOf": target, "oldestDataDate": dates[0] if dates else None, "latestDataDate": dates[-1] if dates else None, "averageScore": None, "exitCount": 0, "reduceCount": 0, "manualCheckCount": sum(stock["manualCheck"] == "是" for stock in stocks), "positionAmountsPublished": False},
        "reportStatus": "failed" if failed_datasets else "complete" if complete_count == 22 and not calendar["issues"] and target in calendar["dates"] else "partial",
        "failedDatasets": failed_datasets,
        "policyNews": news,
        "marketMonitor": market_monitor(news),
        "riskModelVersion": 1,
        "stocks": stocks,
        "disclaimer": "僅供公開市場資料追蹤，警報須人工核對；不自動下單。",
    }
    assert_public(payload, client.token)
    payload["summary"]["qualityReviewCount"] = sum(stock["qualityReviewRequired"] for stock in stocks)
    payload["summary"]["riskCounts"] = {level: sum(stock["riskLevel"] == level for stock in stocks) for level in ("高", "中", "一般觀察")}
    return payload


def markdown_report(payload):
    lines = ["# 台股 22 檔日報", "", f"產生時間：{payload['generatedAt']}", f"目標交易日：{payload['summary']['asOf']}；狀態：{payload['reportStatus']}", "", "成交量與法人買賣超：股；融資融券：張；價格：元。各欄獨立日期，正值為買超／增加。", "", "| 代號 | 名稱 | 價量日期 | 收盤 | 成交量 | 法人日期 | 外資 | 投信 | 自營商 | 資券日期 | 融資 | 日變化 | 融券 | 日變化 | 品質 |", "|---|---|---|---:|---:|---|---:|---:|---:|---|---:|---:|---:|---:|---|"]
    def cell(value):
        return "缺資料" if value is None else str(value).replace("|", "／").replace("\n", " ")
    for stock in payload["stocks"]:
        price, institutional, margin = (stock["latest"][kind] or {} for kind in DATASETS)
        values = [stock["code"], stock["name"], price.get("date"), price.get("close"), price.get("volume"), institutional.get("date"), institutional.get("foreign"), institutional.get("trust"), institutional.get("dealer"), margin.get("date"), margin.get("margin"), margin.get("marginChange"), margin.get("short"), margin.get("shortChange"), stock["dataQualityStatus"]]
        lines.append("| " + " | ".join(cell(value) for value in values) + " |")
    lines.extend(["", "來源：FinMind HTTP API，資料集 " + "、".join(DATASETS.values()), "", "## 警報及品質", ""])
    for stock in payload["stocks"]:
        lines.append(f"### {stock['code']} {stock['name']}")
        lines.append(f"風險級別：{stock.get('riskLevel', '未評估')}；人工確認：{stock['manualCheck']}；資料限制：{stock.get('riskAssessment', '未評估')}")
        lines.append("人工確認原因：" + "、".join(stock.get("manualCheckReasons", [])))
        for kind, quality in stock["quality"].items():
            check = quality["officialCheck"]
            lines.append(f"- {kind}：{quality['status']}，日期 {quality['date']}，來源 {quality['source']}；官方核對 {check['status']}（官方日期 {check['officialDate']}；{check['source']}）；{check.get('reason', '')}；缺漏 {quality['missingDates']}；異常 {quality['issues']}")
        lines.extend("- " + cell(alert["date"]) + " " + cell(alert["message"]) + "（" + cell(alert["source"]) + "）" for alert in stock["alerts"])
        lines.append("- 未能計算的規則：" + ("、".join(stock["unavailableRules"]) or "無"))
        lines.append("")
    monitor = payload.get("marketMonitor") or market_monitor(payload["policyNews"])
    lines.extend(["## 市場政策監控", "", monitor["notice"], "八大官股：無權限（Sponsor 待接入）；不提供推估買賣超。", ""])
    for feed in monitor["sources"]:
        lines.append(f"- {feed['source']}：{feed['status']}；{feed['url']}")
    lines.extend(f"- {item['publishedDate'] or '發布日待確認'}：{cell(item['title'])} {item['url']}" for item in monitor["items"])
    return "\n".join(lines) + "\n"


def write_outputs(payload, destination, token=""):
    assert_public(payload, token)
    destination.mkdir(parents=True, exist_ok=True)
    quality = {"generatedAt": payload["generatedAt"], "reportStatus": payload["reportStatus"], "failedDatasets": payload.get("failedDatasets", []), "calendar": payload["calendar"], "stocks": [{"code": stock["code"], "quality": stock["quality"], "unavailableRules": stock["unavailableRules"]} for stock in payload["stocks"]], "policySources": [{"source": feed["source"], "status": feed["status"]} for feed in payload["policyNews"]]}
    outputs = {"stocks.json": json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2), "quality.json": json.dumps(quality, ensure_ascii=False, allow_nan=False, indent=2), "daily-report.md": markdown_report(payload), "stocks-data.js": "window.STOCK_DASHBOARD_DATA = null;\n"}
    for name, content in outputs.items():
        if token and token in content:
            raise ValueError("secret_rejected")
        temporary = destination / (name + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(destination / name)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=date.fromisoformat)
    parser.add_argument("--output", type=Path, default=ROOT / "docs" / "data")
    args = parser.parse_args()
    token = os.environ.get("FINMIND_TOKEN", "").strip()
    if not token:
        print("FINMIND_TOKEN 未設定；請設定 GitHub Actions Secret。未產生替代分數或覆寫日報。")
        return 2
    try:
        watchlist = load_watchlist(ROOT / "config" / "watchlist_public.json")
        now = datetime.now(TAIPEI)
        if args.date:
            now = datetime.combine(args.date, now.time(), TAIPEI)
        payload = collect(HttpClient(token), watchlist, now)
        write_outputs(payload, args.output, token)
        print(f"日報 {payload['reportStatus']}：22 檔；完整 {payload['summary']['completeCount']} 檔。")
        return 1 if payload["reportStatus"] == "failed" else 0
    except Exception:
        print("收集失敗；未輸出例外原文，以避免憑證或私人資料進入日誌。請執行離線測試並檢查資料品質。")
        return 1
