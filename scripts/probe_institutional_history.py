"""Fail-closed probe of two dated official TWSE/TPEx institutional data feeds.

This is a source RECONNAISSANCE, not an institutional factor pipeline:
no quote archive updates, no historical ranking, no Telegram signals.
"""
import argparse
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import time
from urllib.parse import urlencode

from collect_market_history import roc_to_iso
from quant_run import fetch_text


TWSE_URL = "https://www.twse.com.tw/rwd/zh/fund/T86"
TPEX_URL = "https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade"


class SourceProbeError(Exception):
    pass


def dated_url(market, day):
    d = date.fromisoformat(day)
    if market == "TWSE":
        return TWSE_URL + "?" + urlencode({
            "date": d.strftime("%Y%m%d"),
            "selectType": "ALLBUT0999", "response": "json"})
    if market == "TPEX":
        roc = d.year - 1911
        if roc <= 0:
            raise SourceProbeError("tpex_roc_year_invalid")
        return TPEX_URL + "?" + urlencode({
            "type": "Daily", "sect": "EW",
            "date": f"{roc}/{d.month:02d}/{d.day:02d}",
            "id": "", "response": "json"})
    raise SourceProbeError("unknown_exchange")


def table_from_source(payload, market):
    if not isinstance(payload, dict):
        raise SourceProbeError("institutional_response_not_object_" + market)
    if str(payload.get("stat", "")).lower() != "ok":
        raise SourceProbeError("institutional_stat_not_ok_" + market)
    if market == "TWSE":
        candidates = [payload]
    else:
        candidates = payload.get("tables", [])
        if not isinstance(candidates, list):
            raise SourceProbeError("tpex_table_schema_invalid")
    available = []
    for table in candidates:
        if not isinstance(table, dict):
            continue
        fields, rows = table.get("fields"), table.get("data")
        if not isinstance(fields, list) or not isinstance(rows, list):
            continue
        if not rows or not fields:
            continue
        if not all(isinstance(row, (list, tuple)) and len(row) == len(fields)
                   for row in rows):
            raise SourceProbeError("institutional_row_length_mismatch_" + market)
        available.append((fields, rows))
    if not available:
        raise SourceProbeError("missing_institutional_quote_table_" + market)
    # Probe permits repeated column labels: TPEx can repeat buy/sell/net columns.
    return max(available, key=lambda pair: len(pair[1]))


def inspect_day(payload, market, day, min_rows=250):
    fields, rows = table_from_source(payload, market)
    if len(rows) < min_rows:
        raise SourceProbeError("institutional_source_coverage_too_low_" + market)
    reported = payload.get("date") or payload.get("Date")
    if reported is None:
        date_evidence = "query_only_unverified"
    else:
        try:
            actual = roc_to_iso(reported)
        except Exception:
            date_evidence = "unparseable_response_date"
        else:
            if actual != day:
                raise SourceProbeError("institutional_response_date_mismatch_" + market)
            date_evidence = "explicit_response_date"
    fingerprint = hashlib.sha256(
        json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "requestedDate": day, "sourceDateEvidence": date_evidence,
        "tableRows": len(rows), "columnCount": len(fields),
        "columnNames": [str(x) for x in fields],
        "hasRepeatedColumnNames": len(set(str(x) for x in fields)) < len(fields),
        "dataFingerprintSha256": fingerprint,
    }


def probe(days, fetch=fetch_text, sleep=time.sleep, delay=2.5, min_rows=250):
    if delay < 2.5:
        raise SourceProbeError("rate_limit_required")
    if not isinstance(days, list) or len(days) != 2:
        raise SourceProbeError("exactly_two_dates_required")
    if days != sorted(set(days)):
        raise SourceProbeError("days_need_strict_order")
    dates = [date.fromisoformat(day) for day in days]
    if (dates[1] - dates[0]).days > 7:
        raise SourceProbeError("too_much_gap_between_probe_dates")
    sources = {}
    for market in ("TWSE", "TPEX"):
        results = []
        for d in days:
            sleep(delay)
            source = json.loads(fetch(dated_url(market, d)))
            results.append(inspect_day(source, market, d, min_rows=min_rows))
        if results[0]["dataFingerprintSha256"] == results[1]["dataFingerprintSha256"]:
            raise SourceProbeError("dated_request_not_proven_" + market)
        sources[market] = {
            "baseUrl": TWSE_URL if market == "TWSE" else TPEX_URL,
            "dailyResponsesDistinct": True,
            "days": results,
            "fullMarketCompanyCoverageVerified": False,
            "netBuyerColumnsMappedAndAudited": False,
        }
    return {
        "status": "dated_source_variation_confirmed_research_only",
        "markets": sources, "dates": days,
        "dataMergeAllowed": False, "publishable": False, "top10": None,
        "risks": [
            "TPEx_may_repeat_column_names_and_category_tables",
            "historical_codes_are_not_point_in_time_company_universe",
            "foreign_net_buy_not_foreign_gross_buy_or_foreign_dealer_net",
            "data_fingerprint_difference_does_not_prove_all_row_dates",
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date-one", default="2026-11-12")
    parser.add_argument("--date-two", default="2026-11-13")
    parser.add_argument("--output", type=Path, default=Path("institutional-probe-output"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    try:
        result = probe([args.date_one, args.date_two])
        status = 0
        print("Official institutional history probe: market table fingerprints differ by day; "
              "COLUMN MAPPING AND TOP10 STILL BLOCKED")
    except (SourceProbeError, OSError, ValueError, TypeError, KeyError) as exc:
        result = {
            "status": "failed", "reason": str(exc) if isinstance(exc, SourceProbeError)
            else "official_institutional_source_or_schema_failure",
            "dataMergeAllowed": False, "top10": None, "publishable": False}
        status = 1
        print("Institutional source probe stopped safely: " + result["reason"])
    (args.output / "institutional-source-probe.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
