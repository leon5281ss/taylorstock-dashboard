"""Official TWSE+TPEx company roster + strict ranking readiness; never fakes Top 10."""
import argparse
import csv
import io
import json
import sys
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from market_pipeline.quant_screen import official_universe, screen


def fetch_text(url):
    req = Request(url, headers={"User-Agent": "taylorstock-quant-v1",
                                "Accept": "application/json,text/csv"})
    try:
        with urlopen(req, timeout=25) as res:
            data = res.read(14_000_000).decode("utf-8-sig")
        return data
    except (HTTPError, URLError, OSError, UnicodeError):
        raise OSError("official_source_unavailable") from None


def fetch_json(url):
    value = json.loads(fetch_text(url))
    if not isinstance(value, list):
        raise ValueError("official_schema_changed")
    return value


def fetch_csv(url):
    return list(csv.DictReader(io.StringIO(fetch_text(url))))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("quant-output"))
    parser.add_argument("--enrichment", type=Path, help="Private verified complete history and factor inputs")
    args = parser.parse_args()
    now = datetime.now(ZoneInfo("Asia/Taipei"))
    as_of = now.date().isoformat()
    official = official_universe(fetch_json, fetch_csv)
    enrichment = {}
    if args.enrichment:
        source = json.loads(args.enrichment.read_text(encoding="utf-8"))
        if source.get("asOf") != as_of or not isinstance(source.get("stocks"), dict):
            print("Quant data date/schema mismatch; no ranking published.")
            return 2
        enrichment = source["stocks"]
    result = screen(official, enrichment, as_of)
    result["collectedAt"] = now.isoformat()
    result["universeSources"] = official["sources"]
    result["modelVersion"] = "strict-35-25-25-15-v1"
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "quant-readiness.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print("Quant readiness: " + result["status"] + "; TWSE " +
          str(result["marketCounts"]["TWSE"]) + "; TPEx " +
          str(result["marketCounts"]["TPEX"]) + "; factor-complete " +
          str(result["factorCompleteCount"]) + ". Top 10 suppressed unless verified.")
    return 1 if result["errorReasons"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
