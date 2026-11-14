"""Independent TDCC weekly ARCHIVE research, never historical official data.

A current-week mirror has been verified against TDCC's official newest snapshot.
That DOES NOT independently validate older mirrors or their original publication
times. All older mirror weeks are explicitly classified as external third-party
research ONLY and may never feed a portfolio factor, ranking, or backtest.
"""
import argparse
from datetime import date, timedelta
import gzip
import hashlib
import json
from pathlib import Path
import re
import time
from urllib.request import Request, urlopen

from collect_market_history import compressed_snapshot
from collect_tdcc_weekly_research import TdccError, parse_csv
from crosscheck_tdcc_mirror import MirrorError, compare, fetch_mirror
from market_pipeline.quant_screen import official_universe
from quant_run import fetch_csv, fetch_json

MIRROR_REPO = "wirelessr/tdcc-opendata-archive"
MIRROR_MANIFEST = ("https://api.github.com/repos/"
                   + MIRROR_REPO + "/contents/snapshots/2026?ref=main")
ARCHIVE_BASE = ("https://raw.githubusercontent.com/"
                + MIRROR_REPO + "/main/snapshots/2026/")
SOURCE = "external_third_party_mirror_unverified_historical"
DATE_PATTERN = re.compile(r"^2026-\d{2}-\d{2}\.csv$")


class ExternalHistoryError(Exception):
    pass


def fetch_manifest(url=MIRROR_MANIFEST):
    request = Request(url, headers={
        "User-Agent": "TaylorStock-SourceAudit/0.1",
        "Accept": "application/vnd.github+json"})
    with urlopen(request, timeout=35) as response:
        body = response.read(200_000)
    if len(body) >= 200_000:
        raise ExternalHistoryError("mirror_manifest_too_large")
    return json.loads(body.decode("utf-8-sig"))


def listing(manifest, official_day):
    if not isinstance(manifest, list) or len(manifest) < 10:
        raise ExternalHistoryError("mirror_manifest_incomplete")
    try:
        newest = date.fromisoformat(official_day)
        found = set()
        for item in manifest:
            if item.get("type") != "file":
                continue
            name = item.get("name")
            if not isinstance(name, str) or not DATE_PATTERN.fullmatch(name):
                continue
            day = name[:10]
            if date.fromisoformat(day).year != newest.year:
                raise ExternalHistoryError("mirror_date_wrong_year")
            if day in found:
                raise ExternalHistoryError("duplicate_mirror_week")
            found.add(day)
        if official_day not in found:
            raise ExternalHistoryError("mirror_latest_official_week_missing")
        if len(found) < 10:
            raise ExternalHistoryError("too_few_mirror_weekly_files")
        return sorted((d for d in found if d < official_day), reverse=True)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ExternalHistoryError("mirror_manifest_invalid") from exc


def official_latest(path):
    files = sorted(Path(path).glob("*.json.gz"))
    if not files:
        raise ExternalHistoryError("official_tdcc_week_not_archived")
    try:
        raw = gzip.decompress(files[-1].read_bytes())
        value = json.loads(raw)
        when = date.fromisoformat(value["asOf"])
        if (files[-1].name != when.isoformat()+".json.gz"
                or value.get("status") != "tdcc_shareholder_research_only"
                or value.get("dataCadence") != "weekly"
                or value.get("publishable") is not False
                or len(value.get("companies", [])) < 1000):
            raise ExternalHistoryError("official_latest_week_schema_invalid")
        return value
    except (OSError, KeyError, TypeError, ValueError, gzip.BadGzipFile) as exc:
        raise ExternalHistoryError("official_latest_week_unreadable") from exc


def validate_previous(existing_dir, possible_dates):
    seen = set()
    for path in sorted(Path(existing_dir).glob("*.json.gz")):
        try:
            data = json.loads(gzip.decompress(path.read_bytes()))
            d = date.fromisoformat(data["asOf"]).isoformat()
            if (path.name != d+".json.gz"
                    or d not in possible_dates
                    or data.get("status") != SOURCE
                    or data.get("dataCadence") != "weekly"
                    or data.get("historicalOfficialDirectAcquisition") is not False
                    or data.get("historicalPublicationTimeVerified") is not False
                    or data.get("pointInTimeCompanyUniverse") is not False
                    or data.get("archiveMirrorCurrentWeekValidatedOnly") is not True
                    or data.get("originUrl") != ARCHIVE_BASE+d+".csv"
                    or not re.fullmatch(r"[a-f0-9]{64}", data.get("originSha256", ""))
                    or data.get("publishable") is not False
                    or data.get("top10") is not None
                    or data.get("companyCount", 0) < 1000
                    or len(data.get("companies", [])) != data["companyCount"]):
                raise ExternalHistoryError("existing_external_history_provenance_invalid")
            if d in seen:
                raise ExternalHistoryError("existing_external_week_duplicate")
            seen.add(d)
        except (OSError, EOFError, ValueError, TypeError, KeyError,
                gzip.BadGzipFile) as exc:
            raise ExternalHistoryError("existing_external_history_unreadable") from exc
    return seen


def run(official_dir, research_dir, *, manifest_fetch=fetch_manifest,
        mirror_fetch=fetch_mirror,
        roster_json=fetch_json, roster_csv=fetch_csv,
        sleep=time.sleep, delay=2.5, max_successes=4, max_attempts=6):
    if delay < 2.5 or not (1 <= max_successes <= 6
                           and max_successes <= max_attempts <= 10):
        raise ExternalHistoryError("external_mirror_safety_limits_invalid")
    authoritative = official_latest(official_dir)
    day = authoritative["asOf"]
    if day[:4] != "2026":
        raise ExternalHistoryError("only_preverified_2026_manifest_supported")
    dates = listing(manifest_fetch(), day)
    existing = validate_previous(research_dir, set(dates))
    pending = [d for d in dates if d not in existing]
    if not pending:
        return {"status": "no_unarchived_external_weeks",
                "newCount": 0, "existingWeeks": len(existing),
                "externalWeeksNow": len(existing), "publishable": False,
                "historicalOfficialAcquisitionVerified": False, "top10": None}
    universe = official_universe(roster_json, roster_csv)
    if universe.get("errors"):
        raise ExternalHistoryError("official_current_company_roster_unavailable")

    # Gate: independently confirm latest mirror against directly obtained
    # official newest week in this same job. Earlier files remain unverified.
    sleep(delay)
    latest_text = mirror_fetch(day)
    latest_parsed = parse_csv(
        latest_text, universe, now=date.fromisoformat(day)+timedelta(days=2))
    latest_overlap = compare(authoritative, latest_parsed)
    if latest_overlap["valueDifferenceCount"] != 0:
        raise ExternalHistoryError("latest_mirror_must_match_official_exactly")

    new, errors = [], []
    for candidate in pending:
        if len(new) >= max_successes or len(new)+len(errors) >= max_attempts:
            break
        try:
            sleep(delay)
            raw = mirror_fetch(candidate)
            normalized = parse_csv(
                raw, universe,
                now=date.fromisoformat(candidate)+timedelta(days=2))
            if normalized["asOf"] != candidate:
                raise ExternalHistoryError("external_week_response_date_mismatch")
            if normalized["companyCount"] < 1000:
                raise ExternalHistoryError("external_week_company_coverage_low")
            normalized.update({
                "status": SOURCE,
                "source": "https://github.com/"+MIRROR_REPO,
                "sourceKind": "independent_third_party_mirror",
                "originUrl": ARCHIVE_BASE+candidate+".csv",
                "originSha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
                "historicalOfficialDirectAcquisition": False,
                "archiveMirrorCurrentWeekValidatedOnly": True,
                "historicalPublicationTimeVerified": False,
                "pointInTimeCompanyUniverse": False,
                "corporateActionsAndAllFactorsComplete": False,
                "historicalFactorReady": False,
                "top10": None,
                "publishable": False,
            })
            dest = Path(research_dir)/(candidate+".json.gz")
            if dest.exists():
                raise ExternalHistoryError("external_week_concurrent_archive_collision")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(compressed_snapshot(normalized))
            new.append({"week": candidate,
                        "companies": normalized["companyCount"],
                        "quarantined": normalized["quarantinedTotalMismatchCount"]})
        except (ExternalHistoryError, TdccError, OSError, ValueError,
                TypeError, KeyError, UnicodeError) as exc:
            errors.append({
                "week": candidate,
                "reason": str(exc) if isinstance(exc, (ExternalHistoryError, TdccError))
                else "external_week_source_or_schema_unavailable"})
            if len(errors) >= 3:
                break
    return {
        "status": "partial_with_unverified_weeks" if errors else (
            "archived_external_research_only" if new else "no_new_archives"),
        "directOfficialReferenceWeek": day,
        "latestMirrorCompanyOverlap": latest_overlap["sharedCompanies"],
        "latestMirrorValueDifferences": latest_overlap["valueDifferenceCount"],
        "newCount": len(new), "new": new, "errors": errors,
        "existingWeeks": len(existing),
        "externalWeeksNow": len(existing)+len(new),
        "historicalOfficialAcquisitionVerified": False,
        "historicalPublicationTimeVerified": False,
        "historicalPointInTimeUniverseVerified": False,
        "externalMirrorNotAuthorizedForTradingFactor": True,
        "top10": None, "publishable": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--official-dir", type=Path, default=Path("data/tdcc_weekly_research"))
    parser.add_argument("--research-dir", type=Path, default=Path("data/tdcc_external_history_research"))
    parser.add_argument("--output", type=Path, default=Path("tdcc-external-output"))
    parser.add_argument("--max-successes", type=int, default=4)
    parser.add_argument("--max-attempts", type=int, default=6)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    try:
        result = run(args.official_dir, args.research_dir,
                     max_successes=args.max_successes,
                     max_attempts=args.max_attempts)
        status = 0 if result["newCount"] or not result.get("errors") else 1
        print("External TDCC mirror research: " + result["status"] +
              "; new=" + str(result["newCount"]) +
              "; unverified=" + str(len(result.get("errors", []))) +
              "; NEVER AUTHORITATIVE, NO TOP10")
        for error in result.get("errors", []):
            print("::warning::External week " + error["week"] + ": " + error["reason"])
    except (ExternalHistoryError, MirrorError, TdccError,
            OSError, ValueError, TypeError, KeyError,
            UnicodeError, gzip.BadGzipFile) as exc:
        result = {"status": "failed",
                  "reason": str(exc) if isinstance(
                      exc, (ExternalHistoryError, MirrorError, TdccError))
                  else "external_tdcc_mirror_source_or_schema_failure",
                  "historicalOfficialAcquisitionVerified": False,
                  "top10": None, "publishable": False}
        status = 1
        print("External TDCC research safely stopped: " + result["reason"])
    (args.output/"tdcc-external-history-status.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
