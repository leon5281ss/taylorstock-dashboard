"""Audit close-price research coverage from separated production and historical archives.

Never combines volume/turnover, never treats unadjusted prices as backtest-ready,
never outputs buy/sell rankings. Historical-company and corporate-action
adjustment gates remain blocked regardless of observed price-history length.
"""
import argparse
from collections import defaultdict
from datetime import date, datetime
import gzip
import json
import math
from pathlib import Path
from zoneinfo import ZoneInfo


class CoverageError(Exception):
    pass


def load_snapshot(path, *, historical, minimum=(700, 500)):
    try:
        payload = json.loads(gzip.decompress(Path(path).read_bytes()))
        day = date.fromisoformat(payload["asOf"])
        if Path(path).name != day.isoformat() + ".json.gz":
            raise CoverageError("file_date_mismatch")
        if payload["schemaVersion"] != 1 or payload["priceAdjustment"] != "raw_unadjusted":
            raise CoverageError("unrecognized_price_schema")
        if historical:
            if payload["status"] != "historical_pilot_research_only":
                raise CoverageError("historical_status_invalid")
            if payload["pointInTimeUniverse"] is not False:
                raise CoverageError("point_in_time_claim_invalid")
            if payload["volumeScopes"]["TPEX"] != "tpex_round_lot_shares":
                raise CoverageError("missing_tpex_volume_scope")
            if payload["mixedVolumeWithDailyOpenAPI"] is not False:
                raise CoverageError("historical_volume_mixed")
            evidence = payload["sourceDateEvidence"]
            if any(evidence.get(m) not in ("explicit_response_date", "query_only_unverified")
                   for m in ("TWSE", "TPEX")):
                raise CoverageError("source_date_evidence_missing")
        else:
            if "status" in payload and payload["status"] == "historical_pilot_research_only":
                raise CoverageError("historical_archive_in_production")
            evidence = {"TWSE": "daily_openapi_snapshot", "TPEX": "daily_openapi_snapshot"}
        rows = payload["stocks"]
        if not isinstance(rows, list):
            raise CoverageError("invalid_rows")
        seen = set()
        counts = {"TWSE": 0, "TPEX": 0}
        for row in rows:
            key = (row["market"], row["code"])
            if row["market"] not in counts or not isinstance(row["code"], str):
                raise CoverageError("invalid_market_code")
            if len(row["code"]) != 4 or not row["code"].isdigit():
                raise CoverageError("invalid_market_code")
            if key in seen:
                raise CoverageError("duplicate_market_code")
            seen.add(key)
            counts[row["market"]] += 1
            for field in ("open", "high", "low", "close"):
                value = row[field]
                if (isinstance(value, bool) or not isinstance(value, (float, int))
                        or not math.isfinite(value) or value <= 0):
                    raise CoverageError("invalid_ohlc")
            if (row["high"] < max(row["open"], row["low"], row["close"])
                    or row["low"] > min(row["open"], row["high"], row["close"])):
                raise CoverageError("inconsistent_ohlc")
        if counts != payload["marketCounts"]:
            raise CoverageError("market_counts_inconsistent")
        if counts["TWSE"] < minimum[0] or counts["TPEX"] < minimum[1]:
            raise CoverageError("market_coverage_too_low")
        return {"asOf": day.isoformat(), "kind": "historical_research" if historical
                else "production_daily", "sourceDateEvidence": evidence,
                "closes": {(row["market"], row["code"]): row["close"] for row in rows},
                "counts": counts}
    except (OSError, EOFError, ValueError, TypeError, KeyError, gzip.BadGzipFile,
            json.JSONDecodeError) as exc:
        raise CoverageError("corrupt_or_incomplete_gzip") from exc


def audit_coverage(daily_dir, historical_dir, *, today=None, minimum=(700, 500)):
    today = today or datetime.now(ZoneInfo("Asia/Taipei")).date()
    daily_paths = sorted(Path(daily_dir).glob("*.json.gz"))
    history_paths = sorted(Path(historical_dir).glob("*.json.gz"))
    days = {}
    for historical, paths in ((True, history_paths), (False, daily_paths)):
        for path in paths:
            snapshot = load_snapshot(path, historical=historical, minimum=minimum)
            d = snapshot["asOf"]
            if d in days:
                raise CoverageError("overlapping_source_dates_need_manual_review")
            if date.fromisoformat(d) > today:
                raise CoverageError("future_observation_date")
            days[d] = snapshot
    if not daily_paths or not days:
        raise CoverageError("required_production_snapshots_missing")
    ordered_days = sorted(days)
    latest = ordered_days[-1]
    if days[latest]["kind"] != "production_daily":
        raise CoverageError("latest_date_not_production_daily")
    current = set(days[latest]["closes"])
    cohorts = {}
    for required in (5, 20, 60, 121):
        if len(ordered_days) < required:
            cohorts[str(required)] = {"TWSE": 0, "TPEX": 0}
            continue
        target = ordered_days[-required:]
        complete = [key for key in current if all(key in days[d]["closes"] for d in target)]
        cohorts[str(required)] = {
            market: sum(1 for code_market, _ in complete if code_market == market)
            for market in ("TWSE", "TPEX")
        }
    query_only = sorted(d for d, snapshot in days.items()
                        if "query_only_unverified" in snapshot["sourceDateEvidence"].values())
    return {"status": "research_price_coverage_only",
            "latestObservedDate": latest,
            "latestSource": days[latest]["kind"],
            "totalObservedDates": len(ordered_days),
            "productionDays": len(daily_paths),
            "historicalResearchDays": len(history_paths),
            "earliestObservedDate": ordered_days[0],
            "latestQuoteCounts": days[latest]["counts"],
            "pricePresenceByWindow": cohorts,
            "historicalSourceDateNotExplicitCount": len(query_only),
            "observedDatesNotCertifiedAsCompleteExchangeCalendar": True,
            "volumeScopeCompatible": False,
            "corporateActionAdjusted": False,
            "historicalPointInTimeUniverseAvailable": False,
            "fullFactorDataReady": False,
            "verifiedBacktestAvailable": False,
            "top10": None, "publishable": False,
            "blockingReasons": [
                "historical_source_volume_scope_mismatch",
                "price_adjustments_and_corporate_actions_not_verified",
                "historic_company_universe_and_delisted_samples_missing",
                "exchange_calendar_and_source_date_evidence_incomplete",
                "institutional_tdcc_financial_valuation_factors_missing",
                "out_of_sample_net_fee_tax_backtest_not_completed",
            ]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--daily-dir", type=Path, default=Path("data/market_daily"))
    parser.add_argument("--history-dir", type=Path, default=Path("data/market_backfill_pilot"))
    parser.add_argument("--output", type=Path, default=Path("research-coverage-output"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    try:
        report = audit_coverage(args.daily_dir, args.history_dir)
        result = 0
        print("Price research coverage: " + str(report["totalObservedDates"]) +
              " archived dates, " + str(report["productionDays"]) + " production, " +
              str(report["historicalResearchDays"]) + " historical; 121-price-ready=" +
              str(sum(report["pricePresenceByWindow"]["121"].values())) +
              "; NO TRADING SIGNALS")
    except CoverageError as err:
        report = {"status": "failed", "reason": str(err),
                  "top10": None, "publishable": False}
        result = 1
        print("Research price coverage safely rejected: " + str(err))
    (args.output/"research-price-coverage.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
