"""Archive evidence-checked official TWSE / TPEx daily closing prices.

Only publicly published, unadjusted OHLCV is stored. No holdings or credentials.
"""
import argparse
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import gzip
import io
import json
import math
import re
from pathlib import Path
from zoneinfo import ZoneInfo

from market_pipeline.quant_screen import official_universe
from quant_run import fetch_csv, fetch_json

TWSE_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TPEX_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
URLS = {"TWSE": TWSE_URL, "TPEX": TPEX_URL}
MINIMUM = {"TWSE": 1000, "TPEX": 700}


class IngestionError(Exception):
    pass


def roc_to_iso(value):
    """Accept ROC YYYMMDD, YYY/MM/DD and validated Gregorian YYYYMMDD."""
    value = str(value).strip()
    digits = re.sub(r"[/.\-]", "", value)
    if not digits.isdigit() or len(digits) not in (7, 8):
        raise IngestionError("date_format_invalid")
    year_digits = 3 if len(digits) == 7 else 4
    year = int(digits[:year_digits]) + (1911 if year_digits == 3 else 0)
    try:
        return date(year, int(digits[year_digits:year_digits + 2]),
                    int(digits[year_digits + 2:])).isoformat()
    except ValueError:
        raise IngestionError("date_value_invalid") from None


def number(value, *, integer=False):
    """Never coerce missing, suspended, inf, NaN, or invalid strings to zero."""
    if value is None or isinstance(value, bool):
        return None
    raw = str(value).strip().replace(",", "")
    if raw in ("", "-", "--", "---", "N/A", "NAN", "null", "X", "除權", "除息"):
        return None
    try:
        number_value = Decimal(raw)
        if not number_value.is_finite():
            return None
        if integer:
            if number_value != number_value.to_integral_value():
                return None
            return int(number_value)
        value_float = float(number_value)
        return value_float if math.isfinite(value_float) else None
    except (InvalidOperation, ValueError, OverflowError):
        return None


def row_to_price(raw, market):
    code_key = "Code" if market == "TWSE" else "SecuritiesCompanyCode"
    code = str(raw.get(code_key, "")).strip()
    if market == "TWSE":
        keys = ("OpeningPrice", "HighestPrice", "LowestPrice", "ClosingPrice",
                "TradeVolume", "TradeValue", "Transaction")
    else:
        keys = ("Open", "High", "Low", "Close", "TradingShares",
                "TransactionAmount", "TransactionNumber")
    opening, high, low, close = (number(raw.get(key)) for key in keys[:4])
    volume, turnover = number(raw.get(keys[4]), integer=True), number(raw.get(keys[5]), integer=True)
    if None in (opening, high, low, close, volume, turnover):
        return None
    if min(opening, high, low, close) <= 0 or min(volume, turnover) < 0:
        return None
    if high < max(opening, close, low) or low > min(opening, close, high):
        raise IngestionError("ohlc_invariant_broken_" + market)
    return {"code": code, "market": market,
            "open": opening, "high": high, "low": low, "close": close,
            "volume": volume, "turnover": turnover}


def parse_market(rows, market, universe, minimum=None):
    """Require a single official date and >=80% coverage of company roster."""
    if not isinstance(rows, list) or not rows:
        raise IngestionError("empty_official_response_" + market)
    roster = universe["markets"].get(market, {})
    minimum = MINIMUM[market] if minimum is None else minimum
    if len(roster) < minimum:
        raise IngestionError("official_roster_incomplete_" + market)
    parsed, dates, seen = [], set(), set()
    market_code_key = "Code" if market == "TWSE" else "SecuritiesCompanyCode"
    for raw in rows:
        if not isinstance(raw, dict):
            raise IngestionError("official_row_schema_invalid_" + market)
        code = str(raw.get(market_code_key, "")).strip()
        if code not in roster:
            continue  # ETF, warrant or other non-company security.
        day = roc_to_iso(raw.get("Date", ""))
        dates.add(day)
        if code in seen:
            raise IngestionError("duplicate_official_code_" + market)
        seen.add(code)
        record = row_to_price(raw, market)
        if record is not None:
            parsed.append(record)
    if len(dates) != 1:
        raise IngestionError("mixed_or_missing_official_dates_" + market)
    if len(parsed) < max(1, int(len(roster) * 0.80)):
        raise IngestionError("insufficient_valid_quotes_" + market)
    return {"date": next(iter(dates)), "stocks": parsed,
            "quoted": len(parsed), "roster": len(roster),
            "noValidQuote": len(roster) - len(parsed)}


def make_snapshot(universe, source_rows, now=None, minimum=None):
    """Fail closed if exchanges disagree, data stale or roster incomplete."""
    if universe.get("errors"):
        raise IngestionError("official_roster_errors")
    now = now or datetime.now(ZoneInfo("Asia/Taipei"))
    now_day = now.astimezone(ZoneInfo("Asia/Taipei")).date()
    output = {}
    for market in ("TWSE", "TPEX"):
        output[market] = parse_market(source_rows[market], market, universe,
                                      minimum=(minimum or {}).get(market))
    as_of = output["TWSE"]["date"]
    if as_of != output["TPEX"]["date"]:
        raise IngestionError("exchange_dates_mismatch")
    stamp = date.fromisoformat(as_of)
    if stamp > now_day or (now_day - stamp).days > 4:
        raise IngestionError("stale_or_future_quote")
    roster_overlap = set(universe["markets"]["TWSE"]) & set(universe["markets"]["TPEX"])
    if roster_overlap:
        raise IngestionError("duplicate_company_in_universe")
    stocks = sorted(output["TWSE"]["stocks"] + output["TPEX"]["stocks"],
                    key=lambda x: (x["market"], x["code"]))
    return {"schemaVersion": 1, "asOf": as_of,
            "priceAdjustment": "raw_unadjusted",
            "sources": URLS,
            "marketCounts": {k: output[k]["quoted"] for k in ("TWSE", "TPEX")},
            "rosterCounts": {k: output[k]["roster"] for k in ("TWSE", "TPEX")},
            "missingQuoteCounts": {k: output[k]["noValidQuote"] for k in ("TWSE", "TPEX")},
            "stocks": stocks}


def compressed_snapshot(payload):
    """Deterministic gzip bytes make same-day reruns idempotent."""
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"),
                      sort_keys=True, allow_nan=False).encode("utf-8")
    buf = io.BytesIO()
    with gzip.GzipFile(filename="", fileobj=buf, mode="wb", mtime=0) as f:
        f.write(body)
    return buf.getvalue()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive-dir", type=Path, default=Path("data/market_daily"))
    parser.add_argument("--diagnostics", type=Path, default=Path("ingestion-output"))
    args = parser.parse_args()
    args.diagnostics.mkdir(parents=True, exist_ok=True)
    diagnostic = {"status": "failed", "reason": "not_started"}
    exit_status = 1
    try:
        universe = official_universe(fetch_json, fetch_csv)
        rows = {market: fetch_json(url) for market, url in URLS.items()}
        snapshot = make_snapshot(universe, rows)
        target = args.archive_dir / (snapshot["asOf"] + ".json.gz")
        target.parent.mkdir(parents=True, exist_ok=True)
        content = compressed_snapshot(snapshot)
        if target.exists() and target.read_bytes() == content:
            status = "unchanged"
        else:
            target.write_bytes(content)
            status = "archived"
        diagnostic = {"status": status, "asOf": snapshot["asOf"],
                      "marketCounts": snapshot["marketCounts"],
                      "rosterCounts": snapshot["rosterCounts"],
                      "missingQuoteCounts": snapshot["missingQuoteCounts"],
                      "archive": target.as_posix(), "bytes": len(content),
                      "sourceUrls": URLS, "historicalDaysPresent": len(list(args.archive_dir.glob("*.json.gz")))}
        exit_status = 0
        print("Official prices " + status + " for " + snapshot["asOf"] +
              ": TWSE " + str(snapshot["marketCounts"]["TWSE"]) +
              ", TPEx " + str(snapshot["marketCounts"]["TPEX"]) +
              ". Raw/unadjusted; not yet suitable for backtest.")
    except (IngestionError, KeyError, ValueError, TypeError, OSError) as exc:
        reason = str(exc) if isinstance(exc, IngestionError) else "official_source_or_schema_error"
        diagnostic = {"status": "failed", "reason": reason, "sourceUrls": URLS}
        print("Official market history safely stopped: " + reason)
    finally:
        (args.diagnostics / "market-history-status.json").write_text(
            json.dumps(diagnostic, ensure_ascii=False, indent=2),
            encoding="utf-8")
    return exit_status


if __name__ == "__main__":
    raise SystemExit(main())
