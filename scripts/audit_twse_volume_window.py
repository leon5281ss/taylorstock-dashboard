"""Audit coverage of a TWSE 60-session volume comparison window."""
import argparse
from collections import Counter
from datetime import date, timedelta
import json
from hashlib import sha256
import re
from pathlib import Path

from backfill_research_history import saved_official_closures, verified_extraordinary_closures

from audit_volume_scope import URLS, url_for

WINDOW = 60


def read_evidence(path, expected_hash):
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != expected_hash:
        raise ValueError("comparison_report_sha256_mismatch")
    return json.loads(raw)


def valid_volume(value):
    return type(value) is int and value >= 0


def audit(baseline, end, closures, calendar_year):
    dates = []
    cursor = date.fromisoformat(end)
    while len(dates) < WINDOW:
        if cursor.year != calendar_year:
            raise ValueError("official_calendar_year_unavailable")
        day = cursor.isoformat()
        if cursor.weekday() < 5 and day not in closures:
            dates.append(day)
        cursor -= timedelta(days=1)
    dates.reverse()
    observations = {}
    comparisons = baseline.get("comparisons") if isinstance(baseline, dict) else None
    if not isinstance(comparisons, list):
        raise ValueError("invalid_comparison_report")
    for report in comparisons:
        if not isinstance(report, dict) or not isinstance(report.get("date"), str):
            raise ValueError("invalid_comparison_entry")
        if date.fromisoformat(report["date"]).isoformat() != report["date"]:
            raise ValueError("invalid_comparison_date")
        if report.get("market") not in ("TWSE", "TPEX"):
            raise ValueError("invalid_comparison_market")
        day = report["date"]
        if report["market"] != "TWSE" or day not in dates:
            continue
        if day in observations:
            raise ValueError("duplicate_comparison_day")
        if (report.get("dailySource") != URLS["TWSE"]
                or report.get("historicalSource") != url_for("TWSE", day)
                or report.get("unit") != "shares"):
            raise ValueError("comparison_source_or_unit_mismatch")
        rows = report.get("stocks")
        if not isinstance(rows, list) or any(
            not isinstance(row, dict) or not isinstance(row.get("code"), str)
            or not re.fullmatch(r"[0-9]{4}", row["code"])
            or row.get("presence") not in ("both", "daily_only", "historical_only")
            or not {"dailyShares", "historicalShares"} <= row.keys()
            for row in rows
        ):
            raise ValueError("invalid_comparison_stock")
        observations[day] = {row["code"]: row for row in rows}
        if len(observations[day]) != len(rows):
            raise ValueError("duplicate_comparison_stock")
    numeric_dates = sorted(day for day, rows in observations.items() if any(
        row["presence"] == "both" and valid_volume(row["dailyShares"])
        and valid_volume(row["historicalShares"])
        and not (row.get("invalidDailyVolume") or row.get("invalidHistoricalVolume"))
        for row in rows.values()
    ))
    codes = sorted({code for rows in observations.values() for code in rows})
    stocks, totals = [], Counter()
    for code in codes:
        status = {}
        for day in dates:
            row = observations.get(day, {}).get(code)
            if row is None:
                state = "comparison_missing"
            elif row.get("invalidDailyVolume") or row.get("invalidHistoricalVolume"):
                state = "invalid_volume"
            elif row.get("presence") != "both":
                state = "source_quote_missing"
            elif not all(valid_volume(row[k]) for k in ("dailyShares", "historicalShares")):
                state = "invalid_volume"
            elif row["dailyShares"] == row["historicalShares"] == 0:
                state = "explicit_zero"
            elif row["dailyShares"] != row["historicalShares"]:
                state = "volume_mismatch"
            else:
                state = "numeric_match_scope_unverified"
            status[day] = state
        totals.update(status.values())
        stocks.append({"code": code, "dailyStatus": status,
                       "verifiedSuspensionDates": [], "v5v60": None})
    return {"market": "TWSE", "requiredDates": dates,
            "reportDates": sorted(observations),
            "numericComparisonDates": numeric_dates, "scopeVerifiedDates": [],
            "missingNumericComparisonDates": [day for day in dates if day not in numeric_dates],
            "missingComparisonDates": [day for day in dates if day not in observations],
            "scopeVerifiedDays": 0, "stocksWithVerifiedWindow": 0,
            "suspensionEvidenceAvailable": False,
            "statusCounts": dict(totals), "stocks": stocks,
            "tpexBlockers": ["confirm_regular_session_scope", "verify_odd_lot_and_fixed_price_units",
                             "verify_block_coverage_and_prevent_overlap"],
            "v5v60": None, "top10": None, "publishable": False}


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument("baseline", type=Path)
    cli.add_argument("end")
    cli.add_argument("output", type=Path)
    cli.add_argument("--baseline-sha256", required=True)
    args = cli.parse_args()
    closures = saved_official_closures(Path("config/official_twse_holidays_2026.json"), 2026)
    closures |= verified_extraordinary_closures(
        Path("config/verified_extraordinary_market_closures_2026.json"), 2026)
    report = audit(read_evidence(args.baseline, args.baseline_sha256), args.end, closures, 2026)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"TWSE comparison days: {len(report['numericComparisonDates'])}/{WINDOW}; "
          f"scope verified: {report['scopeVerifiedDays']}/{WINDOW}")


if __name__ == "__main__":
    main()
