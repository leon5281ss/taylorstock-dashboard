"""Research-only official TWSE/TPEx historical net institutional flow ingestion.

Validated by field positions, buy - sell == net, foreign/dealer group totals,
official response dates and current official company rosters. Uses dated
exchange website APIs, NEVER current-only OpenAPI as historical source.
"""
import argparse
from datetime import date
import json
import math
from pathlib import Path
import time

from collect_market_history import compressed_snapshot, number, roc_to_iso
from market_pipeline.quant_screen import official_universe
from probe_institutional_history import dated_url, table_from_source
from quant_run import fetch_json, fetch_csv, fetch_text


class InstitutionalError(Exception):
    pass


TPEX_TRIPLE = ("買進股數", "賣出股數", "買賣超股數")
TPEX_HEADERS = ["代號", "名稱"] + list(TPEX_TRIPLE) * 7 + ["三大法人買賣超股數合計"]
TWSE_INDEX_HEADER = {
    0: "證券代號",
    4: "外陸資買賣超股數(不含外資自營商)",
    7: "外資自營商買賣超股數",
    10: "投信買賣超股數",
    11: "自營商買賣超股數",
    14: "自營商買賣超股數(自行買賣)",
    17: "自營商買賣超股數(避險)",
    18: "三大法人買賣超股數",
}


def safe_int(value):
    n = number(value, integer=True)
    if n is None or isinstance(n, bool) or not isinstance(n, int):
        return None
    return n


def normalized_rows(payload, market, day, roster, min_coverage=0.65):
    try:
        fields, rows = table_from_source(payload, market)
    except Exception as exc:
        raise InstitutionalError("invalid_institutional_table_" + market) from exc
    raw_date = payload.get("date") or payload.get("Date")
    if not raw_date:
        raise InstitutionalError("institutional_response_date_missing_" + market)
    try:
        official_date = roc_to_iso(raw_date)
    except Exception as exc:
        raise InstitutionalError("invalid_institutional_response_date_" + market) from exc
    if official_date != day:
        raise InstitutionalError("institutional_response_date_mismatch_" + market)
    if market == "TWSE":
        if len(fields) != 19 or any(fields[i] != expected
                                   for i, expected in TWSE_INDEX_HEADER.items()):
            raise InstitutionalError("twse_institutional_fields_changed")
    elif market == "TPEX":
        if fields != TPEX_HEADERS:
            raise InstitutionalError("tpex_institutional_positions_changed")
    else:
        raise InstitutionalError("unsupported_market")
    records, seen = [], set()
    for raw in rows:
        code = str(raw[0]).strip()
        if code not in roster:
            continue
        if code in seen:
            raise InstitutionalError("duplicate_institutional_company_code_" + market)
        seen.add(code)
        ints = [safe_int(v) for v in raw[2:]]
        if None in ints:
            # Missing or not-reported values are NOT fabricated as zero.
            continue
        if market == "TWSE":
            v = lambda i: ints[i - 2]
            invariant = all((
                v(2)-v(3) == v(4),
                v(5)-v(6) == v(7),
                v(8)-v(9) == v(10),
                v(12)-v(13) == v(14),
                v(15)-v(16) == v(17),
                v(14)+v(17) == v(11),
                v(4)+v(10)+v(11) == v(18),
            ))
            foreign, trust, dealer, total = v(4), v(10), v(11), v(18)
            foreign_dealer, self_net, hedge = v(7), v(14), v(17)
        else:
            v = lambda i: ints[i - 2]
            triples = [v(i)-v(i+1) == v(i+2) for i in range(2, 23, 3)]
            invariant = all(triples) and (
                v(4)+v(7) == v(10) and
                v(16)+v(19) == v(22) and
                v(4)+v(13)+v(22) == v(23))
            foreign, trust, dealer, total = v(4), v(13), v(22), v(23)
            foreign_dealer, self_net, hedge = v(7), v(16), v(19)
        if not invariant:
            raise InstitutionalError("institutional_accounting_invariant_failed_" + market)
        records.append({"market": market, "code": code,
                        "foreignNet": foreign, "trustNet": trust,
                        "dealerNet": dealer, "totalNet": total,
                        "foreignDealerNetNotAddedToForeign": foreign_dealer,
                        "dealerSelfNet": self_net, "dealerHedgeNet": hedge})
    if len(roster) == 0 or len(records) < math.ceil(len(roster)*min_coverage):
        raise InstitutionalError("institutional_company_coverage_insufficient_" + market)
    return sorted(records, key=lambda r: r["code"])


def official_institutional_day(day, *, fetch=fetch_text,
                               roster_json=fetch_json, roster_csv=fetch_csv,
                               company_universe=None, sleep=time.sleep, delay=2.5,
                               min_coverage=0.65):
    if delay < 2.5:
        raise InstitutionalError("rate_limit_required")
    date.fromisoformat(day)
    universe = company_universe if company_universe is not None else official_universe(roster_json, roster_csv)
    if universe.get("errors"):
        raise InstitutionalError("official_company_roster_unavailable")
    parsed = {}
    for market in ("TWSE", "TPEX"):
        sleep(delay)
        source = json.loads(fetch(dated_url(market, day)))
        parsed[market] = normalized_rows(source, market, day,
                                         universe["markets"][market],
                                         min_coverage=min_coverage)
    all_rows = parsed["TWSE"] + parsed["TPEX"]
    return {
        "schemaVersion": 1, "asOf": day,
        "status": "institutional_history_research_only",
        "sourceDateEvidence": {"TWSE": "explicit_response_date",
                               "TPEX": "explicit_response_date"},
        "sources": {market: dated_url(market, day) for market in ("TWSE", "TPEX")},
        "marketCounts": {market: len(rows) for market, rows in parsed.items()},
        "historicalPointInTimeCompanyUniverse": False,
        "allNetUnits": "shares",
        "rosterBasedOnCurrentCompanies": True,
        "officialQuoteVolumeScopeComparable": False,
        "corporateActionPricesAdjusted": False,
        "financialAndTdccFactorReady": False,
        "institutionalAccountIdentitiesVerified": True,
        "rows": sorted(all_rows, key=lambda r: (r["market"], r["code"])),
        "top10": None, "publishable": False,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--day", default="2026-11-13")
    p.add_argument("--output", type=Path, default=Path("institutional-output"))
    p.add_argument("--research-dir", type=Path, default=Path("data/institutional_research"))
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    try:
        payload = official_institutional_day(args.day)
        path = args.research_dir / (payload["asOf"] + ".json.gz")
        path.parent.mkdir(parents=True, exist_ok=True)
        packed = compressed_snapshot(payload)
        if path.exists() and path.read_bytes() != packed:
            raise InstitutionalError("existing_institutional_archive_mismatch")
        if not path.exists():
            path.write_bytes(packed)
        report = {"status": "archived", "date": args.day,
                  "marketCounts": payload["marketCounts"],
                  "sourceDateEvidence": payload["sourceDateEvidence"],
                  "safety": payload["status"], "publishable": False}
        status = 0
        print("Official historical institutional flow researched: " +
              str(payload["marketCounts"]) + "; NO TOP10")
    except (InstitutionalError, OSError, ValueError, TypeError, KeyError) as exc:
        report = {"status": "failed", "reason": str(exc) if isinstance(exc, InstitutionalError)
                  else "official_source_schema_or_network_error",
                  "publishable": False}
        status = 1
        print("Institutional historical archive safely rejected: " + report["reason"])
    (args.output / "institutional-history-status.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
