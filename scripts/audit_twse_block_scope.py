"""Record single-security block transactions without inferring aggregate scope."""
import argparse
from datetime import date
from decimal import Decimal
from hashlib import sha256
import json
import re
from pathlib import Path

from collect_market_history import IngestionError, roc_to_iso

ROOT = "https://www.twse.com.tw/rwd/zh/block/BFIAUU"
FIELDS = ["證券代號", "證券名稱", "交易別", "成交價", "成交股數", "成交金額"]


def source_url(day):
    stamp = date.fromisoformat(day).strftime("%Y%m%d")
    return f"{ROOT}?date={stamp}&response=json"


def positive_decimal(value, *, integer=False):
    if not isinstance(value, str) or not re.fullmatch(
        r"(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:[.][0-9]+)?", value
    ):
        raise ValueError("invalid_block_numeric_field")
    result = Decimal(value.replace(",", ""))
    if result <= 0 or integer and result != result.to_integral_value():
        raise ValueError("invalid_block_numeric_field")
    return int(result) if integer else result


def replay(capture, day, manifest):
    record = manifest.get(day)
    if not isinstance(record, dict) or (
        record.get("requestedDate"), record.get("responseDate"), record.get("source"),
        record.get("rawFile")
    ) != (day, day, source_url(day), capture.name):
        raise ValueError("block_manifest_identity_mismatch")
    raw = capture.read_bytes()
    if sha256(raw).hexdigest() != record.get("sha256"):
        raise ValueError("block_raw_sha256_mismatch")
    return inspect(raw, day)


def inspect(raw, day):
    payload = json.loads(raw)
    if (payload["stat"] != "OK" or roc_to_iso(payload["date"]) != day
            or "鉅額交易日成交資訊-單一證券" not in payload["title"]):
        raise ValueError("single_security_block_identity_mismatch")
    if payload["fields"] != FIELDS or not isinstance(payload["data"], list):
        raise ValueError("block_quantity_schema_mismatch")
    records, seen = [], set()
    totals = None
    for index, row in enumerate(payload["data"]):
        if not isinstance(row, list) or len(row) != len(FIELDS):
            raise ValueError("invalid_block_row")
        code, name, trade_type, price, shares, amount = row
        if code == "總計":
            if index != len(payload["data"]) - 1 or (name, trade_type, price) != ("", "", ""):
                raise ValueError("invalid_block_total_row")
            totals = (positive_decimal(shares, integer=True),
                      positive_decimal(amount, integer=True))
            continue
        if not isinstance(code, str) or not re.fullmatch(r"[0-9]{4,6}[A-Z]?", code):
            raise ValueError("invalid_block_code")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("invalid_block_name")
        if trade_type not in ("配對交易", "逐筆交易"):
            raise ValueError("invalid_block_trade_type")
        price = positive_decimal(price)
        shares = positive_decimal(shares, integer=True)
        amount = positive_decimal(amount, integer=True)
        # Foreign-currency rows may report turnover converted to TWD.
        key = (code, trade_type, price, shares, amount)
        if key in seen:
            raise ValueError("duplicate_block_trade_without_unique_id")
        seen.add(key)
        records.append({"code": code, "tradeType": trade_type, "price": str(price),
                        "shares": shares, "turnover": amount})
    if totals is not None and totals != (sum(r["shares"] for r in records),
                                         sum(r["turnover"] for r in records)):
        raise ValueError("block_report_totals_mismatch")
    return {"source": source_url(day), "responseDate": day,
            "scope": "single_security_block_rows_only", "unit": "shares",
            "fields": FIELDS, "summaryRows": int(totals is not None), "sha256": sha256(raw).hexdigest(), "transactions": records,
            "allBlockCoverageVerified": False, "publicAggregateInclusionVerified": False,
            "v5v60": None, "top10": None, "publishable": False}


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument("day")
    cli.add_argument("capture", type=Path)
    cli.add_argument("--manifest", type=Path,
                     default=Path("config/twse_bfiauu_capture_manifest_2026.json"))
    args = cli.parse_args()
    try:
        result = replay(args.capture, args.day, json.loads(args.manifest.read_bytes()))
    except (OSError, ValueError, TypeError, KeyError, IngestionError) as exc:
        print(json.dumps({"status": "invalid_source", "reason": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
