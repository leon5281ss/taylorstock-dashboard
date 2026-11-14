"""Research-only daily price/institutional joint-coverage audit.

All data is explicitly non-point-in-time and unadjusted. Counts stock-symbol
joins by market and date; never produces a factor, signal, ranking or trade.
"""
import argparse
from collections import defaultdict
from datetime import date
import gzip
import json
from pathlib import Path

from research_price_coverage import CoverageError, load_snapshot


class FactorAuditError(Exception):
    pass


def institutional_file(path):
    try:
        blob = json.loads(gzip.decompress(Path(path).read_bytes()))
        day = date.fromisoformat(blob["asOf"]).isoformat()
        if (path.name != day + ".json.gz" or blob.get("schemaVersion") != 1
                or blob.get("status") != "institutional_history_research_only"
                or blob.get("allNetUnits") != "shares"
                or blob.get("sourceDateEvidence") != {"TWSE": "explicit_response_date",
                                                       "TPEX": "explicit_response_date"}
                or blob.get("publishable") is not False
                or blob.get("historicalPointInTimeCompanyUniverse") is not False):
            raise FactorAuditError("institutional_archive_schema_or_date_invalid")
        rows = blob["rows"]
        if not isinstance(rows, list):
            raise FactorAuditError("institutional_rows_not_array")
        counts, by_market = {"TWSE": 0, "TPEX": 0}, {"TWSE": set(), "TPEX": set()}
        for row in rows:
            m, c = row["market"], row["code"]
            if (m not in counts or not isinstance(c, str) or len(c) != 4
                    or not c.isdigit() or c in by_market[m]):
                raise FactorAuditError("institutional_duplicate_or_unknown_symbol")
            by_market[m].add(c)
            counts[m] += 1
            for key in ("foreignNet", "trustNet", "dealerNet", "totalNet",
                        "dealerSelfNet", "dealerHedgeNet"):
                if type(row.get(key)) is not int:
                    raise FactorAuditError("institutional_net_not_verified")
            if (row["foreignNet"] + row["trustNet"] + row["dealerNet"] != row["totalNet"]
                    or row["dealerSelfNet"] + row["dealerHedgeNet"] != row["dealerNet"]):
                raise FactorAuditError("institutional_accounting_mismatch")
        if counts != blob.get("marketCounts") or counts["TWSE"] < 700 or counts["TPEX"] < 500:
            raise FactorAuditError("institutional_coverage_or_counts_invalid")
        return day, by_market, counts
    except (OSError, EOFError, KeyError, ValueError, TypeError, gzip.BadGzipFile) as e:
        raise FactorAuditError("institutional_archive_unreadable") from e


def audit_joint_coverage(daily_dir, research_dir, inst_dir):
    prices = {}
    for research, folder in ((False, daily_dir), (True, research_dir)):
        for p in sorted(Path(folder).glob("*.json.gz")):
            try:
                snapshot = load_snapshot(p, historical=research)
            except CoverageError as e:
                raise FactorAuditError("price_archive_invalid") from e
            d = snapshot["asOf"]
            if d in prices:
                raise FactorAuditError("duplicate_price_source_day")
            prices[d] = {
                "TWSE": {code for m, code in snapshot["closes"] if m == "TWSE"},
                "TPEX": {code for m, code in snapshot["closes"] if m == "TPEX"},
            }
    if not prices:
        raise FactorAuditError("official_price_archives_missing")
    observed = []
    totals = defaultdict(int)
    matched = defaultdict(int)
    for path in sorted(Path(inst_dir).glob("*.json.gz")):
        day, institutional, counts = institutional_file(path)
        if day not in prices:
            raise FactorAuditError("orphan_institutional_research_day")
        shared = {m: len(prices[day][m] & institutional[m]) for m in ("TWSE", "TPEX")}
        if any(shared[m] < 0.60 * len(prices[day][m]) for m in ("TWSE", "TPEX")):
            raise FactorAuditError("joint_price_institutional_coverage_below_60pct")
        for market in shared:
            totals[market] += len(prices[day][market])
            matched[market] += shared[market]
        observed.append({"date": day, "pricedCompanies": {
            m: len(prices[day][m]) for m in shared},
                         "institutionalCompanies": counts,
                         "jointCompanies": shared})
    observed_days = sorted(prices)
    inst_days = {item["date"] for item in observed}
    windows = {}
    for length in (5, 20, 60, 121):
        current = observed_days[-length:]
        windows[str(length)] = {
            "observedPriceDays": len(current),
            "allSelectedDaysHaveInstitutional": (
                len(current) == length and all(d in inst_days for d in current)),
            "sharedCompanyUniverseReady": False,
            "tradableSignalReady": False,
        }
    return {"status": "research_joint_coverage_only",
            "priceObservedDates": len(prices),
            "institutionalObservedDates": len(observed),
            "jointDates": len(inst_days),
            "jointStocksAcrossDates": dict(matched),
            "priceStocksAcrossMatchedDates": dict(totals),
            "mostRecentJointDates": observed[-10:],
            "dateWindows": windows,
            "corporateActionsAdjusted": False,
            "pointInTimeUniverseAvailable": False,
            "sameVolumeDefinitionVerified": False,
            "fullInstitutionalAndFundamentalFactorsAvailable": False,
            "backtestNetOfCostsVerified": False,
            "rankingAllowed": False,
            "top10": None, "publishable": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--daily-dir", type=Path, default=Path("data/market_daily"))
    parser.add_argument("--research-dir", type=Path, default=Path("data/market_backfill_pilot"))
    parser.add_argument("--institutional-dir", type=Path, default=Path("data/institutional_research"))
    parser.add_argument("--output", type=Path, default=Path("factor-joint-output"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    try:
        result = audit_joint_coverage(args.daily_dir, args.research_dir,
                                      args.institutional_dir)
        code = 0
        print("Joint research dates:", result["jointDates"],
              "; price days:", result["priceObservedDates"],
              "; ready-to-rank=FALSE")
    except (FactorAuditError, ValueError, TypeError) as exc:
        result = {"status": "failed",
                  "reason": str(exc) if isinstance(exc, FactorAuditError)
                  else "research_data_validation_failed",
                  "publishable": False, "top10": None}
        code = 1
        print("Joint research audit safely stopped:", result["reason"])
    (args.output / "factor-date-coverage.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
