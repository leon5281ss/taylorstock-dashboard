"""Read-only official daily valuation source probe: NOT fundamental PIT backtesting.

A historical P/E/P/B/Yield panel can be dated and still cannot prove when the
underlying issuer earnings and dividend statements were actually disclosed.
"""
import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
import time
from urllib.parse import urlencode

from quant_run import fetch_text


TWSE_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d"
TPEX_URL = ("https://www.tpex.org.tw/web/stock/aftertrading/"
            "peratio_analysis/pera_result.php")


class ValuationProbeError(Exception):
    pass


def source_url(market, day):
    date_obj = date.fromisoformat(day)
    if market == "TWSE":
        return TWSE_URL + "?" + urlencode({
            "date": date_obj.strftime("%Y%m%d"),
            "selectType": "ALL", "response": "json"})
    if market == "TPEX":
        return TPEX_URL + "?" + urlencode({
            "l": "zh-tw", "d": f"{date_obj.year-1911}/{date_obj.month:02}/{date_obj.day:02}",
            "o": "json"})
    raise ValuationProbeError("invalid_market")


def inspect(payload, market, day, min_rows=300):
    if not isinstance(payload, dict):
        raise ValuationProbeError("valuation_response_must_be_dict")
    # Log shape only (keys, row counts, types), never raw financial values.
    # This identifies provider-side API migrations without swallowing errors.
    shape = {
        "keys": sorted(payload.keys())[:16],
        "aaRows": len(payload["aaData"]) if isinstance(payload.get("aaData"), list) else None,
        "iTotalRecordsType": type(payload.get("iTotalRecords")).__name__,
        "tables": len(payload["tables"]) if isinstance(payload.get("tables"), list) else None,
        "firstTableFields": (len(payload["tables"][0].get("fields", []))
                             if isinstance(payload.get("tables"), list)
                             and payload["tables"] and isinstance(payload["tables"][0], dict) else None),
        "firstTableRows": (len(payload["tables"][0].get("data", []))
                           if isinstance(payload.get("tables"), list)
                           and payload["tables"] and isinstance(payload["tables"][0], dict) else None),
        "aaFirstRowColumns": (len(payload["aaData"][0])
                               if isinstance(payload.get("aaData"), list)
                               and payload["aaData"] and isinstance(payload["aaData"][0], list)
                               else None),
    }
    if market == "TWSE":
        if str(payload.get("stat", "")).lower() != "ok":
            raise ValuationProbeError("twse_valuation_not_ok")
        fields = payload.get("fields")
        rows = payload.get("data")
        if (not isinstance(fields, list) or not isinstance(rows, list)
                or len(fields) < 6 or len(rows) < min_rows):
            raise ValuationProbeError("twse_valuation_schema_or_coverage")
        # Historical table commonly includes code, yield, P/E, and P/B.
        if not ("證券代號" in fields and "本益比" in fields and
                "殖利率(%)" in fields and "股價淨值比" in fields):
            raise ValuationProbeError("twse_valuation_columns_changed")
        codes = [str(r[fields.index("證券代號")]).strip()
                 for r in rows if isinstance(r, list) and len(r) == len(fields)]
    elif market == "TPEX":
        # TPEx now serves the dated valuation report as a table-style JSON:
        # {"date":..., "stat":"ok", "tables":[{"fields":[...],"data":[...]}]}.
        # Retain support for older legacy aaData only if complete.
        if isinstance(payload.get("tables"), list):
            if (str(payload.get("stat", "")).lower() != "ok"
                    or len(payload["tables"]) != 1):
                raise ValuationProbeError("tpex_valuation_stat_or_table_invalid")
            tab = payload["tables"][0]
            fields, rows = tab.get("fields"), tab.get("data")
            if not isinstance(fields, list) or not isinstance(rows, list):
                raise ValuationProbeError("tpex_valuation_schema_or_coverage")
            if not all(isinstance(f, str) for f in fields):
                raise ValuationProbeError("tpex_valuation_columns_invalid")
            code_columns = [i for i, f in enumerate(fields)
                            if f.strip().replace(" ", "") in
                            ("代號", "股票代號", "證券代號")]
            if (len(code_columns) != 1
                    or not any("本益比" in f for f in fields)
                    or not any("殖利率" in f for f in fields)
                    or not any("股價淨值比" in f for f in fields)):
                raise ValuationProbeError("tpex_valuation_columns_changed:" +
                                          json.dumps(fields, ensure_ascii=False))
            if "totalCount" in tab and (
                    not isinstance(tab["totalCount"], int)
                    or tab["totalCount"] != len(rows)):
                raise ValuationProbeError("tpex_valuation_response_truncated")
            if len(rows) < min_rows or any(
                    not isinstance(row, list) or len(row) != len(fields)
                    for row in rows):
                raise ValuationProbeError("tpex_valuation_schema_or_coverage")
            codes = [str(row[code_columns[0]]).strip() for row in rows]
        else:
            rows = payload.get("aaData")
            count = payload.get("iTotalRecords")
            if (not isinstance(rows, list) or not isinstance(count, int)
                    or count != len(rows) or len(rows) < min_rows
                    or any(not isinstance(r, list) or len(r) < 7 for r in rows)):
                raise ValuationProbeError("tpex_valuation_schema_or_coverage:" +
                                          json.dumps(shape, sort_keys=True))
            fields = ["code", "name", "pe", "dividend", "dividendYear", "yield", "pb"]
            codes = [str(r[0]).strip() for r in rows]
    else:
        raise ValuationProbeError("unknown_market")
    if len(codes) != len(rows):
        raise ValuationProbeError("truncated_row_schema")
    matched = [c for c in codes if len(c) == 4 and c.isdigit()]
    if len(set(matched)) < min_rows * .70:
        raise ValuationProbeError("valuation_company_coverage_too_low")
    expected = date.fromisoformat(day).strftime("%Y%m%d")
    if "date" in payload and payload["date"] != expected:
        raise ValuationProbeError("valuation_response_date_mismatch_" + market)
    verified = payload.get("date") == expected
    return {"requestedDate": day,
            "responseDate": day if verified else None,
            "recordCount": len(rows), "fourDigitSymbols": len(set(matched)),
            "columns": fields,
            "rowsSha256": hashlib.sha256(json.dumps(
                rows, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
            "responseDateExplicitlyVerified": verified,
            "issuerStatementPublicReleaseDatesVerified": False,
            "historicalPointInTimeUniverseVerified": False,
            "dailyValuationReadyToRank": False}


def run(first_day, second_day, *, fetch=fetch_text, sleep=time.sleep, delay=3):
    days = [first_day, second_day]
    if (len(set(days)) != 2 or days != sorted(days)
            or delay < 2.5):
        raise ValuationProbeError("requires_two_sorted_days_with_rate_limit")
    groups = {}
    for market in ("TWSE", "TPEX"):
        records = []
        for day in days:
            sleep(delay)
            data = json.loads(fetch(source_url(market, day)))
            record = inspect(data, market, day)
            if not record["responseDateExplicitlyVerified"]:
                raise ValuationProbeError("valuation_response_date_missing_" + market)
            records.append(record)
        if records[0]["rowsSha256"] == records[1]["rowsSha256"]:
            raise ValuationProbeError("two_valuation_days_indistinguishable_" + market)
        groups[market] = records
    return {"status": "dated_valuation_source_probe_research_only",
            "dates": days, "markets": groups,
            "bothHistoricalDatesDiffer": True,
            "responseDateExplicitlyVerified": True,
            "issuerFinancialDisclosureTimingVerified": False,
            "fiveYearEPSAndROEHistoryAvailable": False,
            "corporateActionAdjusted": False,
            "rankable": False, "top10": None, "publishable": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--first-day", default="2026-11-12")
    parser.add_argument("--second-day", default="2026-11-13")
    parser.add_argument("--output", type=Path, default=Path("valuation-probe-output"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    try:
        result = run(args.first_day, args.second_day)
        print("Official dated valuation sources have distinct payloads; "
              "issuer disclosure timing UNVERIFIED; NO TOP10.")
        exit_code = 0
    except (ValuationProbeError, ValueError, TypeError, KeyError, OSError) as exc:
        result = {"status": "failed",
                  "reason": str(exc) if isinstance(exc, ValuationProbeError)
                  else "official_valuation_source_or_schema_error",
                  "top10": None, "publishable": False}
        exit_code = 1
        print("Dated valuation probe safely rejected: " + result["reason"])
    (args.output / "dated-valuation-source-probe.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
