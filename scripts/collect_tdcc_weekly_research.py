"""TDCC official weekly shareholder-distribution research-only snapshot.

Stock ownership concentration is a WEEKLY as-of snapshot, never a daily trade
signal. Parse the official 1-5 CSV, validate the 17 level rows by issuer, and
store only market-wide verified public research after source checks pass.
"""
import argparse
import csv
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
import io
import json
from pathlib import Path
import re
import urllib.request
from zoneinfo import ZoneInfo

from collect_market_history import compressed_snapshot
from market_pipeline.quant_screen import official_universe
from quant_run import fetch_csv, fetch_json


URL = "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5"
FIELDS = ("資料日期", "證券代號", "持股分級", "人數", "股數", "占集保庫存數比例%")
REQUIRED_LEVELS = set(range(1, 18))


class TdccError(Exception):
    pass


def header(value):
    return re.sub(r"\s+", "", str(value).replace("佔", "占").replace("％", "%"))


def integer(value, *, allow_negative=False):
    if value is None or isinstance(value, bool):
        raise TdccError("tdcc_missing_integer")
    cleaned = str(value).strip().replace(",", "")
    if not re.fullmatch(r"-?\d+", cleaned):
        raise TdccError("tdcc_not_an_integer")
    n = int(cleaned)
    if n < 0 and not allow_negative:
        raise TdccError("tdcc_negative_integer")
    return n


def percentage(value):
    try:
        d = Decimal(str(value).strip().replace(",", "").replace("%", ""))
    except (ValueError, InvalidOperation) as exc:
        raise TdccError("tdcc_invalid_percentage") from exc
    if not d.is_finite() or d < Decimal("-100") or d > Decimal("100"):
        raise TdccError("tdcc_percentage_out_of_range")
    return float(d)


def fetch_official_csv():
    request = urllib.request.Request(
        URL, headers={"User-Agent": "TaylorStock-TDCC-Research/0.1",
                      "Accept": "text/csv,text/plain,*/*"})
    with urllib.request.urlopen(request, timeout=100) as response:
        raw = response.read(35_000_000)
    if not raw or len(raw) >= 35_000_000:
        raise TdccError("tdcc_response_empty_or_too_large")
    for codec in ("utf-8-sig", "cp950"):
        try:
            decoded = raw.decode(codec)
            if "資料日期" in decoded[:400] and "證券代號" in decoded[:400]:
                return decoded
        except UnicodeDecodeError:
            continue
    raise TdccError("tdcc_unrecognized_charset_or_header")


def parse_csv(raw, roster, *, now=None, min_companies=1000):
    now = now or datetime.now(ZoneInfo("Asia/Taipei")).date()
    if not isinstance(raw, str) or not raw:
        raise TdccError("tdcc_csv_missing")
    reader = csv.reader(io.StringIO(raw))
    try:
        names = [header(x) for x in next(reader)]
    except StopIteration:
        raise TdccError("tdcc_csv_empty") from None
    if len(names) != len(set(names)) or not set(FIELDS).issubset(names):
        raise TdccError("tdcc_csv_schema_changed")
    index = {name: names.index(name) for name in FIELDS}
    official_codes = set(roster["markets"]["TWSE"]) | set(roster["markets"]["TPEX"])
    buckets = {}
    weekly_date = None
    count = 0
    for row in reader:
        if not row or all(not cell.strip() for cell in row):
            continue
        count += 1
        if len(row) != len(names):
            raise TdccError("tdcc_row_field_count_mismatch")
        raw_day = row[index["資料日期"]].strip()
        if not re.fullmatch(r"\d{8}", raw_day):
            raise TdccError("tdcc_date_format_changed")
        day = date(int(raw_day[:4]), int(raw_day[4:6]), int(raw_day[6:]))
        if day > now or (now-day).days > 14:
            raise TdccError("tdcc_weekly_snapshot_future_or_stale")
        if weekly_date is None:
            weekly_date = day
        elif day != weekly_date:
            raise TdccError("tdcc_mixed_week_dates")
        code = row[index["證券代號"]].strip()
        if code not in official_codes:
            continue
        level = integer(row[index["持股分級"]])
        if level not in REQUIRED_LEVELS:
            raise TdccError("tdcc_unsupported_holder_level")
        people = integer(row[index["人數"]])
        shares = integer(row[index["股數"]], allow_negative=level == 16)
        pct = percentage(row[index["占集保庫存數比例%"]])
        record = buckets.setdefault(code, {})
        if level in record:
            raise TdccError("tdcc_duplicate_level")
        record[level] = (people, shares, pct)
    if weekly_date is None or count < 25000:
        raise TdccError("tdcc_source_rows_insufficient")
    data = []
    for code, levels in sorted(buckets.items()):
        if set(levels) != REQUIRED_LEVELS:
            continue  # thin/irregular issuers are not fabricated as complete
        total = levels[17][1]
        if total <= 0 or levels[17][0] <= 0:
            continue
        # Level 16 is a settlement/discrepancy adjustment; it is not a holder tier.
        summed = sum(levels[k][1] for k in range(1, 17))
        if summed != total:
            raise TdccError("tdcc_holding_total_mismatch")
        if abs(levels[17][2]-100.0) > 1.0:
            raise TdccError("tdcc_total_percentage_invalid")
        data.append({"code": code,
                     "market": "TWSE" if code in roster["markets"]["TWSE"] else "TPEX",
                     "shareholders": levels[17][0],
                     "depositoryShares": total,
                     "tier15Shares": levels[15][1],
                     "tier15PercentOfDepository": levels[15][2],
                     "level16AdjustmentShares": levels[16][1]})
    if len(data) < min_companies:
        raise TdccError("tdcc_valid_company_coverage_too_low")
    return {"schemaVersion": 1, "asOf": weekly_date.isoformat(),
            "dataCadence": "weekly",
            "source": URL, "status": "tdcc_shareholder_research_only",
            "officialIssuerRoster": "current_not_point_in_time",
            "companies": data, "companyCount": len(data),
            "sourceRowCount": count,
            "allCompanyLevelsVerified": True,
            "tier15IsNotIdenticalToEveryLargeHolderDefinition": True,
            "corporateActionsAndAllFactorsComplete": False,
            "dailyValueImputationForbidden": True,
            "top10": None, "publishable": False}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--archive-dir", type=Path, default=Path("data/tdcc_weekly_research"))
    p.add_argument("--output", type=Path, default=Path("tdcc-output"))
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    try:
        roster = official_universe(fetch_json, fetch_csv)
        if roster.get("errors"):
            raise TdccError("official_company_roster_unavailable")
        result = parse_csv(fetch_official_csv(), roster)
        path = args.archive_dir / (result["asOf"] + ".json.gz")
        path.parent.mkdir(parents=True, exist_ok=True)
        packed = compressed_snapshot(result)
        if path.exists() and path.read_bytes() != packed:
            raise TdccError("existing_tdcc_week_file_changed")
        if not path.exists():
            path.write_bytes(packed)
        diagnostic = {"status": "verified", "week": result["asOf"],
                      "companies": result["companyCount"],
                      "sourceRows": result["sourceRowCount"],
                      "dailyFactorReady": False, "top10": None}
        rc = 0
        print("TDCC weekly official research:", result["asOf"],
              "companies", result["companyCount"],
              "; NO DAILY FILL, NO TOP10")
    except (TdccError, OSError, ValueError, TypeError, KeyError) as exc:
        diagnostic = {"status": "failed", "reason": str(exc) if isinstance(exc, TdccError)
                      else "official_tdcc_source_or_schema_failure",
                      "dailyFactorReady": False, "top10": None}
        rc = 1
        print("TDCC weekly research safely rejected:", diagnostic["reason"])
    (args.output / "tdcc-weekly-status.json").write_text(
        json.dumps(diagnostic, indent=2, ensure_ascii=False), encoding="utf-8")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
