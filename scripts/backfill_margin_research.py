"""Bounded historical margin balance research backfill.

Date universe is taken ONLY from existing validated price archives. Margin
unit comparability and publishing timing remain UNKNOWN, so this never
generates trading factors, ranks or private Telegram alerts.
"""
import argparse
from datetime import date, datetime
import gzip
import json
from pathlib import Path
import time
from zoneinfo import ZoneInfo

from collect_market_history import compressed_snapshot
from collect_margin_research import MarginHistoryError, collect


class MarginBackfillError(Exception):
    pass


def candidate_dates(daily_dir, price_research_dir, margin_dir, *,
                    max_successes=12, max_attempts=20):
    if not 1 <= max_successes <= 12 or not max_successes <= max_attempts <= 24:
        raise MarginBackfillError("batch_attempt_limits_invalid")
    eligible = set()
    for root in (Path(daily_dir), Path(price_research_dir)):
        for path in root.glob("*.json.gz"):
            try:
                label = path.name
                if not label.endswith(".json.gz"):
                    continue
                day = label[:-8]
                if date.fromisoformat(day).isoformat() != day:
                    raise ValueError("not canonical")
                eligible.add(day)
            except ValueError as exc:
                raise MarginBackfillError("price_archive_date_invalid") from exc
    if not eligible:
        raise MarginBackfillError("verified_price_archives_missing")
    existing = {p.name[:-8] for p in Path(margin_dir).glob("*.json.gz")}
    # Deliberately newest first; only verified market dates can enter the plan.
    return {"dates": sorted(eligible - existing, reverse=True),
            "priceDays": len(eligible), "alreadyArchived": len(existing),
            "maxSuccesses": max_successes, "maxAttempts": max_attempts}


def archive_margin_batch(daily_dir, price_dir, margin_dir, *,
                         fetch_day=collect, sleep=time.sleep, delay=3.0,
                         max_successes=12, max_attempts=20):
    if delay < 2.5:
        raise MarginBackfillError("minimum_three_second_source_spacing")
    plan = candidate_dates(daily_dir, price_dir, margin_dir,
                           max_successes=max_successes,
                           max_attempts=max_attempts)
    if not plan["dates"]:
        return {"status": "already_archived", "newCount": 0,
                "newDates": [], "errors": [], "priceDates": plan["priceDays"],
                "researchMarginDays": plan["alreadyArchived"],
                "marginFactorReady": False, "top10": None, "publishable": False}
    new_dates, errors = [], []
    for day in plan["dates"]:
        if len(new_dates) >= max_successes or len(new_dates) + len(errors) >= max_attempts:
            break
        try:
            sleep(delay)
            payload = fetch_day(day)
            if (not isinstance(payload, dict)
                    or payload.get("schemaVersion") != 1
                    or payload.get("status") != "margin_balance_history_research_only"
                    or payload.get("asOf") != day
                    or payload.get("officialSourceDateExplicit") is not True
                    or payload.get("unitsNotCrossMarketNormalized") is not True
                    or payload.get("marginFactorReady") is not False
                    or payload.get("publishable") is not False
                    or payload.get("top10") is not None
                    or payload.get("pointInTimeCompanyUniverseVerified") is not False
                    or payload.get("currentBalanceAvailableDuringTradingSession") is not False
                    or not isinstance(payload.get("rows"), list)
                    or len(payload["rows"]) < 1200):
                raise MarginBackfillError("margin_day_schema_or_guard_invalid")
            counts = payload.get("marketCounts")
            if (not isinstance(counts, dict)
                    or set(counts) != {"TWSE", "TPEX"}
                    or counts["TWSE"] < 650 or counts["TPEX"] < 450
                    or counts["TWSE"] + counts["TPEX"] != len(payload["rows"])):
                raise MarginBackfillError("margin_day_market_coverage_invalid")
            dest = Path(margin_dir) / (day + ".json.gz")
            if dest.exists():
                raise MarginBackfillError("existing_margin_archive_not_overwritten")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(compressed_snapshot(payload))
            new_dates.append({"date": day, "marketCounts": counts})
        except (MarginHistoryError, MarginBackfillError, OSError, TypeError,
                ValueError, KeyError, json.JSONDecodeError) as exc:
            errors.append({"date": day,
                           "reason": str(exc) if isinstance(
                               exc, (MarginHistoryError, MarginBackfillError))
                           else "official_margin_source_or_schema_unavailable"})
            if len(errors) >= 6:
                break
    return {
        "status": ("partial_with_unverified_days" if errors
                   else "research_only_archived" if new_dates
                   else "no_new_archive"),
        "newCount": len(new_dates), "newDates": new_dates, "errors": errors,
        "priceDates": plan["priceDays"],
        "researchMarginDays": plan["alreadyArchived"] + len(new_dates),
        "unitConversionVerified": False,
        "pointInTimeCompanyUniverseVerified": False,
        "marginFactorReady": False,
        "backtestedNetReturnsVerified": False,
        "top10": None, "publishable": False,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--daily-dir", type=Path, default=Path("data/market_daily"))
    p.add_argument("--price-research-dir", type=Path, default=Path("data/market_backfill_pilot"))
    p.add_argument("--margin-dir", type=Path, default=Path("data/margin_research"))
    p.add_argument("--output", type=Path, default=Path("margin-batch-output"))
    p.add_argument("--max-successes", type=int, default=12)
    p.add_argument("--max-attempts", type=int, default=20)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    try:
        report = archive_margin_batch(a.daily_dir, a.price_research_dir, a.margin_dir,
                                      max_successes=a.max_successes,
                                      max_attempts=a.max_attempts)
        status = 0 if (report["newCount"] or not report["errors"]) else 1
        print("Margin research batch:", report["status"], "new", report["newCount"],
              "total", report["researchMarginDays"], "not rankable")
        for error in report["errors"]:
            print("::warning::", error["date"], error["reason"])
    except (MarginBackfillError, OSError, ValueError, TypeError, KeyError) as e:
        report = {"status": "failed",
                  "reason": str(e) if isinstance(e, MarginBackfillError)
                  else "margin_batch_unavailable",
                  "newCount": 0, "top10": None, "publishable": False}
        status = 1
        print("Margin batch safely failed:", report["reason"])
    (a.output / "margin-batch-status.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
