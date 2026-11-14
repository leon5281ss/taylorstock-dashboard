"""Read-only dated margin-balance source probe (not a trading factor).

A historical JSON endpoint is acceptable only if different requested dates
produce different valid official data and response-date evidence is recorded.
This deliberately does not map shares versus lots or score a company.
"""
import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
import time
from urllib.parse import urlencode

from collect_market_history import roc_to_iso
from quant_run import fetch_text


TWSE = "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN"
TPEX = "https://www.tpex.org.tw/www/zh-tw/margin/balance"


class MarginProbeError(Exception):
    pass


def dated_url(market, day):
    d = date.fromisoformat(day)
    if market == "TWSE":
        return TWSE + "?" + urlencode({"date": d.strftime("%Y%m%d"),
                                      "selectType": "ALL", "response": "json"})
    if market == "TPEX":
        return TPEX + "?" + urlencode({"date": f"{d.year-1911}/{d.month:02d}/{d.day:02d}",
                                      "type": "EW", "response": "json"})
    raise MarginProbeError("unknown_market")


def inspect_response(payload, market, day, minimum=200):
    if not isinstance(payload, dict):
        raise MarginProbeError("source_must_return_object_"+market)
    if str(payload.get("stat", "")).lower() != "ok":
        raise MarginProbeError("source_not_ok_"+market)
    tables = payload.get("tables")
    if not isinstance(tables, list):
        tables = [payload]
    candidates = []
    for t in tables:
        if not isinstance(t, dict):
            continue
        fields, rows = t.get("fields"), t.get("data")
        if not isinstance(fields, list) or not isinstance(rows, list):
            continue
        if len(fields) < 8 or len(rows) < minimum:
            continue
        if any(not isinstance(row, list) or len(row) != len(fields) for row in rows):
            raise MarginProbeError("margin_row_schema_invalid_"+market)
        candidates.append((fields, rows))
    if not candidates:
        raise MarginProbeError("margin_company_table_missing_"+market)
    fields, rows = max(candidates, key=lambda x: len(x[1]))
    response_date = payload.get("date") or payload.get("Date")
    if response_date is None:
        evidence = "query_only_unverified"
    else:
        try:
            normalized = roc_to_iso(response_date)
        except Exception as exc:
            raise MarginProbeError("source_date_format_invalid_"+market) from exc
        if normalized != day:
            raise MarginProbeError("source_date_mismatch_"+market)
        evidence = "explicit_response_date"
    return {
        "requestedDate": day,
        "sourceDateEvidence": evidence,
        "rows": len(rows),
        "columns": len(fields),
        "columnNames": [str(x) for x in fields],
        "duplicateFieldNames": len({str(x) for x in fields}) != len(fields),
        "responseSha256": hashlib.sha256(
            json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "unitIdentityVerified": False,
        "companyMarketCoverageVerified": False,
    }


def probe(dates, fetch=fetch_text, sleep=time.sleep, delay=2.5, minimum=200):
    if delay < 2.5 or len(dates) != 2 or dates != sorted(set(dates)):
        raise MarginProbeError("two_distinct_ordered_days_and_rate_limit_required")
    result = {}
    for market in ("TWSE", "TPEX"):
        results = []
        for d in dates:
            sleep(delay)
            response = json.loads(fetch(dated_url(market, d)))
            results.append(inspect_response(response, market, d, minimum=minimum))
        if results[0]["responseSha256"] == results[1]["responseSha256"]:
            raise MarginProbeError("historical_dates_not_proven_"+market)
        result[market] = {"days": results, "datedDataDifferenceObserved": True}
    return {"status": "historical_margin_source_probe_research_only",
            "dates": dates, "markets": result,
            "marginLotsVsSharesVerified": False,
            "borrowedShareAndSettlementReportingLagVerified": False,
            "canMergeWithInstitutionalOrPriceFactors": False,
            "top10": None, "publishable": False}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--first-day", default="2026-11-12")
    p.add_argument("--second-day", default="2026-11-13")
    p.add_argument("--output", type=Path, default=Path("margin-source-output"))
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    try:
        result = probe([a.first_day, a.second_day])
        code = 0
        print("TWSE/TPEx margin source dated response variation confirmed, "
              "UNIT AND TRADE FACTOR UNVERIFIED")
    except (MarginProbeError, ValueError, OSError, TypeError, KeyError) as e:
        result = {"status": "failed", "reason": str(e) if isinstance(
            e, MarginProbeError) else "source_or_schema_unavailable",
                  "top10": None, "publishable": False}
        code = 1
        print("Margin historical source safely stopped:", result["reason"])
    (a.output/"margin-source-probe.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
