"""Ensure external TDCC historical mirrors cannot be mislabeled as official.

All work is read-only, with no factors, ranking, or direct historical
publication-date claims. Corporate actions and PIT membership remain blocked.
"""
import argparse
from datetime import date
import gzip
import json
from pathlib import Path
import re


class TdccProvenanceError(Exception):
    pass


MIRROR_BASE = ("https://raw.githubusercontent.com/wirelessr/"
               "tdcc-opendata-archive/main/snapshots/2026/")


def read(path):
    try:
        value = json.loads(gzip.decompress(Path(path).read_bytes()))
        day = date.fromisoformat(value["asOf"]).isoformat()
        if path.name != day+".json.gz":
            raise TdccProvenanceError("provenance_archive_date_mismatch")
        if value.get("publishable") is not False or value.get("top10") is not None:
            raise TdccProvenanceError("tdcc_provenance_trading_guard_invalid")
        return value
    except (OSError, ValueError, TypeError, KeyError, gzip.BadGzipFile) as exc:
        raise TdccProvenanceError("tdcc_provenance_archive_unreadable") from exc


def audit(official_dir, external_dir):
    official = {}
    mirror = {}
    for path in sorted(Path(official_dir).glob("*.json.gz")):
        v = read(path)
        if (v.get("status") != "tdcc_shareholder_research_only"
                or v.get("dataCadence") != "weekly"
                or v.get("source") != "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5"
                or v.get("companyCount", 0) < 1000
                or len(v.get("companies", [])) != v["companyCount"]):
            raise TdccProvenanceError("direct_official_tdcc_provenance_invalid")
        official[v["asOf"]] = v["companyCount"]
    if not official:
        raise TdccProvenanceError("no_direct_official_tdcc_week")
    newest = max(official)
    for path in sorted(Path(external_dir).glob("*.json.gz")):
        v = read(path)
        d = v["asOf"]
        if (v.get("status") != "external_third_party_mirror_unverified_historical"
                or v.get("dataCadence") != "weekly"
                or v.get("sourceKind") != "independent_third_party_mirror"
                or v.get("historicalOfficialDirectAcquisition") is not False
                or v.get("historicalPublicationTimeVerified") is not False
                or v.get("pointInTimeCompanyUniverse") is not False
                or v.get("historicalFactorReady") is not False
                or v.get("archiveMirrorCurrentWeekValidatedOnly") is not True
                or v.get("originUrl") != MIRROR_BASE+d+".csv"
                or not re.fullmatch("[0-9a-f]{64}", v.get("originSha256", ""))
                or d >= newest
                or v.get("companyCount", 0) < 1000
                or len(v.get("companies", [])) != v["companyCount"]):
            raise TdccProvenanceError("external_tdcc_provenance_invalid")
        if d in mirror or d in official:
            raise TdccProvenanceError("tdcc_source_dates_overlap")
        mirror[d] = v["companyCount"]
    return {
        "status": "research_tdcc_provenance_checked",
        "latestDirectOfficialWeek": newest,
        "officialWeeks": len(official),
        "externalUnverifiedHistoricalWeeks": len(mirror),
        "externalResearchCompanyCountsByWeek": mirror,
        "externalHistoricalPublicationTimesVerified": False,
        "externalHistoricalWeeksDirectlyOfficialSourced": False,
        "externalResearchEligibleForQuantFactors": False,
        "adjustedCorporateActionsAndPITUniverseReady": False,
        "top10": None, "publishable": False,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--official-dir", type=Path, default=Path("data/tdcc_weekly_research"))
    p.add_argument("--external-dir", type=Path, default=Path("data/tdcc_external_history_research"))
    p.add_argument("--output", type=Path, default=Path("tdcc-provenance-output"))
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    try:
        result = audit(args.official_dir, args.external_dir)
        status = 0
        print("TDCC provenance: direct official weeks=" + str(result["officialWeeks"]) +
              "; external research weeks=" + str(result["externalUnverifiedHistoricalWeeks"]) +
              "; UNVERIFIED HISTORICAL, NO TOP10")
    except (TdccProvenanceError, TypeError, ValueError, KeyError) as err:
        result = {"status": "failed",
                  "reason": str(err) if isinstance(err, TdccProvenanceError)
                  else "tdcc_provenance_schema_failure",
                  "top10": None, "publishable": False}
        status = 1
        print("TDCC research provenance audit safely stopped:", result["reason"])
    (args.output/"tdcc-provenance-audit.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
