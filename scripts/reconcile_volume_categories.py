"""Archive TPEx classification responses and compare research-only volumes."""
import argparse
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import time
from urllib.parse import urlencode
from urllib.request import urlopen

from collect_market_history import IngestionError, number, roc_to_iso

REPORTS = {
    "oddQuote": ("afterTrading/oddQuote", "成交股數", "shares"),
    "odd": ("afterTrading/odd", "成交股數", "shares"),
    "fixPricing": ("afterTrading/fixPricing", "成交張數", "lots"),
    "quote": ("blockTrade/quote", "成交股數", "shares"),
}


def source_url(category, day):
    params = {"date": date.fromisoformat(day).strftime("%Y/%m/%d"), "response": "json"}
    if category == "odd":
        params["type"] = "Daily"
    return "https://www.tpex.org.tw/www/zh-tw/" + REPORTS[category][0] + "?" + urlencode(params)


def parse(category, day, raw):
    payload = json.loads(raw)
    if payload["stat"].lower() != "ok" or roc_to_iso(payload["date"]) != day:
        raise ValueError("source_status_or_date_mismatch")
    tables = payload["tables"]
    _, quantity, unit = REPORTS[category]
    matching = [t for t in tables if quantity in t["fields"]
                and any(c in t["fields"] for c in ("代號", "證券代號"))]
    if len(matching) != 1:
        raise ValueError("unverified_table_scope_or_unit")
    table = matching[0]
    fields = table["fields"]
    code_field = "代號" if "代號" in fields else "證券代號"
    if fields.count(code_field) != 1 or fields.count(quantity) != 1:
        raise ValueError("ambiguous_volume_columns")
    code_index, volume_index = fields.index(code_field), fields.index(quantity)
    if table.get("totalCount", len(table["data"])) != len(table["data"]):
        raise ValueError("incomplete_volume_table")
    values = {}
    transactions = set()
    for row in table["data"]:
        if not isinstance(row, list) or len(row) != len(fields):
            raise ValueError("invalid_volume_row")
        code = str(row[code_index]).strip()
        if category == "quote":
            if tuple(row) in transactions:
                raise ValueError("duplicate_block_transaction")
            transactions.add(tuple(row))
        elif code in values:
            raise ValueError("duplicate_volume_code")
        amount = number(row[volume_index], integer=True)
        valid = amount is not None and amount >= 0
        previous = values.get(code, 0)
        values[code] = previous + amount if valid and previous is not None else None
    return {"responseDate": day, "fields": fields, "unit": unit, "values": values}


def fetch(url):
    with urlopen(url, timeout=20) as response:
        if response.geturl() != url:
            raise ValueError("unexpected_response_url")
        return response.read()


def audit(baseline, folder, *, reuse=False):
    days = [item for item in baseline["comparisons"] if item["market"] == "TPEX"]
    sources, results = [], []
    for item in days:
        day = item["date"]
        reports = {}
        for category in REPORTS:
            url = source_url(category, day)
            path = folder / f"{category}-{day}.json"
            record = {"category": category, "source": url, "requestedDate": day,
                      "responseDate": None, "fields": None, "unit": None,
                      "captureMode": "replayed_raw" if reuse else "direct_https"}
            try:
                if reuse:
                    raw = path.read_bytes()
                else:
                    time.sleep(2.5)
                    raw = fetch(url)
                    path.write_bytes(raw)
                record.update(rawFile=path.name, sha256=sha256(raw).hexdigest())
                data = parse(category, day, raw)
                reports[category] = data["values"]
                record.update({k: data[k] for k in ("responseDate", "fields", "unit")})
                record["rows"] = len(data["values"])
            except (OSError, ValueError, KeyError, TypeError, AttributeError, IngestionError) as exc:
                record["error"] = str(exc)
            sources.append(record)
        for stock in item["stocks"]:
            if stock["status"] != "different":
                continue
            code = stock["code"]
            values = {category: reports.get(category, {}).get(code) for category in REPORTS}
            difference = stock["dailyShares"] - stock["historicalShares"]
            odd = [values["oddQuote"], values["odd"]]
            residual = difference - sum(odd) if None not in odd else None
            results.append({"date": day, "code": code, "differenceShares": difference,
                            "rawCategoryQuantities": values, "oddLotResidualShares": residual,
                            "missingCategories": [k for k, v in values.items() if v is None],
                            "scopeOverlapUnresolved": True, "fullyReconciled": False})
    return {"sources": sources, "stocks": results, "summary": {
                "fullyReconciled": 0, "unreconciled": len(results),
                "missingCategory": sum(bool(r["missingCategories"]) for r in results),
                "scopeOverlapUnresolved": len(results), "confirmedScopeOverlap": 0,
                "oddLotArithmeticMatch": sum(r["oddLotResidualShares"] == 0 for r in results),
                "oddLotResidualUnavailable": sum(r["oddLotResidualShares"] is None for r in results)},
            "twseVerification": {
                "requiredConsecutiveTradingDays": 60,
                "sampledDates": sorted({r["date"] for r in baseline["comparisons"]
                                        if r["market"] == "TWSE"}),
                "scopeVerifiedDays": 0,
                "nextChecks": ["align_official_calendar_and_same_day_sources",
                               "verify_units_and_session_coverage_per_source",
                               "audit_symbol_gaps_and_scope_drift"]},
            "v5v60": None, "top10": None, "publishable": False}


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument("baseline", type=Path)
    cli.add_argument("output", type=Path)
    cli.add_argument("--reuse-raw", action="store_true")
    args = cli.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    baseline = json.loads(args.baseline.read_bytes())
    report = audit(baseline, args.output, reuse=args.reuse_raw)
    (args.output / "classification-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(report["summary"])


if __name__ == "__main__":
    main()
