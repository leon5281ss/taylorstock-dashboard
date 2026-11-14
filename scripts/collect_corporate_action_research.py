"""Research-only normalized official ex-rights/ex-dividend reference events.

A reference-price ratio is NOT a total-return adjustment. Cash/stock
distributions, capital reductions, splits and historic delisted symbols need
separate point-in-time evidence before any backtest or trade recommendation.
"""
import argparse
from datetime import date, datetime
import html
import json
from pathlib import Path
import re
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from collect_market_history import compressed_snapshot, number, roc_to_iso
from market_pipeline.quant_screen import official_universe
from quant_run import fetch_csv, fetch_json, fetch_text


TWSE_ROOT = "https://www.twse.com.tw/rwd/zh/exRight/TWT49U"
TPEX_ROOT = "https://www.tpex.org.tw/www/zh-tw/bulletin/exDailyQ"

COLS = {
    "TWSE": ("資料日期", "股票代號", "除權息前收盤價", "除權息參考價", "權/息"),
    "TPEX": ("除權息日期", "代號", "除權息前收盤價", "除權息參考價", "權/息"),
}


class CorporateError(Exception):
    pass


def normalized_field(value):
    return re.sub(r"\s+", "", re.sub(r"<[^>]*>", "", html.unescape(str(value))))


def corporate_date(value):
    raw = str(value).strip()
    match = re.fullmatch(r"(\d{2,4})年(\d{1,2})月(\d{1,2})日", raw)
    if match:
        year = int(match.group(1))
        year += 1911 if year < 1911 else 0
        try:
            return date(year, int(match.group(2)), int(match.group(3))).isoformat()
        except ValueError as exc:
            raise CorporateError("invalid_corporate_event_date") from exc
    try:
        return roc_to_iso(raw)
    except Exception as exc:
        raise CorporateError("invalid_corporate_event_date") from exc


def request_details(start, end):
    d1, d2 = date.fromisoformat(start), date.fromisoformat(end)
    if d1 > d2 or (d2 - d1).days > 370:
        raise CorporateError("date_window_exceeds_one_year")
    twse_url = TWSE_ROOT + "?" + urlencode({
        "startDate": start.replace("-", ""), "endDate": end.replace("-", ""),
        "response": "json"})
    tpex_form = urlencode({
        "startDate": start.replace("-", "/"), "endDate": end.replace("-", "/"),
        "id": "", "response": "json"})
    return {"TWSE": {"url": twse_url, "method": "GET"},
            "TPEX": {"url": TPEX_ROOT, "method": "POST", "body": tpex_form}}


def official_post(url, form):
    request = Request(
        url, data=form.encode("utf-8"),
        headers={"Accept": "application/json",
                 "Content-Type": "application/x-www-form-urlencoded",
                 "User-Agent": "TaylorStock-Research/0.1"},
        method="POST")
    with urlopen(request, timeout=45) as response:
        return json.loads(response.read().decode("utf-8-sig"))


def source_table(payload, market):
    if not isinstance(payload, dict):
        raise CorporateError("non_object_corporate_response_" + market)
    if market == "TWSE":
        if payload.get("stat") != "OK":
            raise CorporateError("twse_corporate_source_not_ok")
        tab = payload
    else:
        if str(payload.get("stat", "ok")).lower() != "ok":
            raise CorporateError("tpex_corporate_source_not_ok")
        t = payload.get("tables")
        if not isinstance(t, list) or len(t) != 1:
            raise CorporateError("tpex_corporate_table_invalid")
        tab = t[0]
        if "totalCount" not in tab:
            raise CorporateError("tpex_total_count_missing")
        try:
            count = int(tab["totalCount"])
        except (TypeError, ValueError) as exc:
            raise CorporateError("tpex_total_count_invalid") from exc
        if count < 0 or not isinstance(tab.get("data"), list):
            raise CorporateError("tpex_total_count_invalid")
        if len(tab["data"]) != count:
            raise CorporateError("tpex_corporate_response_truncated")
    fields, rows = tab.get("fields"), tab.get("data")
    if not isinstance(fields, list) or not isinstance(rows, list):
        raise CorporateError("corporate_schema_invalid_" + market)
    names = [normalized_field(f) for f in fields]
    if len(names) != len(set(names)) or not set(COLS[market]).issubset(names):
        raise CorporateError("unknown_corporate_schema_" + market)
    if not rows:
        raise CorporateError("empty_corporate_data_" + market)
    return names, rows


def event_records(payload, market, start, end, roster, minimum=1):
    fields, data = source_table(payload, market)
    positions = {name: fields.index(name) for name in COLS[market]}
    result, seen = [], set()
    for cells in data:
        if not isinstance(cells, (list, tuple)) or len(cells) != len(fields):
            raise CorporateError("corporate_row_schema_invalid_" + market)
        code = str(cells[positions[COLS[market][1]]]).strip()
        if code not in roster:
            continue
        stamp = corporate_date(cells[positions[COLS[market][0]]])
        if not start <= stamp <= end:
            raise CorporateError("corporate_event_outside_requested_window")
        old, reference = (number(cells[positions[COLS[market][i]]]) for i in (2, 3))
        kind = str(cells[positions[COLS[market][4]]]).strip().removeprefix("除")
        if old is None or reference is None or old <= 0 or reference <= 0:
            raise CorporateError("corporate_reference_price_invalid")
        if kind not in ("權", "息", "權息"):
            raise CorporateError("unknown_corporate_event_kind")
        key = (market, code, stamp)
        if key in seen:
            raise CorporateError("duplicate_corporate_event_same_symbol_day")
        seen.add(key)
        result.append({
            "market": market, "code": code, "exDate": stamp,
            "previousClose": old, "referencePrice": reference,
            "referenceRatio": round(reference / old, 9),
            "type": kind})
    if len(result) < minimum:
        raise CorporateError("insufficient_matched_corporate_events_" + market)
    return sorted(result, key=lambda row: (row["exDate"], row["code"]))


def research_snapshot(start, end, universe, responses):
    if universe.get("errors"):
        raise CorporateError("company_roster_unavailable")
    data = []
    market_counts = {}
    for market in ("TWSE", "TPEX"):
        rows = event_records(responses[market], market, start, end,
                             universe["markets"][market])
        market_counts[market] = len(rows)
        data += rows
    return {
        "schemaVersion": 1, "status": "corporate_action_reference_research_only",
        "asOf": end, "start": start, "end": end,
        "marketCounts": market_counts,
        "sources": request_details(start, end),
        "events": sorted(data, key=lambda x: (x["exDate"], x["market"], x["code"])),
        "referenceRatioIsNotTotalReturn": True,
        "capitalReductionAndSplitCoverage": False,
        "cashDividendTotalReturnCorrectlyModelled": False,
        "historicalPointInTimeCompanyUniverse": False,
        "adjustedOhlcvReady": False,
        "publishable": False, "top10": None,
    }


def collect(*, today=None, json_fetch=fetch_json, csv_fetch=fetch_csv,
            text_fetch=fetch_text, post=official_post, sleep=time.sleep, delay=3):
    if delay < 2.5:
        raise CorporateError("source_rate_limit_delay_too_short")
    today = today or datetime.now(ZoneInfo("Asia/Taipei")).date()
    start, end = str(today.year) + "-01-01", today.isoformat()
    details = request_details(start, end)
    universe = official_universe(json_fetch, csv_fetch)
    if universe.get("errors"):
        raise CorporateError("company_roster_unavailable")
    try:
        twse = json.loads(text_fetch(details["TWSE"]["url"]))
        sleep(delay)
        tpex = post(details["TPEX"]["url"], details["TPEX"]["body"])
    except (OSError, ValueError, TypeError) as exc:
        raise CorporateError("corporate_api_network_or_json_error") from exc
    return research_snapshot(start, end, universe, {"TWSE": twse, "TPEX": tpex})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive-dir", type=Path, default=Path("data/corporate_action_research"))
    parser.add_argument("--output", type=Path, default=Path("corporate-output"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    try:
        payload = collect()
        path = args.archive_dir / (payload["asOf"][:4] + ".json.gz")
        path.parent.mkdir(parents=True, exist_ok=True)
        content = compressed_snapshot(payload)
        previous = path.read_bytes() if path.exists() else None
        changed = content != previous
        if changed:
            path.write_bytes(content)
        diagnostic = {"status": "archived" if changed else "unchanged",
                      "asOf": payload["asOf"], "events": payload["marketCounts"],
                      "referenceOnly": True, "adjustedOhlcvReady": False,
                      "archive": path.as_posix(), "publishable": False}
        result = 0
        print("Official corporate reference events " + diagnostic["status"] +
              " for " + payload["asOf"] + ": " + str(diagnostic["events"]) +
              "; NOT AN ADJUSTED PRICE SERIES")
    except (CorporateError, ValueError, OSError, KeyError, TypeError) as exc:
        diagnostic = {"status": "failed", "reason": str(exc) if isinstance(exc, CorporateError)
                      else "source_or_schema_invalid", "publishable": False}
        result = 1
        print("Corporate action research safely rejected: " + diagnostic["reason"])
    (args.output / "corporate-reference-status.json").write_text(
        json.dumps(diagnostic, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
