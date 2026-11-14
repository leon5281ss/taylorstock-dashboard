"""Bounded, fail-closed accumulation of official historical institutional net flows.

Only requests exchange dates already independently captured in valid official
price archives. Company universe remains current, NOT historical point-in-time.
"""
import argparse
from datetime import date, datetime
import gzip
import json
from pathlib import Path
import time
from zoneinfo import ZoneInfo

from collect_market_history import compressed_snapshot
from collect_institutional_history import InstitutionalError, official_institutional_day
from market_pipeline.quant_screen import official_universe
from quant_run import fetch_csv, fetch_json, fetch_text
from research_price_coverage import CoverageError, load_snapshot


class InstitutionalBackfillError(Exception):
    pass


def plan_dates(daily_dir, price_research_dir, institutional_dir, *,
               max_successes=12, max_attempts=16):
    if not 1 <= max_successes <= 15 or not max_successes <= max_attempts <= 25:
        raise InstitutionalBackfillError("institutional_batch_limits_invalid")
    price_dates = {}
    for kind, folder in ((False, daily_dir), (True, price_research_dir)):
        for path in sorted(Path(folder).glob("*.json.gz")):
            try:
                snapshot = load_snapshot(path, historical=kind)
            except CoverageError as exc:
                raise InstitutionalBackfillError("price_calendar_source_invalid") from exc
            day = snapshot["asOf"]
            if day in price_dates:
                raise InstitutionalBackfillError("overlapping_price_calendar_date")
            price_dates[day] = snapshot["kind"]
    if not price_dates or "production_daily" not in price_dates.values():
        raise InstitutionalBackfillError("official_price_calendar_missing")
    today = datetime.now(ZoneInfo("Asia/Taipei")).date()
    if any(date.fromisoformat(d) > today for d in price_dates):
        raise InstitutionalBackfillError("future_official_price_calendar_day")
    existing = set()
    for path in sorted(Path(institutional_dir).glob("*.json.gz")):
        try:
            blob = json.loads(gzip.decompress(path.read_bytes()))
            if (blob["schemaVersion"] != 1 or
                    blob["status"] != "institutional_history_research_only" or
                    blob["asOf"] + ".json.gz" != path.name or
                    blob["sourceDateEvidence"] != {
                        "TWSE": "explicit_response_date",
                        "TPEX": "explicit_response_date"} or
                    blob["marketCounts"]["TWSE"] < 700 or
                    blob["marketCounts"]["TPEX"] < 500 or
                    blob["publishable"] is not False):
                raise InstitutionalBackfillError("existing_institutional_archive_not_verified")
            rows = blob.get("rows")
            if (not isinstance(rows, list) or
                    len(rows) != blob["marketCounts"]["TWSE"]+blob["marketCounts"]["TPEX"]):
                raise InstitutionalBackfillError("existing_institutional_rows_count_invalid")
            by_market = {"TWSE": 0, "TPEX": 0}
            observed = set()
            for row in rows:
                market, code = row.get("market"), row.get("code")
                if (market not in by_market or not isinstance(code, str)
                        or len(code) != 4 or not code.isdigit()
                        or (market, code) in observed):
                    raise InstitutionalBackfillError("existing_institutional_symbol_invalid")
                observed.add((market, code))
                by_market[market] += 1
                keys = ("foreignNet", "trustNet", "dealerNet", "totalNet",
                        "foreignDealerNetNotAddedToForeign", "dealerSelfNet", "dealerHedgeNet")
                if any(type(row.get(k)) is not int for k in keys):
                    raise InstitutionalBackfillError("existing_institutional_net_invalid")
                if (row["foreignNet"] + row["trustNet"] + row["dealerNet"] != row["totalNet"]
                        or row["dealerSelfNet"] + row["dealerHedgeNet"] != row["dealerNet"]):
                    raise InstitutionalBackfillError("existing_institutional_net_identity_invalid")
            if by_market != blob["marketCounts"]:
                raise InstitutionalBackfillError("existing_institutional_market_counts_invalid")
            existing.add(blob["asOf"])
        except (OSError, EOFError, ValueError, TypeError, KeyError, gzip.BadGzipFile) as exc:
            raise InstitutionalBackfillError("existing_institutional_archive_corrupt") from exc
    if existing - set(price_dates):
        raise InstitutionalBackfillError("orphan_institutional_date_without_official_prices")
    candidates = sorted(set(price_dates)-existing, reverse=True)
    return {"priceCalendarDates": len(price_dates),
            "existingInstitutionalDays": len(existing),
            "pending": candidates,
            "maxSuccesses": max_successes, "maxAttempts": max_attempts}


def run(daily_dir, price_research_dir, institutional_dir, *,
        fetch=fetch_text, roster_json=fetch_json, roster_csv=fetch_csv,
        sleep=time.sleep, delay=2.5, max_successes=12, max_attempts=16):
    if delay < 2.5:
        raise InstitutionalBackfillError("minimum_delay_required")
    plan = plan_dates(daily_dir, price_research_dir, institutional_dir,
                      max_successes=max_successes, max_attempts=max_attempts)
    if not plan["pending"]:
        return {"status": "all_existing_price_days_have_institutional_research",
                "newCount": 0, "new": [], "errors": [],
                "priceCalendarDates": plan["priceCalendarDates"],
                "institutionalDaysNow": plan["existingInstitutionalDays"],
                "publishable": False, "top10": None}
    universe = official_universe(roster_json, roster_csv)
    if universe.get("errors"):
        raise InstitutionalBackfillError("official_company_roster_unavailable")
    new, errors = [], []
    for day in plan["pending"]:
        if len(new) >= max_successes or len(new)+len(errors) >= max_attempts:
            break
        try:
            snapshot = official_institutional_day(
                day, company_universe=universe, fetch=fetch,
                sleep=sleep, delay=delay)
            if snapshot["asOf"] != day or snapshot["publishable"] is not False:
                raise InstitutionalBackfillError("institutional_date_or_publishable_violation")
            dest = Path(institutional_dir) / (day + ".json.gz")
            if dest.exists():
                raise InstitutionalBackfillError("concurrent_institutional_archive_exists")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(compressed_snapshot(snapshot))
            new.append({"date": day, "marketCounts": snapshot["marketCounts"]})
        except (InstitutionalError, InstitutionalBackfillError,
                OSError, ValueError, TypeError, KeyError) as exc:
            errors.append({"date": day,
                           "reason": str(exc) if isinstance(
                               exc, (InstitutionalError, InstitutionalBackfillError))
                           else "official_source_or_schema_failure"})
            if len(errors) >= 4:
                break
    return {
        "status": "partial_with_unverified_days" if errors else (
            "archived" if new else "no_new_archives"),
        "newCount": len(new), "new": new, "errors": errors,
        "institutionalDaysNow": plan["existingInstitutionalDays"] + len(new),
        "priceCalendarDates": plan["priceCalendarDates"],
        "unverifiedDates": len(errors),
        "historicalPointInTimeUniverseVerified": False,
        "fullFactorAndNetReturnBacktestReady": False,
        "publishable": False, "top10": None,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--daily-dir", type=Path, default=Path("data/market_daily"))
    p.add_argument("--price-research-dir", type=Path,
                   default=Path("data/market_backfill_pilot"))
    p.add_argument("--institutional-dir", type=Path,
                   default=Path("data/institutional_research"))
    p.add_argument("--output", type=Path, default=Path("institutional-backfill-output"))
    p.add_argument("--max-successes", type=int, default=12)
    p.add_argument("--max-attempts", type=int, default=16)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    try:
        report = run(args.daily_dir, args.price_research_dir, args.institutional_dir,
                     max_successes=args.max_successes, max_attempts=args.max_attempts)
        status = 0 if report["newCount"] or not report["errors"] else 1
        print("Institutional history backfill: " + report["status"] +
              "; new=" + str(report["newCount"]) +
              "; total=" + str(report["institutionalDaysNow"]) +
              "; official price dates=" + str(report["priceCalendarDates"]) +
              "; NO TOP10")
        for item in report["errors"]:
            print("::warning::" + item["date"] + ": " + item["reason"])
    except (InstitutionalBackfillError, CoverageError, InstitutionalError,
            OSError, ValueError, TypeError, KeyError) as exc:
        report = {"status": "failed", "reason": str(exc) if isinstance(
            exc, InstitutionalBackfillError) else "institutional_backfill_source_or_schema_error",
                  "publishable": False, "top10": None}
        status = 1
        print("Institutional history backfill safely stopped: " + report["reason"])
    (args.output / "institutional-backfill-status.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
