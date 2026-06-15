from __future__ import annotations

import json
import math
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = Path(__file__).resolve().parents[1]
API = "https://api.finmindtrade.com/api/v4/data"


def request_json(params: dict) -> dict:
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


def load_private_positions() -> dict[str, dict]:
    secret_b64 = os.environ.get("POSITIONS_PRIVATE_JSON_B64", "").strip()
    if secret_b64:
        import base64

        raw = base64.b64decode(secret_b64.encode("utf-8")).decode("utf-8")
        data = json.loads(raw)
    else:
        path = ROOT / "config" / "positions_private.json"
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
    out = {}
    for item in data if isinstance(data, list) else []:
        code = str(item.get("code", "")).strip()
        if code:
            out[code.zfill(4) if code.isdigit() else code] = item
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
    positions = load_private_positions()
    stocks = []
    for item in watchlist:
        try:
            df = indicators(fetch_price(item["code"]))
            row = df.iloc[-1]
            prev = df.iloc[-2] if len(df) > 1 else None
            status, score, reasons, manual = evaluate(row, prev, len(df))
            stock = {
                "code": item["code"],
                "name": item["name"],
                "market": item.get("market", "TWSE"),
                "category": item.get("category"),
                "price": fnum(row["close"]),
                "unrealizedPnlRate": None,
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
                    "revenue": {"基本面警訊": "公開版未揭露私有基本面欄位"},
                    "chip": {"籌碼警訊": "公開版未揭露私有籌碼欄位"},
                    "financial": {"財報警訊": "公開版未揭露私有財報欄位"},
                    "news": {"新聞風險警訊": "公開版未揭露私有新聞欄位"},
                    "score": {"總分": score, "第二階段狀態": status, "主要理由": "；".join(reasons)},
                },
            }
        except Exception as exc:
            stock = {
                "code": item["code"],
                "name": item["name"],
                "market": item.get("market", "TWSE"),
                "category": item.get("category"),
                "price": None,
                "unrealizedPnlRate": None,
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
    for stock in stocks:
        pos = positions.get(stock["code"], {})
        price = stock.get("price")
        cost = pos.get("averageCost")
        shares = pos.get("shares")
        if price is None:
            stock["unrealizedPnlRate"] = "缺價格" if shares else "非持倉"
        elif not shares:
            stock["unrealizedPnlRate"] = "非持倉"
        elif cost in (None, 0, ""):
            stock["unrealizedPnlRate"] = "缺成本"
        else:
            stock["unrealizedPnlRate"] = round((float(price) - float(cost)) / float(cost) * 100, 2)
    numeric_scores = [s["totalScore"] for s in stocks if isinstance(s.get("totalScore"), (int, float))]
    payload = {
        "generatedAt": datetime.now(ZoneInfo("Asia/Taipei")).isoformat(timespec="seconds"),
        "privacy": {
            "publicDashboard": True,
            "positionAmountsPublished": False,
            "sharesPublished": False,
            "averageCostPublished": False,
            "rawSourcePathsPublished": False,
        },
        "summary": {
            "asOf": date.today().isoformat(),
            "totalMarketValue": None,
            "totalUnrealizedPnl": None,
            "overallReturnRate": None,
            "exitCount": sum(1 for s in stocks if s["status"] == "出場警訊"),
            "reduceCount": sum(1 for s in stocks if s["status"] == "減碼警訊"),
            "manualCheckCount": sum(1 for s in stocks if s["manualCheck"] == "是"),
            "stockCount": len(stocks),
            "averageScore": round(sum(numeric_scores) / len(numeric_scores), 1) if numeric_scores else None,
            "positionAmountsPublished": False,
        },
        "stocks": stocks,
        "disclaimer": "本系統僅供投資追蹤與風險提示，不構成買賣建議，不得自動下單，所有決策需人工確認。",
    }
    out = ROOT / "docs" / "data"
    out.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    (out / "stocks.json").write_text(text, encoding="utf-8")
    (out / "stocks-data.js").write_text("window.STOCK_DASHBOARD_DATA = " + text + ";\n", encoding="utf-8")


if __name__ == "__main__":
    main()
