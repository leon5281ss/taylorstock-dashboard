"""Explicit opt-in CLI. Secret values and raw HTTP errors are never printed."""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from market_pipeline.telegram_delivery import DeliveryError, PrivateLedger, deliver, send_message


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--report", type=Path, required=True)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    try:
        payload = json.loads(args.report.read_text(encoding="utf-8"))
        if args.dry_run:
            result = deliver(payload, dry_run=True)
        else:
            if os.getenv("TELEGRAM_NOTIFICATIONS_ENABLED") != "true":
                raise DeliveryError("telegram_not_enabled")
            token = os.getenv("TELEGRAM_BOT_TOKEN", "")
            chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
            ledger = PrivateLedger(os.getenv("TELEGRAM_LEDGER_REPO", ""),
                                   os.getenv("TELEGRAM_LEDGER_TOKEN", ""))
            result = deliver(payload, ledger, lambda msg: send_message(token, chat_id, msg),
                             dry_run=False)
        print("Telegram " + result["mode"] + ": " + str(result["events"]) +
              " events, " + str(result["messages"]) + " messages.")
        return 0
    except (DeliveryError, KeyError, OSError, ValueError) as err:
        category = str(err) if isinstance(err, DeliveryError) else "invalid_report"
        print("Telegram safely stopped: " + category)
        return 1


if __name__ == "__main__":
    sys.exit(main())
