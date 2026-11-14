"""Cross-check the latest external TDCC weekly archive against our official snapshot.

The external GitHub mirror is an independent historical cache, NOT the
authoritative exchange/TDCC source. This job is read-only and cannot promote
historical mirrors into trusted factors or produce any trading output.
"""
import argparse
from datetime import date, timedelta
import gzip
import json
from pathlib import Path
from urllib.request import Request, urlopen

from collect_tdcc_weekly_research import TdccError, parse_csv
from market_pipeline.quant_screen import official_universe
from quant_run import fetch_csv, fetch_json


MIRROR_BASE = ("https://raw.githubusercontent.com/wirelessr/"
               "tdcc-opendata-archive/main/snapshots/")


class MirrorError(Exception):
    pass


def fetch_mirror(day):
    year = day[:4]
    url = MIRROR_BASE + year + "/" + day + ".csv"
    req = Request(url, headers={"User-Agent": "TaylorStock-Research/0.1"})
    with urlopen(req, timeout=60) as response:
        raw = response.read(10_000_000)
    if not raw or len(raw) >= 10_000_000:
        raise MirrorError("mirror_empty_or_too_large")
    return raw.decode("utf-8-sig")


def compare(official, mirror):
    if (official.get("status") != "tdcc_shareholder_research_only"
            or official.get("dataCadence") != "weekly"
            or official.get("publishable") is not False
            or official.get("asOf") != mirror.get("asOf")
            or mirror.get("publishable") is not False):
        raise MirrorError("weekly_provenance_or_date_mismatch")
    keys = ("market", "shareholders", "depositoryShares", "tier15Shares",
            "tier15PercentOfDepository", "level16AdjustmentShares")
    direct = {row["code"]: row for row in official["companies"]}
    cached = {row["code"]: row for row in mirror["companies"]}
    common = sorted(set(direct) & set(cached))
    if len(common) < 1000 or len(common) < 0.95*len(direct):
        raise MirrorError("mirror_official_company_overlap_insufficient")
    mismatched = [code for code in common
                  if any(direct[code][k] != cached[code][k] for k in keys)]
    mismatch_rate = len(mismatched)/len(common)
    if mismatch_rate > 0.001:
        raise MirrorError("mirror_official_value_mismatch")
    return {"status": "crosschecked_latest_only",
            "asOf": official["asOf"],
            "officialCompanies": len(direct), "mirrorCompanies": len(cached),
            "sharedCompanies": len(common),
            "identicalCompanies": len(common)-len(mismatched),
            "valueDifferenceCount": len(mismatched),
            "sampleDifferenceCodes": mismatched[:10],
            "source": MIRROR_BASE,
            "mirrorHistoryAuthorizedForFactorUsage": False,
            "latestDateOverlapDoesNotValidateAllEarlierWeeks": True,
            "allCorporateActionsAdjusted": False,
            "pointInTimeUniverseVerified": False,
            "top10": None, "publishable": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--official-dir", type=Path, default=Path("data/tdcc_weekly_research"))
    parser.add_argument("--output", type=Path, default=Path("tdcc-crosscheck-output"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    try:
        existing = sorted(args.official_dir.glob("*.json.gz"))
        if not existing:
            raise MirrorError("official_weekly_snapshot_not_archived")
        official = json.loads(gzip.decompress(existing[-1].read_bytes()))
        official_day = official["asOf"]
        roster = official_universe(fetch_json, fetch_csv)
        if roster.get("errors"):
            raise MirrorError("official_company_roster_unavailable")
        raw = fetch_mirror(official_day)
        parsed = parse_csv(raw, roster,
                           now=date.fromisoformat(official_day) + timedelta(days=2))
        output = compare(official, parsed)
        result = 0
        print("TDCC latest mirror vs official: shared=" + str(output["sharedCompanies"]) +
              "; changed=" + str(output["valueDifferenceCount"]) +
              "; HISTORICAL MIRROR NOT AUTHORIZED")
    except (MirrorError, TdccError, OSError, ValueError, TypeError, KeyError,
            UnicodeError, gzip.BadGzipFile) as exc:
        output = {"status": "failed", "reason": str(exc) if isinstance(
            exc, (MirrorError, TdccError)) else "mirror_or_official_source_invalid",
                  "mirrorHistoryAuthorizedForFactorUsage": False,
                  "top10": None, "publishable": False}
        result = 1
        print("TDCC external mirror crosscheck safely rejected:", output["reason"])
    (args.output / "tdcc-mirror-crosscheck.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
