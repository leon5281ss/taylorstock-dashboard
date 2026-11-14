"""Source-segregated margin / short-sale financing balance research.

TWSE individual balance fields are repeated and its trading-unit denominator
is not presumed to be shares. TPEx balance fields explicitly label lots.
No cross-market balance ratios, intraday signals, or historical returns.
"""
import argparse
from datetime import date
import json
from pathlib import Path
import time

from collect_market_history import compressed_snapshot, number, roc_to_iso
from market_pipeline.quant_screen import official_universe
from probe_margin_history import dated_url, inspect_response
from quant_run import fetch_csv, fetch_json, fetch_text


class MarginHistoryError(Exception):
    pass


TWSE_FIELDS = ["代號", "名稱", "買進", "賣出", "現金償還",
               "前日餘額", "今日餘額", "次一營業日限額",
               "買進", "賣出", "現券償還", "前日餘額",
               "今日餘額", "次一營業日限額", "資券互抵", "註記"]
TPEX_FIELDS = ["代號", "名稱", "前資餘額(張)", "資買", "資賣", "現償",
               "資餘額", "資屬證金", "資使用率(%)", "資限額",
               "前券餘額(張)", "券賣", "券買", "券償",
               "券餘額", "券屬證金", "券使用率(%)", "券限額",
               "資券相抵(張)", "備註"]


def parse_market(payload, market, day, roster, *, minimum_coverage=0.60):
    # Probe already confirms dated source and identifies largest legal table.
    try:
        info = inspect_response(payload, market, day, minimum=200)
    except Exception as e:
        raise MarginHistoryError("official_margin_source_invalid_"+market) from e
    if info["sourceDateEvidence"] != "explicit_response_date":
        raise MarginHistoryError("explicit_official_margin_date_required_"+market)
    expected = TWSE_FIELDS if market == "TWSE" else TPEX_FIELDS
    raw_tables = payload.get("tables")
    tables = raw_tables if isinstance(raw_tables, list) else [payload]
    tables = [t for t in tables if isinstance(t, dict)
              and isinstance(t.get("fields"), list)
              and isinstance(t.get("data"), list)
              and len(t["data"]) >= 200]
    if not tables:
        raise MarginHistoryError("margin_company_table_missing_"+market)
    tab = max(tables, key=lambda x: len(x["data"]))
    if tab["fields"] != expected:
        raise MarginHistoryError("official_margin_column_order_changed_"+market)
    indices = ((5, 6, 11, 12) if market == "TWSE" else (2, 6, 10, 14))
    out, seen = [], set()
    for row in tab["data"]:
        if not isinstance(row, list) or len(row) != len(expected):
            raise MarginHistoryError("margin_row_length_invalid_"+market)
        code = str(row[0]).strip()
        if code not in roster:
            continue
        if code in seen:
            raise MarginHistoryError("duplicate_margin_symbol_"+market)
        seen.add(code)
        vals = [number(row[i], integer=True) for i in indices]
        if None in vals:
            continue  # blank report is NOT a zero balance
        if any(type(x) is not int or x < 0 for x in vals):
            raise MarginHistoryError("margin_negative_or_invalid_balance_"+market)
        out.append({
            "market": market, "code": code,
            "marginPrevious": vals[0], "marginCurrent": vals[1],
            "shortPrevious": vals[2], "shortCurrent": vals[3],
            "sourceBalanceUnit": ("twse_trading_unit_not_proven_shares"
                                  if market == "TWSE" else "tpex_explicit_lots"),
            "currentBalancePublicationTimingVerified": False,
        })
    if not roster or len(out) < len(roster)*minimum_coverage:
        raise MarginHistoryError("margin_company_coverage_low_"+market)
    return sorted(out, key=lambda row: row["code"])


def collect(day, *, fetch=fetch_text, json_fetch=fetch_json,
            csv_fetch=fetch_csv, sleep=time.sleep, delay=2.5):
    if delay < 2.5:
        raise MarginHistoryError("minimum_source_delay_required")
    date.fromisoformat(day)
    universe = official_universe(json_fetch, csv_fetch)
    if universe.get("errors"):
        raise MarginHistoryError("official_current_company_roster_unavailable")
    groups = {}
    for market in ("TWSE", "TPEX"):
        sleep(delay)
        payload = json.loads(fetch(dated_url(market, day)))
        groups[market] = parse_market(payload, market, day,
                                      universe["markets"][market])
    return {
        "schemaVersion": 1,
        "status": "margin_balance_history_research_only",
        "asOf": day,
        "marketCounts": {m: len(v) for m, v in groups.items()},
        "sources": {m: dated_url(m, day) for m in ("TWSE", "TPEX")},
        "officialSourceDateExplicit": True,
        "unitsNotCrossMarketNormalized": True,
        "pointInTimeCompanyUniverseVerified": False,
        "priorBalancePublishedOnSameDateVerified": False,
        "currentBalanceAvailableDuringTradingSession": False,
        "sourceBalanceSharesConverted": False,
        "marginFactorReady": False,
        "rows": groups["TWSE"]+groups["TPEX"],
        "top10": None, "publishable": False,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--day", default="2026-11-13")
    p.add_argument("--research-dir", type=Path, default=Path("data/margin_research"))
    p.add_argument("--output", type=Path, default=Path("margin-research-output"))
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    try:
        result = collect(args.day)
        output = args.research_dir/(args.day+".json.gz")
        output.parent.mkdir(parents=True, exist_ok=True)
        packed = compressed_snapshot(result)
        if output.exists() and output.read_bytes() != packed:
            raise MarginHistoryError("existing_margin_research_file_differs")
        if not output.exists():
            output.write_bytes(packed)
        diagnostic = {"status": "archived", "date": args.day,
                      "counts": result["marketCounts"],
                      "balanceUnitsUnverified": True,
                      "top10": None, "publishable": False}
        status = 0
        print("Official margin balance research:", result["marketCounts"],
              "UNCONVERTED UNITS, NO TOP10")
    except (MarginHistoryError, OSError, ValueError, TypeError, KeyError) as e:
        diagnostic = {"status": "failed", "reason": str(e) if isinstance(
            e, MarginHistoryError) else "source_or_schema_unavailable",
                      "top10": None, "publishable": False}
        status = 1
        print("Official margin research safely stopped:", diagnostic["reason"])
    (args.output/"margin-research-status.json").write_text(
        json.dumps(diagnostic, ensure_ascii=False, indent=2), encoding="utf-8")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
