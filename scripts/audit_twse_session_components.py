"""Compare same-session TWSE component evidence without blending sources."""
import argparse
from hashlib import sha256
import json
import time
from pathlib import Path

from collect_market_history import number, roc_to_iso, IngestionError
from reconcile_volume_categories import fetch

REPORTS = {
    "TWTC7U": ("盤中零股交易行情單", "成交股數", "shares", "afterTrading"),
    "TWT53U": ("盤後零股交易行情單", "成交股數", "shares", "afterTrading"),
    "BFT41U": ("盤後定價交易", "成交數量", None, "afterTrading"),
    "BFIAUU": ("鉅額交易日成交資訊", "成交股數", "shares", "blockTrade"),
}


def source_url(report, day):
    return ("https://www.twse.com.tw/rwd/zh/" + REPORTS[report][3] + "/" + report
            + "?date=" + day.replace("-", "") + "&response=json")


def parse(raw, report, day):
    title, field, unit, _ = REPORTS[report]
    data = json.loads(raw)
    if data["stat"] != "OK" or roc_to_iso(data["date"]) != day or title not in data["title"]:
        raise ValueError("source_date_or_title_mismatch")
    fields = data["fields"]
    if fields.count(field) != 1 or fields.count("證券代號") != 1:
        raise ValueError("unexpected_quantity_schema")
    qi, ci = fields.index(field), fields.index("證券代號")
    values = {}
    for row in data["data"]:
        if not isinstance(row, list) or len(row) != len(fields):
            raise ValueError("unexpected_row_schema")
        code = str(row[ci]).strip()
        if code in values:
            raise ValueError("duplicate_symbol_or_transaction_scope")
        amount = number(row[qi], integer=True)
        values[code] = amount if amount is not None and amount >= 0 else None
    return {"fields": fields, "unit": unit, "volumeField": field, "values": values}


def audit(baseline, folder, *, download=False):
    samples = [r for stock in baseline["stocks"] for r in stock["comparisons"]
               if r["archiveSource"].startswith("https://openapi.twse.com.tw/")]
    captures, rows = [], []
    for day in sorted({r["date"] for r in samples}):
        components = {}
        for report in REPORTS:
            name = f"twse-{report}-{day.replace('-', '')}.json"
            source = {"report": report, "date": day, "url": source_url(report, day),
                      "file": name, "captureMode": "local_replay"}
            try:
                path = folder / name
                if download and not path.exists():
                    time.sleep(2.5)
                    path.write_bytes(fetch(source["url"]))
                    source["captureMode"] = "direct_https"
                raw = path.read_bytes()
                source["sha256"] = sha256(raw).hexdigest()
                parsed = parse(raw, report, day)
                components[report] = parsed["values"]
                source.update({k: parsed[k] for k in ("fields", "unit", "volumeField")})
            except (OSError, ValueError, TypeError, KeyError, IngestionError) as exc:
                source["error"] = str(exc)
            captures.append(source)
        for sample in samples:
            if sample["date"] != day:
                continue
            code = sample["code"]
            quantities = {report: components.get(report, {}).get(code) for report in REPORTS}
            rows.append({"date": day, "code": code, "stockDayShares": sample["stockDayShares"],
                         "openApiShares": sample["archiveShares"], "reportedComponents": quantities,
                         "missingComponents": [r for r, n in quantities.items() if n is None],
                         "scopeVerified": False})
    return {"captures": captures, "comparisons": rows, "scopeVerifiedStocks": 0,
            "v5v60": None, "top10": None, "publishable": False,
            "tpexUnverifiedDifferences": 2533}


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument("baseline", type=Path)
    cli.add_argument("captures", type=Path)
    cli.add_argument("--download", action="store_true")
    args = cli.parse_args()
    report = audit(json.loads(args.baseline.read_bytes()), args.captures, download=args.download)
    (args.captures / "twse-session-components.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Sample rows: {len(report['comparisons'])}; parsed reports: "
          f"{sum('error' not in r for r in report['captures'])}/{len(report['captures'])}")


if __name__ == "__main__":
    main()
