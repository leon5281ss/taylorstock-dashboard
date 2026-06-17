from __future__ import annotations

from datetime import datetime

from zoneinfo import ZoneInfo

from update_stock_data import ROOT, has_finmind_token, load_config, precheck_finmind_connection, setup_logger


def main() -> None:
    config = load_config()
    timezone = config.get("timezone", "Asia/Taipei")
    run_date = datetime.now(ZoneInfo(timezone)).date().isoformat()
    log_path = ROOT / config["logs_folder"] / f"update_log_{run_date}.txt"
    logger = setup_logger(log_path)
    print(f"FINMIND_TOKEN: {'found' if has_finmind_token() else 'missing'}")
    try:
        precheck_finmind_connection(config, int(config.get("request_timeout_seconds", 20)), logger)
        print("FinMind API connection check passed")
    except Exception as exc:
        print(str(exc))
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
