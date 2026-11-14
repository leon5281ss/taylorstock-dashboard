"""Compare dated official volumes with same-day OpenAPI archives."""
import argparse
from collections import Counter
import gzip
import json
import re
from pathlib import Path

from backfill_market_pilot import PilotError, _source_date, tables, url_for
from collect_market_history import IngestionError, URLS, number
from research_price_coverage import CoverageError, MARKETS, load_snapshot

HISTORICAL_SCOPE = {"TWSE": "exchange_daily_report", "TPEX": "round_lot"}


def compare(day, market, daily, payload):
    if _source_date(payload, day) != "explicit_response_date":
        raise PilotError("missing_official_response_date")
    fields, rows = tables(payload, market)
    code_index = fields.index("證券代號" if market == "TWSE" else "代號")
    volume_index = fields.index("成交股數")
    historical = {}
    for row in rows:
        if not isinstance(row, list) or len(row) != len(fields):
            raise PilotError("invalid_historical_volume_row")
        code = str(row[code_index]).strip()
        if not re.fullmatch(r'[1-9][0-9]{3}', code):
            continue
        if code in historical:
            raise PilotError("duplicate_historical_volume_code")
        value = number(row[volume_index], integer=True)
        historical[code] = value if value is not None and value >= 0 else None
    evidence = []
    for code in sorted(daily.keys() | historical.keys()):
        current, prior = daily.get(code), historical.get(code)
        presence = ("historical_only" if code not in daily else
                    "daily_only" if code not in historical else "both")
        if type(current) is not int or current < 0:
            current = None
        delta = prior - current if prior is not None and current is not None else None
        status = ("equal" if delta == 0 else "different" if delta is not None
                  else "missing_or_invalid_historical_volume" if code not in historical or prior is None
                  else "missing_or_invalid_daily_volume")
        evidence.append({"code": code, "dailyShares": current, "historicalShares": prior,
                         "presence": presence, "differenceShares": delta,
                         "absoluteDifferenceShares": abs(delta) if delta is not None else None,
                         "relativeDifferencePercent": 100 * delta / current
                         if delta is not None and current > 0 else None,
                         "invalidHistoricalVolume": code in historical and prior is None,
                         "invalidDailyVolume": code in daily and current is None,
                         "status": status, "v5v60Available": False, "v5v60": None})
    return {"date": day, "market": market, "dailySource": URLS[market],
            "historicalSource": url_for(market, day), "unit": "shares",
            "boardLotConversionApplied": False,
            "historicalScope": HISTORICAL_SCOPE[market],
            "dailyScope": "openapi_scope_unverified", "oddLotCoverageVerified": False,
            "afterHoursAndBlockCoverageVerified": False,
            "scopeEquivalenceVerified": False,
            "counts": dict(Counter(item["status"] for item in evidence if item["presence"] != "historical_only")),
            "summary": summarize(evidence), "stocks": evidence}


def summarize(rows):
    diffs = [r["differenceShares"] for r in rows if r["differenceShares"] is not None]
    relative = [r["relativeDifferencePercent"] for r in rows
                if r["relativeDifferencePercent"] is not None]
    return {
        "coverage": dict(Counter(r["presence"] for r in rows)),
        "invalidDaily": sum(r["invalidDailyVolume"] for r in rows),
        "invalidHistorical": sum(r["invalidHistoricalVolume"] for r in rows),
        "equal": diffs.count(0), "historicalHigher": sum(n > 0 for n in diffs),
        "historicalLower": sum(n < 0 for n in diffs),
        "netDifferenceShares": sum(diffs), "absoluteDifferenceShares": sum(map(abs, diffs)),
        "maxAbsoluteDifferenceShares": max(map(abs, diffs), default=None),
        "relativeDifferenceSamples": len(relative),
        "meanRelativeDifferencePercent": sum(relative) / len(relative) if relative else None,
        "meanAbsoluteRelativeDifferencePercent": sum(map(abs, relative)) / len(relative)
        if relative else None,
    }


def audit(daily_dir, response_dir):
    comparisons, errors = [], []
    for path in sorted(daily_dir.glob("*.json.gz")):
        snapshot = load_snapshot(path, historical=False)
        day = snapshot["asOf"]
        with gzip.open(path, "rt", encoding="utf-8") as file:
            archive = json.load(file)
        if archive.get("sources") != URLS:
            raise CoverageError("unexpected_daily_source")
        for market in MARKETS:
            response = response_dir / f"{market}-{day}.json"
            try:
                payload = json.loads(response.read_text(encoding="utf-8-sig"))
                quotes = {r["code"]: r["volume"] for r in archive["stocks"]
                          if r["market"] == market}
                comparisons.append(compare(day, market, quotes, payload))
            except (OSError, ValueError, TypeError, AttributeError, PilotError, IngestionError) as exc:
                reason = str(exc) if isinstance(exc, (PilotError, IngestionError)) else "response_unavailable_or_invalid"
                errors.append({"date": day, "market": market, "reason": reason})
    return {"comparisons": comparisons, "errors": errors,
            "marketSummary": {market: summarize([stock for item in comparisons
                                                if item["market"] == market
                                                for stock in item["stocks"]])
                              for market in MARKETS},
            "requiredVolumeWindowDays": 60, "scopeVerifiedWindows": 0,
            "v5v60Available": False, "v5v60": None, "top10": None, "publishable": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--daily-dir", type=Path, default=Path("data/market_daily"))
    parser.add_argument("--response-dir", type=Path, required=True,
                        help="Official dated responses saved as MARKET-YYYY-MM-DD.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.daily_dir, args.response_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return int(not report["comparisons"] or bool(report["errors"]))


if __name__ == "__main__":
    raise SystemExit(main())
