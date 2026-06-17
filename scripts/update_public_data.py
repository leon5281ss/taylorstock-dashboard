from __future__ import annotations

import base64
import json
import math
import os
from decimal import Decimal
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from collections.abc import Mapping, Sequence

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = Path(__file__).resolve().parents[1]
API = "https://api.finmindtrade.com/api/v4/data"
SOURCE_CONFIG = ROOT / "config" / "data_sources_public.json"


def request_json(params: dict) -> dict:
    token = os.environ.get("FINMIND_TOKEN", "").strip()
    if token and "token" not in params:
        params = dict(params)
        params["token"] = token
    session = requests.Session()
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        status=3,
        backoff_factor=1.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    headers = {
        "User-Agent": "stock-dashboard-public (+https://github.com/leon5281ss/taylorstock-dashboard)",
        "Accept": "application/json,text/plain,*/*",
    }
    try:
        resp = session.get(API, params=params, headers=headers, timeout=30)
        resp.raise_for_status()
        return resp.json()
    finally:
        session.close()


def safe_print(message: str) -> None:
    print(message, flush=True)


def json_default_fallback(value: object) -> object:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    try:
        import numpy as np

        if isinstance(value, np.integer):
            return int(value)
        if isinstance(value, np.floating):
            number = float(value)
            return None if not math.isfinite(number) else number
        if isinstance(value, np.bool_):
            return bool(value)
    except Exception:
        pass
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    safe_print(f"Unsupported JSON type fallback: {type(value).__name__}")
    return str(value)


def to_json_safe(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): to_json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_json_safe(v) for v in value]
    if isinstance(value, pd.Series):
        return to_json_safe(value.to_dict())
    if isinstance(value, pd.DataFrame):
        return to_json_safe(value.to_dict(orient="records"))
    try:
        import numpy as np

        if isinstance(value, np.integer):
            return int(value)
        if isinstance(value, np.floating):
            return float(value)
        if isinstance(value, np.bool_):
            return bool(value)
        if isinstance(value, np.ndarray):
            return [to_json_safe(v) for v in value.tolist()]
    except Exception:
        pass
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    if hasattr(value, "item"):
        try:
            return to_json_safe(value.item())
        except Exception:
            pass
    return str(value)


def collect_non_json_types(value: object, path: str = "payload", found: list[tuple[str, str]] | None = None, limit: int = 10) -> list[tuple[str, str]]:
    if found is None:
        found = []
    if len(found) >= limit:
        return found
    if value is None or isinstance(value, (str, int, float, bool)):
        return found
    if isinstance(value, Decimal):
        return found
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return found
    if isinstance(value, dict):
        for key, item in value.items():
            collect_non_json_types(item, f'{path}["{key}"]', found, limit)
            if len(found) >= limit:
                break
        return found
    if isinstance(value, (list, tuple)):
        for idx, item in enumerate(value):
            collect_non_json_types(item, f"{path}[{idx}]", found, limit)
            if len(found) >= limit:
                break
        return found
    if isinstance(value, pd.Series):
        return collect_non_json_types(value.to_dict(), path, found, limit)
    if isinstance(value, pd.DataFrame):
        return collect_non_json_types(value.to_dict(orient="records"), path, found, limit)
    try:
        import numpy as np

        if isinstance(value, (np.integer, np.floating, np.bool_, np.ndarray)):
            return found
    except Exception:
        pass
    try:
        if pd.isna(value):
            return found
    except Exception:
        pass
    found.append((type(value).__name__, path))
    return found


def write_json_safe(path: Path, payload: object) -> None:
    safe_payload = to_json_safe(payload)
    unsafe = collect_non_json_types(safe_payload)
    for type_name, found_path in unsafe:
        safe_print(f"Non JSON-safe type found: {type_name} at {found_path}")
    with path.open("w", encoding="utf-8") as fh:
        json.dump(
            safe_payload,
            fh,
            ensure_ascii=False,
            separators=(",", ":"),
            default=json_default_fallback,
        )
    safe_print(f"JSON written: {path}")


def load_source_config() -> dict[str, dict]:
    if SOURCE_CONFIG.exists():
        return json.loads(SOURCE_CONFIG.read_text(encoding="utf-8"))
    return {}


def normalize_code(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    upper = text.upper()
    for suffix in (".TW", ".TWO", ".TPE"):
        if upper.endswith(suffix):
            text = text[: -len(suffix)]
            break
    try:
        num = float(text)
        if num.is_integer():
            text = str(int(num))
        else:
            text = str(num)
    except ValueError:
        pass
    text = text.strip()
    if text.isdigit() and len(text) < 4:
        text = text.zfill(4)
    return text


def first_present(record: dict, keys: list[str]) -> object:
    for key in keys:
        if key in record and record.get(key) not in (None, ""):
            return record.get(key)
    return None


def load_private_positions() -> tuple[dict[str, dict], dict[str, object]]:
    secret_b64 = os.environ.get("POSITIONS_PRIVATE_JSON_B64", "").strip()
    source_exists = False
    source_readable = False
    if secret_b64:
        raw = base64.b64decode(secret_b64.encode("utf-8")).decode("utf-8")
        data = json.loads(raw)
        source_exists = True
        source_readable = True
    else:
        path = ROOT / "config" / "positions_private.json"
        if not path.exists():
            return {}, {
                "exists": False,
                "readable": False,
                "count": 0,
                "fields": [],
                "matched_codes": [],
                "unmatched_codes": [],
            }
        data = json.loads(path.read_text(encoding="utf-8"))
        source_exists = True
        source_readable = True
    out = {}
    fields: set[str] = set()
    for item in data if isinstance(data, list) else []:
        fields.update(item.keys())
        code = normalize_code(first_present(item, ["code", "stockCode", "ticker", "股票代號", "代號"]))
        if code:
            out[code] = item
    return out, {
        "exists": source_exists,
        "readable": source_readable,
        "count": len(out),
        "fields": sorted(fields),
        "matched_codes": [],
        "unmatched_codes": [],
    }


def fetch_finmind_dataset(dataset: str, stock_id: str, start_date: date, end_date: date) -> pd.DataFrame:
    params = {
        "dataset": dataset,
        "data_id": stock_id,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
    }
    token_present = bool(os.environ.get("FINMIND_TOKEN", "").strip())
    safe_print(f"FinMind request start: dataset={dataset} code={stock_id} token_present={'yes' if token_present else 'no'}")
    try:
        data = request_json(params)
    except Exception as exc:
        safe_print(f"FinMind request failed: dataset={dataset} code={stock_id} http_status=unknown rows=0 error_type={type(exc).__name__} error={exc}")
        raise
    status_code = data.get("status") if isinstance(data, dict) else None
    rows = len(data.get("data") or []) if isinstance(data, dict) else 0
    if not isinstance(data, dict):
        safe_print(f"FinMind request failed: dataset={dataset} code={stock_id} http_status=unknown rows=0 error_type=ParseError error=API 回傳格式不符")
        raise RuntimeError("API 回傳格式不符")
    if status_code not in (200, "200"):
        safe_print(f"FinMind request failed: dataset={dataset} code={stock_id} http_status={status_code} rows={rows} error_type=APIError error={data.get('msg') or 'no data returned'}")
        raise RuntimeError(data.get("msg") or "no data returned")
    if not data.get("data"):
        safe_print(f"FinMind request failed: dataset={dataset} code={stock_id} http_status={status_code} rows=0 error_type=NoDataError error=no data returned")
        raise RuntimeError(data.get("msg") or "no data returned")
    df = pd.DataFrame(data["data"])
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
    safe_print(f"FinMind request ok: dataset={dataset} code={stock_id} http_status={status_code} rows={len(df)}")
    return df


def row_to_dict(row: pd.Series | None, fields: list[tuple[str, str]], default_status: str, warning_key: str, warning_value: str) -> dict[str, object]:
    if row is None or row.empty:
        return {k: "API 未取得" for _, k in fields} | {warning_key: warning_value, "狀態": default_status}
    out: dict[str, object] = {}
    for source_key, target_key in fields:
        out[target_key] = row.get(source_key, "API 未取得")
    out[warning_key] = warning_value
    out["狀態"] = default_status
    return out


def fetch_price(code: str) -> pd.DataFrame:
    end = date.today()
    start = end - timedelta(days=430)
    data = request_json(
        {
            "dataset": "TaiwanStockPrice",
            "data_id": code,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
        }
    )
    if data.get("status") not in (200, "200") or not data.get("data"):
        raise RuntimeError(data.get("msg") or "no data")
    df = pd.DataFrame(data["data"]).rename(
        columns={
            "max": "high",
            "min": "low",
            "Trading_Volume": "volume",
        }
    )
    df["date"] = pd.to_datetime(df["date"])
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)


def indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for w in [5, 10, 20, 60, 120, 240]:
        df[f"ma{w}"] = df["close"].rolling(w).mean()
    df["vol20"] = df["volume"].rolling(20).mean()
    low9 = df["low"].rolling(9).min()
    high9 = df["high"].rolling(9).max()
    rsv = (df["close"] - low9) / (high9 - low9) * 100
    k, d, kp, dp = [], [], 50.0, 50.0
    for val in rsv:
        if pd.isna(val):
            k.append(math.nan)
            d.append(math.nan)
        else:
            kp = kp * 2 / 3 + float(val) / 3
            dp = dp * 2 / 3 + kp / 3
            k.append(kp)
            d.append(dp)
    df["k"], df["d"] = k, d
    df["j"] = 3 * df["k"] - 2 * df["d"]
    ema12 = df["close"].ewm(span=12, adjust=False).mean()
    ema26 = df["close"].ewm(span=26, adjust=False).mean()
    df["macd"] = ema12 - ema26
    df["macdSignal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macdHist"] = df["macd"] - df["macdSignal"]
    delta = df["close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    df["rsi"] = 100 - 100 / (1 + gain / loss)
    df["return20d"] = df["close"] / df["close"].shift(20) - 1
    df["return60d"] = df["close"] / df["close"].shift(60) - 1
    df["return120d"] = df["close"] / df["close"].shift(120) - 1
    df["drawdown60"] = df["close"] / df["high"].rolling(60).max() - 1
    df["drawdown120"] = df["close"] / df["high"].rolling(120).max() - 1
    return df


def fnum(value, digits=2):
    if value is None or pd.isna(value):
        return None
    return round(float(value), digits)


def evaluate(row: pd.Series, prev: pd.Series | None, count: int) -> tuple[str, int, list[str], str]:
    if count < 120 or pd.isna(row.get("ma120")):
        return "資料不足", 45, ["歷史資料不足，無法完整判斷 MA120/長期趨勢"], "是"
    status, reasons = "保留", []

    def raise_to(new_status: str, reason: str):
        nonlocal status
        order = {"保留": 0, "觀察": 1, "減碼警訊": 2, "出場警訊": 3}
        if order[new_status] > order[status]:
            status = new_status
        reasons.append(reason)

    if row["close"] < row["ma20"]:
        raise_to("觀察", "收盤價跌破 MA20")
    if row["close"] < row["ma60"]:
        raise_to("減碼警訊", "收盤價跌破 MA60")
    if row["close"] < row["ma120"]:
        raise_to("出場警訊", "收盤價跌破 MA120")
    if prev is not None and prev["macd"] >= prev["macdSignal"] and row["macd"] < row["macdSignal"] and row["macdHist"] < prev["macdHist"]:
        raise_to("減碼警訊", "MACD 死亡交叉且柱狀體擴大")
    if prev is not None and prev["k"] >= prev["d"] and row["k"] < row["d"] and row["k"] > 80:
        raise_to("觀察", "KDJ 高檔死亡交叉")
    if row["close"] < row["open"] and row["volume"] > row["vol20"] * 1.5:
        raise_to("減碼警訊", "放量收黑 K")
    if row["drawdown60"] <= -0.15:
        raise_to("減碼警訊", "近 60 日高點回落超過 15%")
    elif row["drawdown60"] <= -0.10:
        raise_to("觀察", "近 60 日高點回落超過 10%")
    if row["drawdown120"] <= -0.20:
        raise_to("出場警訊", "近 120 日高點回落超過 20%")
    if not reasons:
        reasons.append("未觸發主要技術警訊")
    score = {"保留": 88, "觀察": 72, "減碼警訊": 48, "出場警訊": 35}[status]
    return status, score, reasons, "是" if status in {"減碼警訊", "出場警訊"} else "否"


def main() -> None:
    watchlist = json.loads((ROOT / "config" / "watchlist_public.json").read_text(encoding="utf-8"))
    positions, position_meta = load_private_positions()
    source_cfg = load_source_config()
    safe_print(f"FINMIND_TOKEN present: {'yes' if os.environ.get('FINMIND_TOKEN', '').strip() else 'no'}")
    safe_print(f"positions_private.json exists: {'yes' if position_meta['exists'] else 'no'}")
    safe_print(f"position_count: {position_meta['count']}")
    safe_print(f"public_stock_count: {len(watchlist)}")
    safe_print(f"matched_count: {len([item for item in watchlist if normalize_code(item.get('code')) in positions])}")
    unmatched_codes_preview = [normalize_code(item.get("code")) for item in watchlist if normalize_code(item.get("code")) not in positions]
    safe_print(f"unmatched_codes: {', '.join(unmatched_codes_preview) if unmatched_codes_preview else '(none)'}")
    stocks = []
    matched_codes: list[str] = []
    unmatched_codes: list[str] = []
    for item in watchlist:
        stock_code = normalize_code(item.get("code"))
        try:
            df = indicators(fetch_price(stock_code))
            row = df.iloc[-1]
            prev = df.iloc[-2] if len(df) > 1 else None
            status, score, reasons, manual = evaluate(row, prev, len(df))
            stock = {
                "code": stock_code,
                "name": item["name"],
                "market": item.get("market", "TWSE"),
                "category": item.get("category"),
                "price": fnum(row["close"]),
                "gainLossRate": None,
                "totalScore": score,
                "status": status,
                "technicalStatus": status,
                "riskReasons": reasons,
                "manualCheck": manual,
                "updatedAt": row["date"].date().isoformat(),
                "sourceStatus": "成功",
                "sourceLabel": "FinMind TaiwanStockPrice",
                "dataQualityStatus": "資料完整",
                "technical": {
                    "open": fnum(row["open"]),
                    "high": fnum(row["high"]),
                    "low": fnum(row["low"]),
                    "close": fnum(row["close"]),
                    "volume": fnum(row["volume"], 0),
                    "ma5": fnum(row["ma5"]),
                    "ma10": fnum(row["ma10"]),
                    "ma20": fnum(row["ma20"]),
                    "ma60": fnum(row["ma60"]),
                    "ma120": fnum(row["ma120"]),
                    "ma240": fnum(row["ma240"]),
                    "k": fnum(row["k"]),
                    "d": fnum(row["d"]),
                    "j": fnum(row["j"]),
                    "macd": fnum(row["macd"], 4),
                    "macdSignal": fnum(row["macdSignal"], 4),
                    "macdHistogram": fnum(row["macdHist"], 4),
                    "rsi": fnum(row["rsi"]),
                    "return20d": fnum(row["return20d"], 4),
                    "return60d": fnum(row["return60d"], 4),
                    "return120d": fnum(row["return120d"], 4),
                },
                "scores": {"technical": score, "fundamental": None, "chip": None, "news": None, "total": score},
                "details": {
                    "technical": {},
                    "revenue": {},
                    "chip": {},
                    "financial": {},
                    "news": {},
                    "score": {"總分": score, "第二階段狀態": status, "主要理由": "；".join(reasons)},
                },
            }
        except Exception as exc:
            stock = {
                "code": stock_code,
                "name": item["name"],
                "market": item.get("market", "TWSE"),
                "category": item.get("category"),
                "price": None,
                "gainLossRate": None,
                "totalScore": 30,
                "status": "資料不足",
                "technicalStatus": "資料不足",
                "riskReasons": [f"公開資料更新失敗：{exc}"],
                "manualCheck": "是",
                "updatedAt": date.today().isoformat(),
                "sourceStatus": f"失敗：{exc}",
                "sourceLabel": "FinMind TaiwanStockPrice",
                "dataQualityStatus": "API 失敗",
                "technical": {},
                "scores": {"technical": 30, "fundamental": None, "chip": None, "news": None, "total": 30},
                "details": {"score": {"主要理由": f"公開資料更新失敗：{exc}"}},
            }
        stocks.append(stock)
    # Enrich with public market data from FinMind
    for stock in stocks:
        code = normalize_code(stock["code"])
        if not code:
            continue
        try:
            rev_df = fetch_finmind_dataset("TaiwanStockMonthRevenue", code, date.today() - timedelta(days=365), date.today())
            rev_df = rev_df.sort_values("date")
            rev_latest = rev_df.iloc[-1] if not rev_df.empty else None
            rev_prev = rev_df.iloc[-2] if len(rev_df) > 1 else None
            stock["details"]["revenue"] = {
                "資料年月": rev_latest.get("date").date().isoformat() if rev_latest is not None and not pd.isna(rev_latest.get("date")) else "API 未取得",
                "當月營收": rev_latest.get("revenue") if rev_latest is not None else "API 未取得",
                "月增率": rev_latest.get("month_kd") if rev_latest is not None else "API 未取得",
                "年增率": rev_latest.get("year_growth") if rev_latest is not None else "API 未取得",
                "累計年增率": rev_latest.get("accumulated_year_growth") if rev_latest is not None else "API 未取得",
                "基本面警訊": "今日暫無資料",
                "基本面狀態": "資料完整" if rev_latest is not None else "API 未取得",
            }
        except Exception as exc:
            stock["details"]["revenue"] = {"資料年月": "API 未取得", "基本面警訊": str(exc), "基本面狀態": "API 未取得"}
        try:
            chip_df = fetch_finmind_dataset("TaiwanStockInstitutionalInvestorsBuySell", code, date.today() - timedelta(days=45), date.today())
            chip_df = chip_df.sort_values("date")
            chip_latest = chip_df.iloc[-1] if not chip_df.empty else None
            stock["details"]["chip"] = {
                "日期": chip_latest.get("date").date().isoformat() if chip_latest is not None and not pd.isna(chip_latest.get("date")) else "API 未取得",
                "外資買賣超": chip_latest.get("foreign_investor_buy_sell") if chip_latest is not None else "API 未取得",
                "投信買賣超": chip_latest.get("investment_trust_buy_sell") if chip_latest is not None else "API 未取得",
                "自營商買賣超": chip_latest.get("dealer_buy_sell") if chip_latest is not None else "API 未取得",
                "三大法人合計買賣超": chip_latest.get("total_buy_sell") if chip_latest is not None else "API 未取得",
                "近5日外資買賣超": "今日暫無資料",
                "籌碼警訊": "今日暫無資料",
                "籌碼狀態": "資料完整" if chip_latest is not None else "API 未取得",
            }
        except Exception as exc:
            stock["details"]["chip"] = {"日期": "API 未取得", "籌碼警訊": str(exc), "籌碼狀態": "API 未取得"}
        try:
            fin_df = fetch_finmind_dataset("TaiwanStockFinancialStatements", code, date.today() - timedelta(days=1200), date.today())
            per_df = fetch_finmind_dataset("TaiwanStockPER", code, date.today() - timedelta(days=45), date.today())
            fin_latest = fin_df.iloc[-1] if not fin_df.empty else None
            per_latest = per_df.iloc[-1] if not per_df.empty else None
            stock["details"]["financial"] = {
                "EPS": fin_latest.get("EPS") if fin_latest is not None else "API 未取得",
                "近四季EPS": "今日暫無資料",
                "毛利率": fin_latest.get("GrossProfitMargin") if fin_latest is not None else "API 未取得",
                "營業利益率": fin_latest.get("OperatingIncomeRatio") if fin_latest is not None else "API 未取得",
                "淨利率": fin_latest.get("NetIncomeRatio") if fin_latest is not None else "API 未取得",
                "本益比": per_latest.get("PER") if per_latest is not None else "API 未取得",
                "股價淨值比": per_latest.get("PBR") if per_latest is not None else "API 未取得",
                "殖利率": per_latest.get("dividend_yield") if per_latest is not None else "API 未取得",
                "財報警訊": "今日暫無資料",
                "財報狀態": "資料完整" if (fin_latest is not None or per_latest is not None) else "API 未取得",
            }
        except Exception as exc:
            stock["details"]["financial"] = {"EPS": "API 未取得", "財報警訊": str(exc), "財報狀態": "API 未取得"}
        try:
            news_df = fetch_finmind_dataset("TaiwanStockNews", code, date.today() - timedelta(days=90), date.today())
            news_df = news_df.sort_values("date") if "date" in news_df.columns else news_df
            news_latest = news_df.iloc[-1] if not news_df.empty else None
            stock["details"]["news"] = {
                "公司新聞標題": news_latest.get("title") if news_latest is not None else "API 未取得",
                "新聞日期": news_latest.get("date").date().isoformat() if news_latest is not None and not pd.isna(news_latest.get("date")) else "API 未取得",
                "新聞來源": news_latest.get("source") if news_latest is not None else "API 未取得",
                "新聞連結": news_latest.get("link") if news_latest is not None else "API 未取得",
                "新聞摘要": news_latest.get("summary") if news_latest is not None else "API 未取得",
                "正面/中性/負面": news_latest.get("sentiment") if news_latest is not None else "API 未取得",
                "是否重大利空": "今日暫無資料",
                "產業趨勢摘要": "今日暫無資料",
                "新聞風險警訊": "今日暫無資料",
                "新聞風險狀態": "資料完整" if news_latest is not None else "API 未取得",
            }
        except Exception as exc:
            stock["details"]["news"] = {"公司新聞標題": "API 未取得", "新聞風險警訊": str(exc), "新聞風險狀態": "API 未取得"}
        safe_print(
            "stock summary: "
            + " / ".join(
                [
                    code,
                    stock["name"],
                    f"revenue_has_data={'yes' if stock.get('details', {}).get('revenue', {}).get('基本面狀態') == '資料完整' else 'no'}",
                    f"chip_has_data={'yes' if stock.get('details', {}).get('chip', {}).get('籌碼狀態') == '資料完整' else 'no'}",
                    f"financial_has_data={'yes' if stock.get('details', {}).get('financial', {}).get('財報狀態') == '資料完整' else 'no'}",
                    f"news_has_data={'yes' if stock.get('details', {}).get('news', {}).get('新聞風險狀態') == '資料完整' else 'no'}",
                ]
            )
        )
    for stock in stocks:
        code = normalize_code(stock["code"])
        pos = positions.get(code, {})
        price = stock.get("price")
        cost = first_present(pos, ["averageCost", "avgCost", "cost", "成本均價", "平均成本", "買進均價", "持股成本", "庫存均價"])
        shares = first_present(pos, ["shares", "quantity", "qty", "持有股數", "股數", "庫存股數"])
        if code in positions:
            matched_codes.append(code)
        else:
            unmatched_codes.append(code)
        if price is None:
            stock["gainLossRate"] = "缺價格" if shares else "非持倉"
        elif not shares:
            stock["gainLossRate"] = "非持倉"
        elif cost in (None, 0, ""):
            stock["gainLossRate"] = "缺成本"
        else:
            stock["gainLossRate"] = round((float(price) - float(cost)) / float(cost) * 100, 2)
    numeric_scores = [s["totalScore"] for s in stocks if isinstance(s.get("totalScore"), (int, float))]
    summary_lines = [
        f"positions_private.json exists: {position_meta['exists']}",
        f"positions_private.json readable: {position_meta['readable']}",
        f"position count: {position_meta['count']}",
        f"public stock count: {len(stocks)}",
        f"matched codes: {', '.join(sorted(set(matched_codes))) if matched_codes else '(none)'}",
        f"unmatched codes: {', '.join(sorted(set(unmatched_codes))) if unmatched_codes else '(none)'}",
        f"position fields: {', '.join(position_meta['fields']) if position_meta['fields'] else '(none)'}",
    ]
    (ROOT / "logs").mkdir(parents=True, exist_ok=True)
    (ROOT / "logs" / f"family_view_match_summary_{date.today().isoformat()}.txt").write_text("\n".join(summary_lines), encoding="utf-8")
    data_sources = {
        "price": {"enabled": True, "provider": "TWSE OpenAPI + FinMind", "endpoint": "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"},
        "technical": {"enabled": True, "provider": "FinMind TaiwanStockPrice", "endpoint": "https://api.finmindtrade.com/api/v4/data"},
        "revenue": {"enabled": True, "provider": source_cfg.get("revenue", {}).get("provider", "FinMind TaiwanStockMonthRevenue"), "endpoint": "https://api.finmindtrade.com/api/v4/data"},
        "chip": {"enabled": True, "provider": source_cfg.get("chip", {}).get("provider", "FinMind TaiwanStockInstitutionalInvestorsBuySell"), "endpoint": "https://api.finmindtrade.com/api/v4/data"},
        "financial": {"enabled": True, "provider": source_cfg.get("financial", {}).get("provider", "FinMind TaiwanStockFinancialStatements + PER"), "endpoint": "https://api.finmindtrade.com/api/v4/data"},
        "news": {"enabled": True, "provider": source_cfg.get("news", {}).get("provider", "FinMind TaiwanStockNews"), "endpoint": "https://api.finmindtrade.com/api/v4/data"},
    }
    payload = {
        "generatedAt": datetime.now(ZoneInfo("Asia/Taipei")).isoformat(timespec="seconds"),
        "privacy": {
            "publicDashboard": True,
            "holdingsMasked": True,
            "costMasked": True,
            "rawSourcePathsMasked": True,
        },
        "summary": {
            "asOf": date.today().isoformat(),
            "portfolioValue": None,
            "portfolioPnl": None,
            "overallReturnRate": None,
            "exitCount": sum(1 for s in stocks if s["status"] == "出場警訊"),
            "reduceCount": sum(1 for s in stocks if s["status"] == "減碼警訊"),
            "manualCheckCount": sum(1 for s in stocks if s["manualCheck"] == "是"),
            "stockCount": len(stocks),
            "averageScore": round(sum(numeric_scores) / len(numeric_scores), 1) if numeric_scores else None,
            "positionAmountsMasked": True,
        },
        "stocks": stocks,
        "disclaimer": "本系統僅供投資追蹤與風險提示，不構成買賣建議，不得自動下單，所有決策需人工確認。",
        "dataSources": data_sources,
    }
    out = ROOT / "docs" / "data"
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "stocks.json"
    js_path = out / "stocks-data.js"
    write_json_safe(json_path, payload)
    text = json_path.read_text(encoding="utf-8")
    js_path.write_text("window.STOCK_DASHBOARD_DATA = " + text + ";\n", encoding="utf-8")


if __name__ == "__main__":
    main()
