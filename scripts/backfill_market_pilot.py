"""Conservative, bounded official-history backfill PILOT.

Historical TPEx whole-market quotes use ROUND-LOT shares/turnover while its
newest-day OpenAPI includes other sessions. Archive separately; never silently
mix these rows into live archives or use for trade recommendations.
"""
import argparse
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from collect_market_history import compressed_snapshot, number, roc_to_iso
from market_pipeline.quant_screen import official_universe
from quant_run import fetch_json, fetch_csv, fetch_text


TWSE_BASE = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
TPEX_BASE = "https://www.tpex.org.tw/www/zh-tw/afterTrading/otc"
REQUIRED = {
    "TWSE": ("證券代號", "成交股數", "成交金額", "開盤價", "最高價", "最低價", "收盤價"),
    "TPEX": ("代號", "成交股數", "成交金額(元)", "開盤", "最高", "最低", "收盤"),
}
MINIMUM_ROSTER = {"TWSE": 1000, "TPEX": 700}


class PilotError(Exception):
    pass


def normalize_header(value):
    """Normalize spaces/markup in public exchange column names."""
    return re.sub(r"\s+", "", re.sub(r"<[^>]*>", "", str(value))).replace("（", "(").replace("）", ")")


def tables(response, market):
    """Select the exact intended quote table, not an unstable table index."""
    if not isinstance(response, dict):
        raise PilotError("invalid_response_type_" + market)
    status = str(response.get("stat", "")).lower()
    if status not in ("ok",):
        raise PilotError("source_not_ok_" + market)
    candidates = list(response.get("tables") or [])
    if market == "TWSE" and not candidates:
        for i in range(1, 30):
            if isinstance(response.get("fields" + str(i)), list):
                candidates.append({"fields": response["fields" + str(i)],
                                   "data": response.get("data" + str(i), [])})
    desired = set(REQUIRED[market])
    matches = []
    for tab in candidates:
        if not isinstance(tab, dict):
            continue
        fields = [normalize_header(x) for x in tab.get("fields", [])]
        if market == "TPEX":
            # Trading-value labels vary slightly by TPEx page version.
            fields = ["成交金額(元)" if x == "成交金額" else x for x in fields]
        if len(fields) == len(set(fields)) and desired.issubset(set(fields)):
            matches.append((fields, tab.get("data", [])))
    if len(matches) != 1:
        raise PilotError("unknown_or_ambiguous_quote_table_" + market)
    names, rows = matches[0]
    if not isinstance(rows, list) or not rows:
        raise PilotError("empty_quote_table_" + market)
    return names, rows


def _source_date(response, requested):
    """Verify official response date when explicitly supplied; otherwise label."""
    raw = response.get("date") or response.get("Date")
    if raw is None or raw == "":
        return "query_only_unverified"
    try:
        parsed = roc_to_iso(raw)
    except ValueError as e:
        raise PilotError("unrecognized_official_response_date") from e
    if parsed != requested:
        raise PilotError("official_response_date_mismatch")
    return "explicit_response_date"


def records(response, market, requested, roster, minimum_ratio=0.75):
    names, rows = tables(response, market)
    if len(roster) < MINIMUM_ROSTER[market]:
        raise PilotError("official_roster_too_small_" + market)
    response_evidence = _source_date(response, requested)
    result, seen = [], set()
    for raw in rows:
        if not isinstance(raw, (list, tuple)) or len(raw) != len(names):
            raise PilotError("quote_row_schema_mismatch_" + market)
        row = dict(zip(names, raw))
        code = str(row["證券代號" if market == "TWSE" else "代號"]).strip()
        if code not in roster:
            continue
        if code in seen:
            raise PilotError("duplicate_quote_symbol_" + market)
        seen.add(code)
        mapping = {
            "open": "開盤價" if market == "TWSE" else "開盤",
            "high": "最高價" if market == "TWSE" else "最高",
            "low": "最低價" if market == "TWSE" else "最低",
            "close": "收盤價" if market == "TWSE" else "收盤",
            "volume": "成交股數",
            "turnover": "成交金額" if market == "TWSE" else "成交金額(元)",
        }
        prices = {k: number(row[v], integer=k in ("volume", "turnover"))
                  for k, v in mapping.items()}
        if None in prices.values():
            continue  # missing trades never coerced to zero
        if min(prices["open"], prices["high"], prices["low"], prices["close"]) <= 0:
            continue
        if min(prices["volume"], prices["turnover"]) < 0:
            raise PilotError("negative_trade_size_" + market)
        if (prices["high"] < max(prices["open"], prices["close"], prices["low"]) or
                prices["low"] > min(prices["open"], prices["close"], prices["high"])):
            raise PilotError("invalid_ohlc_" + market)
        result.append({"code": code, "market": market, **prices})
    if len(result) < int(len(roster) * minimum_ratio):
        raise PilotError("incomplete_historical_coverage_" + market)
    return {"rows": sorted(result, key=lambda r: r["code"]),
            "quoted": len(result),
            "roster": len(roster),
            "sourceDateEvidence": response_evidence,
            "volumeScope": "twse_all_trades_shares" if market == "TWSE"
            else "tpex_round_lot_shares"}


def url_for(market, day):
    actual = date.fromisoformat(day)
    if market == "TWSE":
        return TWSE_BASE + "?" + urlencode({
            "date": actual.strftime("%Y%m%d"), "type": "ALLBUT0999", "response": "json"})
    return TPEX_BASE + "?" + urlencode({
        "date": actual.strftime("%Y/%m/%d"), "type": "EW", "response": "json"})


def combine(day, universe, responses):
    if universe.get("errors"):
        raise PilotError("invalid_current_official_roster")
    markets = {
        m: records(responses[m], m, day, universe["markets"][m])
        for m in ("TWSE", "TPEX")
    }
    if set(universe["markets"]["TWSE"]) & set(universe["markets"]["TPEX"]):
        raise PilotError("cross_market_symbol_overlap")
    return {
        "schemaVersion": 1, "asOf": day, "priceAdjustment": "raw_unadjusted",
        "status": "historical_pilot_research_only",
        "pointInTimeUniverse": False,
        "mixedVolumeWithDailyOpenAPI": False,
        "sources": {"TWSE": url_for("TWSE", day),
                    "TPEX": url_for("TPEX", day)},
        "sourceDateEvidence": {m: markets[m]["sourceDateEvidence"] for m in markets},
        "volumeScopes": {m: markets[m]["volumeScope"] for m in markets},
        "marketCounts": {m: markets[m]["quoted"] for m in markets},
        "rosterCounts": {m: markets[m]["roster"] for m in markets},
        "stocks": sorted(markets["TWSE"]["rows"] + markets["TPEX"]["rows"],
                         key=lambda x: (x["market"], x["code"])),
    }


def pilot_dates(start, end, archive_dir, daily_dir, max_days=5):
    """Recent-only pilot; no collision with existing production snapshots."""
    try:
        start_d, end_d = date.fromisoformat(start), date.fromisoformat(end)
    except ValueError:
        raise PilotError("invalid_pilot_date") from None
    if start_d > end_d or (end_d - start_d).days > 15:
        raise PilotError("pilot_window_exceeds_15_calendar_days")
    current = date.today()
    if end_d >= current:
        raise PilotError("pilot_requires_past_days")
    existing = sorted(Path(daily_dir).glob("*.json.gz"))
    if not existing:
        raise PilotError("requires_existing_live_archive")
    first_day = date.fromisoformat(existing[0].name[:-8])
    if end_d >= first_day or start_d < first_day - timedelta(days=60):
        raise PilotError("pilot_requires_recent_prearchive_dates")
    days = [start_d + timedelta(days=i) for i in range((end_d-start_d).days+1)]
    weekdays = [d.isoformat() for d in days if d.weekday() < 5]
    if not weekdays or len(weekdays) > max_days:
        raise PilotError("pilot_day_count_out_of_bounds")
    return [d for d in weekdays if not (Path(archive_dir)/(d+".json.gz")).exists()]


def run(start, end, archive_dir, daily_dir, fetch, sleep, delay=2.5):
    days = pilot_dates(start, end, archive_dir, daily_dir)
    if not days:
        return {"status": "already_archived", "processed": 0, "days": []}
    universe = official_universe(fetch_json, fetch_csv)
    if universe.get("errors"):
        raise PilotError("official_company_roster_unavailable")
    saved = []
    for day in days:
        responses = {}
        for market in ("TWSE", "TPEX"):
            sleep(delay)
            result = fetch(url_for(market, day))
            responses[market] = json.loads(result)
        snapshot = combine(day, universe, responses)
        output = Path(archive_dir)/(day+".json.gz")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(compressed_snapshot(snapshot))
        saved.append({"date": day, "counts": snapshot["marketCounts"],
                      "sourceDateEvidence": snapshot["sourceDateEvidence"]})
    return {"status": "pilot_only", "processed": len(saved), "days": saved}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date", default="2026-11-04")
    parser.add_argument("--end-date", default="2026-11-10")
    parser.add_argument("--archive-dir", type=Path, default=Path("data/market_backfill_pilot"))
    parser.add_argument("--daily-dir", type=Path, default=Path("data/market_daily"))
    parser.add_argument("--diagnostics", type=Path, default=Path("pilot-output"))
    args = parser.parse_args()
    args.diagnostics.mkdir(parents=True, exist_ok=True)
    try:
        result = run(args.start_date, args.end_date, args.archive_dir, args.daily_dir,
                     fetch_text, time.sleep)
        print("Official history pilot: " + result["status"] + "; " +
              str(result["processed"]) + " archived; NO RANKING")
        code = 0
    except (PilotError, OSError, ValueError, TypeError, KeyError) as e:
        result = {"status": "failed",
                  "reason": str(e) if isinstance(e, PilotError) else "source_network_or_schema_failure",
                  "processed": None}
        print("Official history pilot safely stopped: " + result["reason"])
        code = 1
    (args.diagnostics/"history-pilot-status.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
