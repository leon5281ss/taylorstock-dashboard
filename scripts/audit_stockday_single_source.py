"""Audit whether existing STOCK_DAY captures form a consistent research window."""
import argparse
import json
from pathlib import Path

from audit_twse_volume_window import audit, read_evidence
from backfill_research_history import saved_official_closures, verified_extraordinary_closures
from collect_market_history import IngestionError
from compare_twse_stockday_volume import monthly_url, parse_month


def check(code, sessions, folder, manifest):
    months = sorted({day[:7] for day in sessions})
    observed, captures, issues, signatures = {}, [], [], set()
    for month in months:
        name = f"stockday-{code}-{month}.json"
        url = monthly_url(code, month)
        try:
            entry = manifest.get(name)
            if not isinstance(entry, dict) or entry.get("source") != url:
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
            issues.append({"month": month, "reason": str(exc)})
    missing = [day for day in sessions if observed.get(day) is None]
    schema_consistent = len(captures) == len(months) and len(signatures) == 1
    return {"code": code, "numericWindowComplete": not missing,
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
