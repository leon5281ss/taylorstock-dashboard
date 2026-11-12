"""Audit only pre-recorded recommendations after trading outcome matures."""
import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from market_pipeline.strategy_audit import audit


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--signals", type=Path, required=True)
    p.add_argument("--calendar", type=Path, required=True)
    p.add_argument("--prices", type=Path, required=True)
    p.add_argument("--output", type=Path, default=Path("audit-output"))
    args = p.parse_args()
    signals = json.loads(args.signals.read_text(encoding="utf-8"))
    days = json.loads(args.calendar.read_text(encoding="utf-8"))
    history = json.loads(args.prices.read_text(encoding="utf-8"))
    as_of = datetime.now(ZoneInfo("Asia/Taipei")).date().isoformat()
    result = audit(signals, days, history, as_of)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output/"recommendation-audit.json").write_text(
        json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2), encoding="utf-8")
    print("Paper trade audit: " + result["status"] +
          ", matured=" + str(result["maturedTrades"]) +
          ", unresolved=" + str(sum(result["unresolved"].values())))


if __name__ == "__main__":
    main()
