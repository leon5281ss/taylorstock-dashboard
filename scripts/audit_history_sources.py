"""Cross-source OHLCV consistency audit for official TWSE/TPEx historical prices.

Audits overlap between production latest-day OpenAPI archives and dated
historical endpoints. Never merges the feeds or emits trading signals.
"""
import argparse
from datetime import date
import json
from pathlib import Path
from statistics import median
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from backfill_market_pilot import PilotError, records, url_for
from quant_run import fetch_text
from technical_readiness import load_archives, TechnicalError


class AuditError(Exception):
    pass


FIELDS = ("open", "high", "low", "close")
MIN_SHARED = {"TWSE": 700, "TPEX": 500}


def compare_market(live_rows, dated_rows, market, min_shared=None):
    """Use stock code keys, not list order. Denominators are shared symbols."""
    live = {r["code"]: r for r in live_rows if r["market"] == market}
    dated = {r["code"]: r for r in dated_rows if r["market"] == market}
    common = sorted(set(live) & set(dated))
    threshold = MIN_SHARED[market] if min_shared is None else min_shared
    if len(common) < threshold:
        raise AuditError("insufficient_cross_source_overlap_" + market)
    compared = len(common)
    matched = 0
    differing = []
    ratios = {"volume": [], "turnover": []}
    exact_counts = {"volume": 0, "turnover": 0}
    for code in common:
        old, new = dated[code], live[code]
        if all(abs(old[k] - new[k]) <= 0.011 for k in FIELDS):
            matched += 1
        elif len(differing) < 12:
            differing.append({"code": code, "liveClose": new["close"],
                              "datedClose": old["close"]})
        for k in ("volume", "turnover"):
            if old[k] == new[k]:
                exact_counts[k] += 1
            if new[k] > 0:
                ratios[k].append(old[k] / new[k])
    return {"sharedSymbols": compared, "liveQuotes": len(live), "datedQuotes": len(dated),
            "ohlcMatched": matched, "ohlcMatchRate": round(matched / compared, 6),
            "sampleOhlcDifferences": differing,
            "volumeExactMatchRate": round(exact_counts["volume"] / compared, 6),
            "turnoverExactMatchRate": round(exact_counts["turnover"] / compared, 6),
            "datedToLiveMedianVolumeRatio": round(median(ratios["volume"]), 6) if ratios["volume"] else None,
            "datedToLiveMedianTurnoverRatio": round(median(ratios["turnover"]), 6) if ratios["turnover"] else None}


def audit_day(snapshot, historical_responses, min_shared=None, min_roster=None):
    day = snapshot["asOf"]
    market_results = {}
    for market in ("TWSE", "TPEX"):
        # Use only symbols actually present in the official production snapshot.
        # This is deliberately NOT an historical point-in-time investable roster.
        current = [r for r in snapshot["stocks"] if r["market"] == market]
        roster = {r["code"]: True for r in current}
        if not roster:
            raise AuditError("empty_live_market_" + market)
        try:
            dated = records(historical_responses[market], market, day, roster,
                            minimum_ratio=0.70)
        except PilotError as err:
            raise AuditError("dated_source_invalid_" + market + "_" + str(err)) from err
        if dated["sourceDateEvidence"] != "explicit_response_date":
            # Keep observed prices but do not claim independently verified date.
            date_status = "query_only_unverified"
        else:
            date_status = "explicit_response_date"
        details = compare_market(current, dated["rows"], market,
                                 min_shared=(min_shared or {}).get(market))
        details["sourceDateEvidence"] = date_status
        details["datedVolumeScope"] = dated["volumeScope"]
        details["productionVolumeScope"] = ("twse_all_trades_shares"
                                             if market == "TWSE" else "tpex_openapi_all_sessions_shares")
        details["historicalVolumeCompatible"] = (
            market == "TWSE" and details["volumeExactMatchRate"] >= 0.98
            and details["turnoverExactMatchRate"] >= 0.98)
        market_results[market] = details
    return {"asOf": day, "markets": market_results,
            "bothMarketsOhlcAtLeast99Percent": all(
                x["ohlcMatchRate"] >= 0.99 for x in market_results.values()),
            "bothResponseDatesExplicit": all(
                x["sourceDateEvidence"] == "explicit_response_date"
                for x in market_results.values()),
            "integrationAllowed": False,
            "whyNoIntegration": [
                "tpex_historical_round_lot_vs_openapi_full_sessions_volume",
                "historical_unadjusted_prices_and_corporate_actions_not_checked",
                "historical_point_in_time_company_universe_missing",
                "financial_chip_factors_and_backtest_not_complete",
            ]}


def run(archive_dir, fetch, sleep, days=2, delay=2.5):
    if days < 1 or days > 3:
        raise AuditError("audit_limited_to_three_dates")
    snapshots = load_archives(archive_dir)
    if not snapshots:
        raise AuditError("no_existing_market_daily_archives")
    output = []
    for snapshot in snapshots[-days:]:
        responses = {}
        for market in ("TWSE", "TPEX"):
            sleep(delay)
            responses[market] = json.loads(fetch(url_for(market, snapshot["asOf"])))
        output.append(audit_day(snapshot, responses))
    return {"status": "audited_research_only", "daysAudited": len(output),
            "days": output, "top10": None, "publishable": False,
            "integrationAllowed": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive-dir", type=Path, default=Path("data/market_daily"))
    parser.add_argument("--output", type=Path, default=Path("source-audit-output"))
    parser.add_argument("--days", type=int, default=2)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    try:
        report = run(args.archive_dir, fetch_text, time.sleep, days=args.days)
        result = 0
        for day in report["days"]:
            print("OHLC comparison " + day["asOf"] + ": " +
                  ", ".join(m + " " + str(x["ohlcMatchRate"]) +
                            " matched, dated/live volume " +
                            str(x["datedToLiveMedianVolumeRatio"])
                            for m, x in day["markets"].items()) +
                  "; DATA INTEGRATION BLOCKED")
    except (AuditError, TechnicalError, PilotError, OSError, ValueError,
            TypeError, KeyError) as err:
        report = {"status": "failed", "reason": str(err) if isinstance(err, AuditError)
                  else "history_audit_source_or_schema_failure",
                  "daysAudited": 0, "top10": None, "publishable": False,
                  "integrationAllowed": False}
        result = 1
        print("History source audit safely stopped: " + report["reason"])
    (args.output / "cross-source-audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
