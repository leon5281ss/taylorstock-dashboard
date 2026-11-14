"""Compare same-session TWSE component evidence without blending sources."""
import argparse
from hashlib import sha256
import json
import time
from pathlib import Path

from collect_market_history import number, roc_to_iso, IngestionError
from reconcile_volume_categories import fetch

REPORTS = {
    "TWTC7U": ("盤中零股交易行情單", "成交股數", "shares", "afterTrading"),
    "TWT53U": ("盤後零股交易行情單", "成交股數", "shares", "afterTrading"),
    "BFT41U": ("盤後定價交易", "成交數量", None, "afterTrading"),
    "BFIAUU": ("鉅額交易日成交資訊", "成交股數", "shares", "blockTrade"),
}


def source_url(report, day):
    return ("https://www.twse.com.tw/rwd/zh/" + REPORTS[report][3] + "/" + report
            + "?date=" + day.replace("-", "") + "&response=json")


def parse(raw, report, day):
    title, field, unit, _ = REPORTS[report]
    data = json.loads(raw)
    if data["stat"] != "OK" or roc_to_iso(data["date"]) != day or title not in data["title"]:
        raise ValueError("source_date_or_title_mismatch")
    fields = data["fields"]
    if fields.count(field) != 1 or fields.count("證券代號") != 1:
        raise ValueError("unexpected_quantity_schema")
    qi, ci = fields.index(field), fields.index("證券代號")
    rows = data["data"]
    if (not isinstance(rows, list) or type(data.get("total")) is not int
            or data["total"] != len(rows)):
        raise ValueError("incomplete_component_report")
    values = {}
    for row in rows:
        if not isinstance(row, list) or len(row) != len(fields):
            raise ValueError("unexpected_row_schema")
        code = str(row[ci]).strip()
        if code in values:
            raise ValueError("duplicate_symbol_or_transaction_scope")
        amount = number(row[qi], integer=True)
        if amount is None or amount < 0:
            raise ValueError("invalid_component_quantity")
        values[code] = amount
    return {"fields": fields, "unit": unit, "volumeField": field, "values": values}


def audit(baseline, folder, *, download=False):
    samples = [r for stock in baseline["stocks"] for r in stock["comparisons"]
               if r["archiveSource"].startswith("https://openapi.twse.com.tw/")]
    captures, rows = [], []
    manifest_path = folder / "twse-components-manifest.json"
    try:
        manifest = json.loads(manifest_path.read_bytes()) if manifest_path.exists() else {}
        if not isinstance(manifest, dict):
            raise ValueError("invalid_capture_manifest")
    except (OSError, ValueError):
        manifest = {}
    for day in sorted({r["date"] for r in samples}):
        components = {}
        for report in REPORTS:
            name = f"twse-{report}-{day.replace('-', '')}.json"
            source = {"report": report, "date": day, "url": source_url(report, day),
                      "file": name, "captureMode": "local_replay"}
            source.update(responseDate=None, unit=None, parseStatus="failed",
                          rawIntegrityVerified=False, retrieved=False)
            captured = False
            try:
                path = folder / name
                if download and not path.exists():
                    time.sleep(2.5)
                    raw = fetch(source["url"])
                    with path.open("xb") as output:
                        output.write(raw)
                    captured = True
                    source["captureMode"] = "direct_https"
                raw = path.read_bytes()
                source["retrieved"] = True
                digest = sha256(raw).hexdigest()
                if not captured:
                    registered = manifest.get(name)
                    if not isinstance(registered, dict) or any(
                        registered.get(k) != source[k] for k in ("url", "date", "file", "report")
                    ):
                        raise ValueError("capture_manifest_entry_missing_or_mismatched")
                    source["sha256"] = registered.get("sha256")
                    if source["sha256"] != digest:
                        raise ValueError("raw_sha256_mismatch")
                else:
                    source["sha256"] = digest
                source["rawIntegrityVerified"] = True
                parsed = parse(raw, report, day)
                if not captured and (registered.get("responseDate"), registered.get("unit"),
                                     registered.get("fields")) != (day, parsed["unit"], parsed["fields"]):
                    raise ValueError("replay_metadata_mismatch")
                components[report] = parsed["values"]
                source.update({k: parsed[k] for k in ("fields", "unit", "volumeField")})
                source.update(responseDate=day, parseStatus="parsed")
            except (OSError, ValueError, TypeError, KeyError, AttributeError, IngestionError) as exc:
                source["error"] = str(exc)
            if captured:
                manifest[name] = source.copy()
                manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                                         encoding="utf-8")
            captures.append(source)
        for sample in samples:
            if sample["date"] != day:
                continue
            code = sample["code"]
            quantities = {report: components.get(report, {}).get(code) for report in REPORTS}
            rows.append({"date": day, "code": code, "stockDayShares": sample["stockDayShares"],
                         "openApiShares": sample["archiveShares"], "reportedComponents": quantities,
                         "missingComponents": [r for r, n in quantities.items() if n is None],
                         "scopeVerified": False})
    parsed_all = bool(captures) and all(r["parseStatus"] == "parsed" for r in captures)
    integrity = bool(captures) and all(r["rawIntegrityVerified"] for r in captures)
    return {"auditExecuted": True,
            "officialSourceAcquisitionComplete": parsed_all,
            "rawIntegrityVerified": integrity, "scopeVerificationPassed": False,
            "status": "research_only" if parsed_all and integrity else "failed_official_evidence",
            "captures": captures, "comparisons": rows, "scopeVerifiedStocks": 0,
            "v5v60": None, "top10": None, "publishable": False,
            "tpexUnverifiedDifferences": 2533}


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument("baseline", type=Path)
    cli.add_argument("captures", type=Path)
    cli.add_argument("--download", action="store_true")
    args = cli.parse_args()
    args.captures.mkdir(parents=True, exist_ok=True)
    report = audit(json.loads(args.baseline.read_bytes()), args.captures, download=args.download)
    (args.captures / "twse-session-components.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Sample rows: {len(report['comparisons'])}; parsed reports: "
          f"{sum('error' not in r for r in report['captures'])}/{len(report['captures'])}")
    for key in ("auditExecuted", "officialSourceAcquisitionComplete",
                "rawIntegrityVerified", "scopeVerificationPassed"):
        print(f"{key}={str(report[key]).lower()}")
    return int(report["status"] == "failed_official_evidence")


if __name__ == "__main__":
    raise SystemExit(main())
