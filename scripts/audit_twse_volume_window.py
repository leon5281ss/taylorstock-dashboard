"""Audit coverage of a TWSE 60-session volume comparison window."""
import argparse
from collections import Counter
from datetime import date, timedelta
import json
from pathlib import Path

from backfill_research_history import saved_official_closures, verified_extraordinary_closures

WINDOW = 60


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
    for report in baseline["comparisons"]:
        day = report["date"]
        if report["market"] != "TWSE" or day not in dates:
            continue
        if day in observations:
            raise ValueError("duplicate_comparison_day")
        rows = report["stocks"]
        observations[day] = {row["code"]: row for row in rows}
        if len(observations[day]) != len(rows):
            raise ValueError("duplicate_comparison_stock")
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
            "numericComparisonDates": sorted(observations),
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
    args = cli.parse_args()
    closures = saved_official_closures(Path("config/official_twse_holidays_2026.json"), 2026)
    closures |= verified_extraordinary_closures(
        Path("config/verified_extraordinary_market_closures_2026.json"), 2026)
    report = audit(json.loads(args.baseline.read_bytes()), args.end, closures, 2026)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"TWSE comparison days: {len(report['numericComparisonDates'])}/{WINDOW}; "
          f"scope verified: {report['scopeVerifiedDays']}/{WINDOW}")


if __name__ == "__main__":
    main()
