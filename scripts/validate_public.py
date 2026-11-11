import json

from market_pipeline.pipeline import ROOT, assert_public, load_watchlist


def validate():
    expected = {item["code"] for item in load_watchlist(ROOT / "config/watchlist_public.json")}
    payload = json.loads((ROOT / "docs/data/stocks.json").read_text(encoding="utf-8"))
    assert_public(payload)
    actual = [item["code"] for item in payload["stocks"]]
    if len(actual) != 22 or set(actual) != expected or payload.get("schemaVersion") != 3:
        raise ValueError("public_payload_must_match_22_symbols")
    if (ROOT / "docs/data/stocks-data.js").read_text(encoding="utf-8").strip() != "window.STOCK_DASHBOARD_DATA = null;":
        raise ValueError("legacy_embedded_data_rejected")
    for file in (ROOT / "docs").rglob("*"):
        if file.is_file() and (file.suffix.lower() in {".xlsx", ".csv", ".env", ".log"} or "private" in file.name.lower()):
            raise ValueError("private_file_in_public_site")
    print("Public schema and 22-symbol privacy checks passed")


if __name__ == "__main__":
    validate()

