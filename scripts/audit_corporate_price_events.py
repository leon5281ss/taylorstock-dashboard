"""Read-only official event versus raw daily price consistency research.

A match between prior raw close and official ex-right reference event's
previousClose is evidence of source consistency, NOT a corporate-action
adjustment, backtest, or total-return price series.
"""
import argparse
from bisect import bisect_left
from datetime import date
import gzip
import json
from pathlib import Path

from research_price_coverage import CoverageError, load_snapshot


class EventPriceError(Exception):
    pass


def load_events(folder):
    files = sorted(Path(folder).glob("*.json.gz"))
    if not files:
        raise EventPriceError("missing_corporate_event_research")
    events, seen = [], set()
    for path in files:
        try:
            data = json.loads(gzip.decompress(path.read_bytes()))
            if (path.name != data["asOf"][:4]+".json.gz"
                    or data.get("schemaVersion") != 1
                    or data.get("status") != "corporate_action_reference_research_only"
                    or data.get("adjustedOhlcvReady") is not False
                    or data.get("referenceRatioIsNotTotalReturn") is not True
                    or data.get("publishable") is not False):
                raise EventPriceError("untrusted_corporate_event_provenance")
            if sum(data["marketCounts"].values()) != len(data["events"]):
                raise EventPriceError("corporate_event_counts_mismatch")
            for event in data["events"]:
                d = date.fromisoformat(event["exDate"])
                if not data["start"] <= d.isoformat() <= data["end"]:
                    raise EventPriceError("corporate_event_outside_source_window")
                key = (event["market"], event["code"], event["exDate"])
                if key in seen or event["market"] not in ("TWSE", "TPEX"):
                    raise EventPriceError("duplicate_corporate_event")
                seen.add(key)
                if any(not isinstance(event.get(k), (float, int)) or
                       isinstance(event.get(k), bool) or event[k] <= 0
                       for k in ("previousClose", "referencePrice", "referenceRatio")):
                    raise EventPriceError("nonpositive_corporate_event_price")
                events.append(event)
        except (OSError, ValueError, TypeError, KeyError,
                gzip.BadGzipFile) as exc:
            raise EventPriceError("invalid_corporate_event_gzip") from exc
    return events


def audit(daily_dir, historic_dir, corp_dir, *, price_tolerance=0.011):
    days = {}
    for hist, folder in ((False, daily_dir), (True, historic_dir)):
        for path in sorted(Path(folder).glob("*.json.gz")):
            try:
                snap = load_snapshot(path, historical=hist)
            except CoverageError as exc:
                raise EventPriceError("invalid_price_archive") from exc
            day = snap["asOf"]
            if day in days:
                raise EventPriceError("overlapping_price_sources")
            days[day] = snap["closes"]
    if len(days) < 2:
        raise EventPriceError("insufficient_archived_price_dates")
    ordered = sorted(days)
    events = load_events(corp_dir)
    if not events:
        raise EventPriceError("zero_official_corporate_events")
    observed, out_of_range, nontrading, prior_missing, matching, different = (
        0, 0, 0, 0, 0, [])
    event_on_price_date = 0
    for e in events:
        ex = e["exDate"]
        if not ordered[0] <= ex <= ordered[-1]:
            out_of_range += 1
            continue
        observed += 1
        if ex not in days:
            nontrading += 1
            continue
        event_on_price_date += 1
        i = bisect_left(ordered, ex)
        if i == 0:
            prior_missing += 1
            continue
        prev = ordered[i-1]
        if (date.fromisoformat(ex)-date.fromisoformat(prev)).days > 7:
            prior_missing += 1
            continue
        key = (e["market"], e["code"])
        previous = days[prev].get(key)
        if previous is None:
            prior_missing += 1
            continue
        if abs(previous - e["previousClose"]) <= price_tolerance:
            matching += 1
        else:
            if len(different) < 20:
                different.append({
                    "code": e["code"], "market": e["market"],
                    "exDate": ex, "previousObservedDay": prev,
                    "observedPriorClose": previous,
                    "officialCorporatePreviousClose": e["previousClose"],
                })
    # Do not compute a total-return or adjusted OHLC series; this only checks
    # one field against a prior observation, and lacks cash dividends/splits.
    return {
        "status": "research_corporate_event_price_crosscheck_only",
        "earliestPriceDay": ordered[0], "latestPriceDay": ordered[-1],
        "priceObservedDates": len(ordered),
        "officialCorporateReferenceEvents": len(events),
        "eventsOutsidePriceRange": out_of_range,
        "eventsInsidePriceRange": observed,
        "eventsWithExDayPrice": event_on_price_date,
        "eventsWithoutObservedExDay": nontrading,
        "eventsWithoutUsablePriorClose": prior_missing,
        "priorRawCloseMatchesReferencePreviousClose": matching,
        "samplePriorCloseDifferences": different,
        "samplePriorCloseDifferenceCountDisplayed": len(different),
        "absenceOfDifferencesDoesNotProveTotalReturnAdjustment": True,
        "priceSeriesAdjustedForCashAndStockDividends": False,
        "capitalReductionsAndStockSplitsVerified": False,
        "pointInTimeCompanyUniverseVerified": False,
        "corporateActionsCheckedForTrading": False,
        "netReturnBacktestReady": False,
        "top10": None, "publishable": False,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--daily-dir", type=Path, default=Path("data/market_daily"))
    p.add_argument("--historical-dir", type=Path, default=Path("data/market_backfill_pilot"))
    p.add_argument("--corporate-dir", type=Path, default=Path("data/corporate_action_research"))
    p.add_argument("--output", type=Path, default=Path("corporate-price-output"))
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    try:
        result = audit(a.daily_dir, a.historical_dir, a.corporate_dir)
        status = 0
        print("Corporate event versus raw prices: in-range events=" +
              str(result["eventsInsidePriceRange"]) +
              "; prior-close matches=" +
              str(result["priorRawCloseMatchesReferencePreviousClose"]) +
              "; NOT ADJUSTED, NO TOP10")
    except (EventPriceError, ValueError, TypeError) as exc:
        result = {"status": "failed", "reason": str(exc) if isinstance(
            exc, EventPriceError) else "official_corporate_price_crosscheck_invalid",
                  "top10": None, "publishable": False}
        status = 1
        print("Corporate event price crosscheck stopped safely:", result["reason"])
    (a.output/"corporate-price-crosscheck.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
