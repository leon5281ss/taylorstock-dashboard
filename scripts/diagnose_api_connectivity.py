from __future__ import annotations

import importlib.util
import json
import os
import platform
import socket
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "logs"
OUT_DIR.mkdir(parents=True, exist_ok=True)
RUN_DATE = datetime.now().date().isoformat()
OUT_PATH = OUT_DIR / f"api_diagnosis_{RUN_DATE}.txt"

URLS = [
    ("Google", "https://www.google.com"),
    ("GitHub", "https://github.com"),
    ("TWSE", "https://www.twse.com.tw"),
    ("TPEx", "https://www.tpex.org.tw"),
    ("FinMind API", "https://api.finmindtrade.com/api/v4/data"),
]


def has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def classify_error(message: str) -> str:
    low = message.lower()
    if "winerror 10013" in low:
        return "Windows socket 權限問題"
    if "timed out" in low or "timeout" in low:
        return "HTTPS 連線失敗"
    if "name or service not known" in low or "getaddrinfo failed" in low or "temporary failure in name resolution" in low:
        return "DNS 失敗"
    if "403" in low or "401" in low or "forbidden" in low or "unauthorized" in low:
        return "API 權限不足"
    if "429" in low or "too many requests" in low:
        return "API 限流"
    if "html" in low and "json" in low:
        return "資料格式改變"
    return "其他未知錯誤"


def probe_url(url: str) -> dict[str, object]:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    result: dict[str, object] = {"url": url, "host": host}
    try:
        if host:
            result["dns"] = socket.getaddrinfo(host, parsed.port or 443)
        req = urllib.request.Request(url, headers={"User-Agent": "api-diagnose/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read(200).decode("utf-8", errors="replace")
            result["http_status"] = getattr(resp, "status", None)
            result["ok"] = True
            result["sample"] = body.replace("\n", " ")
    except Exception as exc:
        result["ok"] = False
        result["error"] = str(exc)
        result["classification"] = classify_error(str(exc))
    return result


def main() -> None:
    lines: list[str] = []
    lines.append(f"API diagnosis date: {RUN_DATE}")
    lines.append(f"Python version: {platform.python_version()}")
    lines.append(f"Executable: {sys.executable}")
    lines.append(f"requests available: {'yes' if has_module('requests') else 'no'}")
    lines.append(f"urllib available: yes")
    lines.append(f"proxy settings: {json.dumps({k: v for k, v in os.environ.items() if k.lower().endswith('_proxy')}, ensure_ascii=False)}")
    lines.append("")
    for label, url in URLS:
        lines.append(f"[{label}] {url}")
        res = probe_url(url)
        for key, value in res.items():
            if key == "dns":
                lines.append(f"- dns: ok ({len(value) if value else 0} records)")
            else:
                lines.append(f"- {key}: {value}")
        lines.append("")
    OUT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(OUT_PATH)


if __name__ == "__main__":
    main()
