"""Bounded auto-backfill of official historical quote research, without mixing volumes.

This only writes validated dated-source snapshots into the existing research
archive. The output must never be used directly for trading, Top10 or claims of
a survivorship-bias-free backtest.
"""
import argparse
from datetime import date, timedelta
import json
from pathlib import Path
import time

from backfill_market_pilot import PilotError, combine, url_for
from collect_market_history import IngestionError, compressed_snapshot, roc_to_iso
from market_pipeline.quant_screen import official_universe
from quant_run import fetch_csv, fetch_json, fetch_text


class BackfillError(Exception):
    pass


HOLIDAY_URL = "https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule"


def scheduled_market_closures(payload, year):
    # The official table lists first/last trading days as well as holidays.
    if not isinstance(payload, list) or len(payload) < 8:
        raise BackfillError("official_holiday_calendar_invalid")
    closed = set()
    seen_year = 0
    for item in payload:
        if not isinstance(item, dict):
            raise BackfillError("official_holiday_row_invalid")
        try:
            day = date.fromisoformat(roc_to_iso(item["Date"]))
        except (IngestionError, ValueError, KeyError, TypeError) as exc:
            raise BackfillError("official_holiday_date_invalid") from exc
        if day.year != year:
            continue
        seen_year += 1
        name, detail = str(item.get("Name", "")), str(item.get("Description", ""))
        if "開始交易" in name or "最後交易" in name:
            continue
        if day.weekday() < 5 and ("放假" in detail or "補假" in detail or "無交易" in name):
            closed.add(day.isoformat())
    if seen_year < 8:
        raise BackfillError("official_holiday_calendar_year_unavailable")
    return closed


def archive_plan(daily_dir, research_dir, *, lookback_days=220,
                 max_successes=20, max_attempts=30, official_closed_dates=()):
    """Newest first, explicit cap, never rewrite verified daily or pilot snapshots."""
    if not 180 <= lookback_days <= 300:
        raise BackfillError("lookback_out_of_safe_range")
    if not 1 <= max_successes <= 25 or not max_successes <= max_attempts <= 40:
        raise BackfillError("batch_limits_out_of_safe_range")
    daily_files = sorted(Path(daily_dir).glob("*.json.gz"))
    if not daily_files:
        raise BackfillError("daily_archive_is_missing")
    try:
        first_day = date.fromisoformat(daily_files[0].name[:-8])
    except ValueError as exc:
        raise BackfillError("bad_daily_archive_filename") from exc
    existing = {p.stem.replace(".json", "") for p in Path(research_dir).glob("*.json.gz")}
    # Older-than-live dates only. The latest OpenAPI snapshots never get modified.
    candidates = [first_day - timedelta(days=i)
                  for i in range(1, lookback_days + 1)]
    pending = [d.isoformat() for d in candidates
               if (d.weekday() < 5 and d.isoformat() not in existing
                   and d.isoformat() not in official_closed_dates)]
    return {"firstDaily": first_day.isoformat(), "researchExisting": len(existing),
            "candidates": pending, "candidateCount": len(pending),
            "maxSuccesses": max_successes, "maxAttempts": max_attempts,
            "officialScheduledClosuresSkipped": sorted(set(official_closed_dates))}


def run_batch(daily_dir, research_dir, *,
              fetch=fetch_text, roster_fetch_json=fetch_json,
              roster_fetch_csv=fetch_csv, holiday_fetch=None,
              sleep=time.sleep, delay=2.5,
              lookback_days=220, max_successes=20, max_attempts=30):
    if delay < 2.5:
        raise BackfillError("minimum_delay_2_5_seconds_required")
    plan = archive_plan(daily_dir, research_dir, lookback_days=lookback_days,
                        max_successes=max_successes, max_attempts=max_attempts)
    calendar_status = "not_checked"
    calendar_error = None
    if holiday_fetch is not None:
        try:
            closed = scheduled_market_closures(
                holiday_fetch(HOLIDAY_URL), year=int(plan["firstDaily"][:4]))
            plan = archive_plan(daily_dir, research_dir, lookback_days=lookback_days,
                                max_successes=max_successes, max_attempts=max_attempts,
                                official_closed_dates=closed)
            calendar_status = "official_year_verified"
        except (BackfillError, ValueError, TypeError, KeyError, OSError) as exc:
            calendar_status = "unavailable_not_assumed_open"
            calendar_error = str(exc) if isinstance(exc, BackfillError) else "holiday_source_or_schema_error"
    if not plan["candidates"]:
        return {"status": "no_candidates", "new": [], "errors": [],
                "existingResearchDays": plan["researchExisting"], "newCount": 0,
                "holidayCalendarStatus": calendar_status,
                "officialScheduledClosuresSkipped": plan["officialScheduledClosuresSkipped"]}
    universe = official_universe(roster_fetch_json, roster_fetch_csv)
    if universe.get("errors"):
        raise BackfillError("official_roster_unavailable")
    new = []
    errors = []
    for day in plan["candidates"]:
        if len(new) >= max_successes or len(new) + len(errors) >= max_attempts:
            break
        try:
            responses = {}
            for market in ("TWSE", "TPEX"):
                sleep(delay)
                source = fetch(url_for(market, day))
                responses[market] = json.loads(source)
            snapshot = combine(day, universe, responses)
            if snapshot["asOf"] != day:
                raise BackfillError("response_day_invariant_failed")
            dest = Path(research_dir) / (day + ".json.gz")
            if dest.exists():
                raise BackfillError("race_condition_existing_archive")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(compressed_snapshot(snapshot))
            new.append({"date": day,
                        "counts": snapshot["marketCounts"],
                        "dateEvidence": snapshot["sourceDateEvidence"],
                        "volumeScopes": snapshot["volumeScopes"]})
        except (PilotError, BackfillError, ValueError, TypeError, OSError, KeyError) as exc:
            # Do not convert unknown schemas, exchange holidays, or service
            # failures into valid trading-day observations.
            errors.append({"date": day, "reason": str(exc) if isinstance(
                exc, (PilotError, BackfillError)) else "source_or_network_error"})
            if len(errors) >= 8:
                break
    total = plan["researchExisting"] + len(new)
    return {"status": ("partial_with_unverified_days" if errors else
                       "archived" if new else "no_new_archives"),
            "firstDaily": plan["firstDaily"],
            "new": new, "newCount": len(new),
            "errors": errors, "unverifiedDays": len(errors),
            "existingResearchDays": plan["researchExisting"],
            "researchDaysNow": total,
            "remainingWeekdayCandidatesAtStart": plan["candidateCount"],
            "holidayCalendarStatus": calendar_status,
            "holidayCalendarError": calendar_error,
            "officialScheduledClosuresSkipped": plan["officialScheduledClosuresSkipped"],
            "historicalPointInTimeUniverseAvailable": False,
            "volumeScopesCompatibleForDirectMerge": False,
            "productionDataModified": False,
            "top10": None, "publishable": False,
            "nextAction": "keep_research_separate_until_pit_and_corporate_actions_checked"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--daily-dir", type=Path, default=Path("data/market_daily"))
    parser.add_argument("--research-dir", type=Path, default=Path("data/market_backfill_pilot"))
    parser.add_argument("--output", type=Path, default=Path("research-backfill-output"))
    parser.add_argument("--lookback-days", type=int, default=220)
    parser.add_argument("--max-successes", type=int, default=20)
    parser.add_argument("--max-attempts", type=int, default=30)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    try:
        report = run_batch(args.daily_dir, args.research_dir,
                           holiday_fetch=fetch_json,
                           lookback_days=args.lookback_days,
                           max_successes=args.max_successes,
                           max_attempts=args.max_attempts)
        result = 0
        print("Backfill research: " + report["status"] +
              "; new=" + str(report["newCount"]) +
              "; total-research=" + str(report.get("researchDaysNow", report["existingResearchDays"])) +
              "; unverified=" + str(report.get("unverifiedDays", 0)) +
              "; NO TOP10/NO PROD MERGE")
        for failure in report.get("errors", [])[:8]:
            print("::warning::" + failure["date"] + ": " + failure["reason"])
        if not report["newCount"] and report.get("errors"):
            # No new trusted evidence: treat as failed, not a successful run.
            result = 1
    except (BackfillError, PilotError, TypeError, KeyError, ValueError, OSError) as exc:
        report = {"status": "failed", "reason": str(exc) if isinstance(
            exc, BackfillError) else "source_or_schema_error",
                  "newCount": 0, "publishable": False, "top10": None}
        result = 1
        print("Backfill failed safely: " + report["reason"])
    (args.output / "research-backfill-status.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False),
        encoding="utf-8")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
