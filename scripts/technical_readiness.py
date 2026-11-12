"""Research-only technical factor readiness from verified DAILY official archives.

Raw/unadjusted price series are NEVER treated as corporate-action-adjusted data
and NEVER passed into trade recommendations, scoring or Telegram.
"""
import argparse
from collections import defaultdict
from datetime import date, datetime
import gzip
import json
import math
from pathlib import Path
from statistics import mean, pstdev
from zoneinfo import ZoneInfo


class TechnicalError(Exception):
    pass


def load_archives(archive_dir):
    snapshots = []
    for path in sorted(Path(archive_dir).glob("*.json.gz")):
        try:
            payload = json.loads(gzip.decompress(path.read_bytes()))
            stamp = payload["asOf"]
            date.fromisoformat(stamp)
            if path.name != stamp + ".json.gz":
                raise TechnicalError("archive_filename_date_mismatch")
            if payload.get("schemaVersion") != 1 or payload.get("priceAdjustment") != "raw_unadjusted":
                raise TechnicalError("unsupported_archive_schema_or_adjustment")
            rows = payload["stocks"]
            if not isinstance(rows, list) or not isinstance(payload.get("marketCounts"), dict):
                raise TechnicalError("archive_stock_schema_invalid")
            codes = set()
            actual = {"TWSE": 0, "TPEX": 0}
            for row in rows:
                market, code = row["market"], row["code"]
                if market not in actual or not isinstance(code, str) or len(code) != 4 or not code.isdigit():
                    raise TechnicalError("archive_stock_identifier_invalid")
                key = (market, code)
                if key in codes:
                    raise TechnicalError("duplicate_market_code_in_archive")
                codes.add(key)
                actual[market] += 1
                for field in ("open", "high", "low", "close", "volume", "turnover"):
                    value = row.get(field)
                    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                        raise TechnicalError("nonfinite_market_price_or_volume")
                    if (field in ("open", "high", "low", "close") and value <= 0) or (field in ("volume", "turnover") and value < 0):
                        raise TechnicalError("invalid_market_price_or_volume")
                if row["high"] < max(row["open"], row["close"], row["low"]) or row["low"] > min(row["open"], row["close"], row["high"]):
                    raise TechnicalError("invalid_ohlc_archive")
            if actual != payload["marketCounts"]:
                raise TechnicalError("archive_market_counts_mismatch")
            snapshots.append(payload)
        except (OSError, EOFError, ValueError, TypeError, KeyError, gzip.BadGzipFile, json.JSONDecodeError) as exc:
            raise TechnicalError("invalid_archived_snapshot") from exc
    dates = [s["asOf"] for s in snapshots]
    if len(dates) != len(set(dates)):
        raise TechnicalError("duplicate_archive_trading_date")
    return snapshots


def _ema(values, days):
    alpha = 2 / (days + 1)
    result = []
    previous = None
    for x in values:
        previous = x if previous is None else alpha * x + (1-alpha) * previous
        result.append(previous)
    return result


def features(rows):
    if len(rows) < 121:
        raise TechnicalError("insufficient_technical_history")
    prices = [x["close"] for x in rows]
    close = prices[-1]
    changes = [b-a for a, b in zip(prices[-15:-1], prices[-14:])]
    gains = sum(max(c, 0) for c in changes)
    losses = -sum(min(c, 0) for c in changes)
    rsi = 50.0 if gains == 0 and losses == 0 else (100.0 if losses == 0 else 100 - 100/(1+gains/losses))
    macd = [x-y for x,y in zip(_ema(prices,12),_ema(prices,26))]
    hist = macd[-1] - _ema(macd,9)[-1]
    returns = [b/a - 1 for a,b in zip(prices[-21:-1],prices[-20:])]
    return {"close": close,
            "ma5": round(mean(prices[-5:]), 5),
            "ma20": round(mean(prices[-20:]), 5),
            "ma60": round(mean(prices[-60:]), 5),
            "ma120": round(mean(prices[-120:]), 5),
            "rsi14": round(rsi, 4),
            "macdHistogram": round(hist, 6),
            "momentum5": round(close/prices[-6]-1, 6),
            "momentum20": round(close/prices[-21]-1, 6),
            "volatility20": round(pstdev(returns), 6),
            "turnover20": round(mean(x["turnover"] for x in rows[-20:]), 2)}


def readiness(snapshots, now=None):
    now = now or datetime.now(ZoneInfo("Asia/Taipei"))
    today = now.astimezone(ZoneInfo("Asia/Taipei")).date()
    dates = [s["asOf"] for s in snapshots]
    if not dates:
        return {"status": "no_archive", "asOf": None, "archivedTradingDays": 0,
                "daysUntil121": 121, "latestQuotedStocks": 0, "technicalCompleteCount": 0,
                "rawTechnicalResearch": [], "top10": None,
                "publishable": False, "reason": "no_archived_history"}
    latest_date = date.fromisoformat(dates[-1])
    if latest_date > today:
        raise TechnicalError("future_archive_date")
    all_rows = defaultdict(dict)
    for snapshot in snapshots:
        for row in snapshot["stocks"]:
            all_rows[(row["market"], row["code"])][snapshot["asOf"]] = row
    latest = snapshots[-1]
    output = []
    if len(dates) >= 121:
        required = dates[-121:]
        for row in latest["stocks"]:
            key = (row["market"], row["code"])
            if all(day in all_rows[key] for day in required):
                values = features([all_rows[key][day] for day in required])
                output.append({"code": row["code"], "market": row["market"],
                               "asOf": latest["asOf"], **values})
    return {"status": "research_only" if output else "history_building",
            "asOf": latest["asOf"],
            "archivedTradingDays": len(dates),
            "daysUntil121": max(0,121-len(dates)),
            "latestQuotedStocks": len(latest["stocks"]),
            "technicalCompleteCount": len(output),
            "rawTechnicalResearch": output,
            "top10": None,
            "publishable": False,
            "adjustmentStatus": "UNADJUSTED_CORPORATE_ACTION_CHECK_NOT_DONE",
            "reason": "technical_indicators_are_unadjusted_and_full_factors_missing"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive-dir", type=Path, default=Path("data/market_daily"))
    parser.add_argument("--output", type=Path, default=Path("technical-output"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    try:
        output = readiness(load_archives(args.archive_dir))
        print("Technical readiness: " + output["status"] + "; archived-days=" +
              str(output["archivedTradingDays"]) + "; technical-ready=" +
              str(output["technicalCompleteCount"]) + "; TOP10 BLOCKED")
        result = 0
    except TechnicalError as err:
        output = {"status": "failed", "reason": str(err), "top10": None,
                  "publishable": False}
        print("Technical archive rejected: " + str(err))
        result = 1
    (args.output / "technical-readiness.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
