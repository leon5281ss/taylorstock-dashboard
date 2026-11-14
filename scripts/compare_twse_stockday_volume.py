"""Compare official TWSE monthly stock reports with existing dated snapshots."""
import argparse
from datetime import date
import gzip
from hashlib import sha256
import json
from pathlib import Path
import re
import time
from urllib.parse import urlencode

from audit_twse_volume_window import audit, valid_volume
from backfill_market_pilot import url_for
from backfill_research_history import saved_official_closures, verified_extraordinary_closures
from collect_market_history import IngestionError, URLS, number, roc_to_iso
from reconcile_volume_categories import fetch
from research_price_coverage import CoverageError, load_snapshot

ROOT = "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY"


def monthly_url(code, month):
    if not re.fullmatch(r"[1-9][0-9]{3}", code):
        raise ValueError("invalid_stock_code")
    stamp = date.fromisoformat(month + "-01")
    return ROOT + "?" + urlencode(
        {"date": stamp.strftime("%Y%m%d"), "stockNo": code, "response": "json"})


def parse_month(raw, code, month):
    data = json.loads(raw)
    year, mm = map(int, month.split("-"))
    title = rf"^{year - 1911}年{mm:02d}月\s+{code}\s"
    if (data["stat"] != "OK" or roc_to_iso(data["date"]) != month + "-01"
            or not re.match(title, data["title"])):
        raise ValueError("monthly_identity_mismatch")
    fields = data["fields"]
    if fields.count("日期") != 1 or fields.count("成交股數") != 1:
        raise ValueError("monthly_volume_unit_unverified")
    dates, values = fields.index("日期"), fields.index("成交股數")
    output = {}
    for row in data["data"]:
        if not isinstance(row, list) or len(row) != len(fields):
            raise ValueError("invalid_monthly_row")
        day = roc_to_iso(row[dates])
        if not day.startswith(month + "-") or day in output:
            raise ValueError("unexpected_or_duplicate_session")
        volume = number(row[values], integer=True)
        output[day] = volume if valid_volume(volume) else None
    return fields, output


def window_status(rows):
    missing = [row["date"] for row in rows
               if not all(valid_volume(row[key]) for key in ("archiveShares", "stockDayShares"))]
    mismatches = [row["date"] for row in rows if row["status"] == "different"]
    complete = len(rows) == 60 and len({row["date"] for row in rows}) == 60 and not missing
    return {"numericWindowComplete": complete,
            "numericWindowAllMatch": complete and not mismatches,
            "scopeVerifiedWindowComplete": False,
            "missingDates": missing, "mismatchDates": mismatches}


def exit_status(report):
    if not report["dataAcquisitionComplete"]:
        return 1
    return 0 if report["numericComparisonPassed"] else 2


def compare(dates, codes, daily_dir, historical_dir, captures, *, download=False):
    sources, errors, monthly, archives = [], [], {}, {}
    manifest_path = captures / "twse-stockday-manifest.json"
    manifest = json.loads(manifest_path.read_bytes()) if manifest_path.exists() else {}
    for code in codes:
        for month in sorted({day[:7] for day in dates}):
            url = monthly_url(code, month)
            path = captures / f"stockday-{code}-{month}.json"
            try:
                if download and not path.exists():
                    time.sleep(2.5)
                    raw = fetch(url)
                    path.write_bytes(raw)
                    manifest[path.name] = {"source": url, "sha256": sha256(raw).hexdigest()}
                    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
                raw = path.read_bytes()
                digest = sha256(raw).hexdigest()
                if manifest.get(path.name) != {"source": url, "sha256": digest}:
                    raise ValueError("capture_manifest_mismatch")
                fields, monthly[code, month] = parse_month(raw, code, month)
                sources.append({"code": code, "month": month, "source": url,
                                "rawFile": path.name, "sha256": digest, "fields": fields,
                                "unit": "shares", "scope": "stock_day_scope_unverified"})
            except (OSError, ValueError, KeyError, TypeError, IngestionError) as exc:
                errors.append({"source": url, "reason": str(exc)})
    for day in dates:
        live = daily_dir / (day + ".json.gz")
        historical = not live.exists()
        path = historical_dir / live.name if historical else live
        source = url_for("TWSE", day) if historical else URLS["TWSE"]
        try:
            snapshot = load_snapshot(path, historical=historical)
            raw = path.read_bytes()
            data = json.loads(gzip.decompress(raw))
            if (snapshot["asOf"] != day or data["sources"]["TWSE"] != source or historical
                    and snapshot["sourceDateEvidence"]["TWSE"] != "explicit_response_date"):
                raise ValueError("archive_source_or_date_mismatch")
            archives[day] = {r["code"]: r["volume"] for r in data["stocks"] if r["market"] == "TWSE"}
            sources.append({"date": day, "source": source, "rawFile": path.name,
                            "sha256": sha256(raw).hexdigest(), "unit": "shares",
                            "scope": "dated_market_report" if historical else "openapi_scope_unverified"})
        except (OSError, ValueError, KeyError, CoverageError) as exc:
            errors.append({"date": day, "source": source, "reason": str(exc)})
    stocks, compared = [], set()
    for code in codes:
        rows = []
        for day in dates:
            a = archives.get(day, {}).get(code)
            b = monthly.get((code, day[:7]), {}).get(day)
            if a is None or b is None:
                state = "missing_or_invalid_evidence"
            else:
                compared.add(day)
                state = "explicit_zero" if a == b == 0 else "equal" if a == b else "different"
            rows.append({"date": day, "code": code, "archiveShares": a,
                         "stockDayShares": b, "stockDaySource": monthly_url(code, day[:7]),
                         "archiveSource": URLS["TWSE"] if (daily_dir / (day + ".json.gz")).exists()
                         else url_for("TWSE", day), "status": state})
        stocks.append({"code": code, **window_status(rows),
                       "scopeUnverifiedDates": dates, "comparisons": rows})
    return {"dataAcquisitionComplete": bool(stocks) and not errors and all(
                stock["numericWindowComplete"] for stock in stocks),
            "numericComparisonPassed": bool(stocks) and all(
                stock["numericWindowAllMatch"] for stock in stocks),
            "scopeVerificationPassed": False,
            "requiredDates": dates, "numericComparisonDates": sorted(compared),
            "missingComparisonDates": sorted(set(dates) - compared), "sources": sources,
            "errors": errors, "stocks": stocks, "scopeVerifiedDays": 0,
            "stocksWithVerifiedWindow": 0, "tpexUnverifiedDifferences": 2533,
            "v5v60": None, "top10": None, "publishable": False}


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument("captures", type=Path)
    cli.add_argument("--end", default="2026-11-13")
    cli.add_argument("--codes", nargs="+", required=True)
    cli.add_argument("--download", action="store_true")
    args = cli.parse_args()
    args.captures.mkdir(parents=True, exist_ok=True)
    year = date.fromisoformat(args.end).year
    closures = saved_official_closures(Path(f"config/official_twse_holidays_{year}.json"), year)
    closures |= verified_extraordinary_closures(
        Path(f"config/verified_extraordinary_market_closures_{year}.json"), year)
    dates = audit({"comparisons": []}, args.end, closures, year)["requiredDates"]
    report = compare(dates, sorted(set(args.codes)), Path("data/market_daily"),
                     Path("data/market_backfill_pilot"), args.captures, download=args.download)
    (args.captures / "stockday-volume-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"TWSE numeric comparisons: {len(report['numericComparisonDates'])}/{len(dates)}")
    for key in ("dataAcquisitionComplete", "numericComparisonPassed", "scopeVerificationPassed"):
        print(f"{key}={str(report[key]).lower()}")
    return exit_status(report)


if __name__ == "__main__":
    raise SystemExit(main())
