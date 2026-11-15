"""Audit whether existing STOCK_DAY captures form a consistent research window."""
import argparse
from datetime import date
import json
from pathlib import Path

from audit_twse_volume_window import audit, read_evidence
from backfill_research_history import saved_official_closures, verified_extraordinary_closures
from collect_market_history import IngestionError
from compare_twse_stockday_volume import monthly_url, parse_month


def check(code, sessions, folder, manifest):
    if not sessions or sessions != sorted(set(sessions)) or any(
        date.fromisoformat(day).isoformat() != day or date.fromisoformat(day).weekday() >= 5
        for day in sessions
    ):
        raise ValueError("invalid_trading_sessions")
    months = sorted({day[:7] for day in sessions})
    observed, captures, issues, signatures = {}, [], [], set()
    for month in months:
        name = f"stockday-{code}-{month}.json"
        url = monthly_url(code, month)
        try:
            entry = manifest.get(name)
            if not isinstance(entry, dict):
                raise ValueError("stockday_manifest_entry_missing")
            if entry.get("source") != url:
                raise ValueError("stockday_manifest_source_mismatch")
            path = folder / name
            payload = read_evidence(path, entry.get("sha256"))
            fields, values = parse_month(json.dumps(payload), code, month)
            observed.update(values)
            signatures.add(tuple(fields))
            captures.append({"month": month, "url": url, "sha256": entry["sha256"],
                             "responseDate": payload["date"], "fields": fields,
                             "sourceVersion": None, "tradeScope": None})
        except (OSError, ValueError, TypeError, KeyError, IngestionError) as exc:
            if isinstance(exc, FileNotFoundError) or str(exc) == "stockday_manifest_entry_missing":
                category = "raw_source_missing"
            elif str(exc) in ("stockday_manifest_source_mismatch", "comparison_report_sha256_mismatch"):
                category = "raw_source_or_sha256_mismatch"
            else:
                category = "raw_source_invalid"
            issues.append({"month": month, "category": category, "reason": str(exc)})
    missing = [day for day in sessions if observed.get(day) is None]
    schema_consistent = len(captures) == len(months) and len(signatures) == 1
    blockers = sorted({issue["category"] for issue in issues})
    numeric_complete = len(sessions) == 60 and not missing
    if not numeric_complete:
        blockers.append("numeric_window_incomplete")
    if len(signatures) > 1:
        blockers.append("cross_month_schema_mismatch")
    blockers.append("historical_scope_unverified")
    return {"code": code, "numericWindowComplete": numeric_complete,
            "blockers": blockers,
            "crossMonthSchemaConsistent": schema_consistent, "captures": captures,
            "missingOrInvalidDates": missing, "captureErrors": issues,
            "window": [{"date": day, "shares": observed.get(day)} for day in sessions],
            "historicalScopeVerified": False, "v5v60": None}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("captures", type=Path)
    parser.add_argument("--codes", nargs="+", required=True)
    parser.add_argument("--end", default="2026-11-13")
    args = parser.parse_args()
    year = int(args.end[:4])
    closures = saved_official_closures(Path(f"config/official_twse_holidays_{year}.json"), year)
    closures |= verified_extraordinary_closures(
        Path(f"config/verified_extraordinary_market_closures_{year}.json"), year)
    sessions = audit({"comparisons": []}, args.end, closures, year)["requiredDates"]
    manifest = json.loads((args.captures / "twse-stockday-manifest.json").read_bytes())
    stocks = [check(code, sessions, args.captures, manifest) for code in sorted(set(args.codes))]
    report = {"stocks": stocks, "scopeVerifiedStocks": 0,
              "tpexUnverifiedDifferences": 2533, "v5v60": None,
              "top10": None, "publishable": False}
    (args.captures / "stockday-single-source-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return int(any(not s["numericWindowComplete"] or not s["crossMonthSchemaConsistent"]
                   for s in stocks))


if __name__ == "__main__":
    raise SystemExit(main())
