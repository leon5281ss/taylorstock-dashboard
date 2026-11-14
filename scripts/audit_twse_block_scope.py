"""Record single-security block transactions without inferring aggregate scope."""
import argparse
from datetime import date
from hashlib import sha256
import json
from pathlib import Path

from collect_market_history import IngestionError, number, roc_to_iso

ROOT = "https://www.twse.com.tw/rwd/zh/block/BFIAUU"
FIELDS = ["證券代號", "證券名稱", "交易別", "成交價", "成交股數", "成交金額"]


def source_url(day):
    stamp = date.fromisoformat(day).strftime("%Y%m%d")
    return f"{ROOT}?date={stamp}&response=json"


def inspect(raw, day):
    payload = json.loads(raw)
    if (payload["stat"] != "OK" or roc_to_iso(payload["date"]) != day
            or "鉅額交易日成交資訊-單一證券" not in payload["title"]):
        raise ValueError("single_security_block_identity_mismatch")
    if payload["fields"] != FIELDS or not isinstance(payload["data"], list):
        raise ValueError("block_quantity_schema_mismatch")
    records = []
    for row in payload["data"]:
        if not isinstance(row, list) or len(row) != len(FIELDS):
            raise ValueError("invalid_block_row")
        shares = number(row[4], integer=True)
        if shares is None or shares < 0:
            raise ValueError("invalid_block_shares")
        records.append({"code": row[0], "tradeType": row[2], "shares": shares})
    return {"source": source_url(day), "responseDate": day,
            "scope": "single_security_block_rows_only", "unit": "shares",
            "fields": FIELDS, "sha256": sha256(raw).hexdigest(), "transactions": records,
            "allBlockCoverageVerified": False, "publicAggregateInclusionVerified": False,
            "v5v60": None, "top10": None, "publishable": False}


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument("day")
    cli.add_argument("capture", type=Path)
    args = cli.parse_args()
    try:
        result = inspect(args.capture.read_bytes(), args.day)
    except (OSError, ValueError, TypeError, KeyError, IngestionError) as exc:
        print(json.dumps({"status": "invalid_source", "reason": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
