from __future__ import annotations

import json
import math
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
API = "https://api.finmindtrade.com/api/v4/data"


def request_json(params: dict) -> dict:
    url = f"{API}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "taylorstock-dashboard-public"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


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
    df = pd.DataFrame(data["data"]).rename(columns={"max": "high", "min": "low", "Trading_Volume": "volume"})
    df["date"] = pd.to_datetime(df["date"])
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for w in [5, 10, 20, 60, 120, 240]:
        df[f"ma{w}"] = df["close"].rolling(w).mean()
    df["vol20"] = df["volume"].rolling(20).mean()
    low9 = df["low"].rolling(9).min()
    high9 = df["high"].rolling(9).max()
    rsv = (df["close"] - low9) / (high9 - low9) * 100
    k_values, d_values, last_k, last_d = [], [], 50.0, 50.0
    for value in rsv:
        if pd.isna(value):
            k_values.append(math.nan)
            d_values.append(math.nan)
        else:
            last_k = last_k * 2 / 3 + float(value) / 3
            last_d = last_d * 2 / 3 + last_k / 3
            k_values.append(last_k)
            d_values.append(last_d)
    df["k"] = k_values
    df["d"] = d_values
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


def round_or_none(value, digits=2):
    if value is None or pd.isna(value):
        return None
    return round(float(value), digits)


def evaluate(row: pd.Series, prev: pd.Series | None, count: int) -> tuple[str, int, list[str], str]:
    if count < 120 or pd.isna(row.get("ma120")):
        return "資料不足", 45, ["歷史資料不足，無法完整判斷 MA120/長期趨勢"], "是"
    status = "保留"
    reasons: list[str] = []
    order = {"保留": 0, "觀察": 1, "減碼警訊": 2, "出場警訊": 3, "資料不足": 4}

    def raise_to(new_status: str, reason: str) -> None:
        nonlocal status
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
    score = {"保留": 88, "觀察": 72, "減碼警訊": 48, "出場警訊": 35, "資料不足": 45}[status]
    return status, score, reasons, "是" if status in {"減碼警訊", "出場警訊", "資料不足"} else "否"


def build_stock(item: dict) -> dict:
    df = add_indicators(fetch_price(item["code"]))
    row = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else None
    status, score, reasons, manual = evaluate(row, prev, len(df))
    return {
        "code": item["code"],
        "name": item["name"],
        "market": item.get("market", "TWSE"),
        "category": item.get("category"),
        "shares": None,
        "averageCost": None,
        "price": round_or_none(row["close"]),
        "marketValue": None,
        "unrealizedPnl": None,
        "unrealizedPnlRate": None,
        "totalScore": score,
        "status": status,
        "technicalStatus": status,
        "riskReasons": reasons,
        "manualCheck": manual,
        "updatedAt": row["date"].date().isoformat(),
        "sourceStatus": "成功",
        "sourceLabel": "FinMind TaiwanStockPrice",
        "technical": {
            "open": round_or_none(row["open"]),
            "high": round_or_none(row["high"]),
            "low": round_or_none(row["low"]),
            "close": round_or_none(row["close"]),
            "volume": round_or_none(row["volume"], 0),
            "ma5": round_or_none(row["ma5"]),
            "ma10": round_or_none(row["ma10"]),
            "ma20": round_or_none(row["ma20"]),
            "ma60": round_or_none(row["ma60"]),
            "ma120": round_or_none(row["ma120"]),
            "ma240": round_or_none(row["ma240"]),
            "k": round_or_none(row["k"]),
            "d": round_or_none(row["d"]),
            "j": round_or_none(row["j"]),
            "macd": round_or_none(row["macd"], 4),
            "macdSignal": round_or_none(row["macdSignal"], 4),
            "macdHistogram": round_or_none(row["macdHist"], 4),
            "rsi": round_or_none(row["rsi"]),
            "return20d": round_or_none(row["return20d"], 4),
            "return60d": round_or_none(row["return60d"], 4),
            "return120d": round_or_none(row["return120d"], 4),
        },
        "scores": {"technical": score, "fundamental": None, "chip": None, "news": None, "total": score},
        "details": {
            "revenue": {"基本面警訊": "公開版未揭露私有基本面資料"},
            "chip": {"籌碼警訊": "公開版未揭露私有籌碼明細"},
            "financial": {"財報警訊": "公開版未揭露私有財報明細"},
            "news": {"新聞風險警訊": "公開版未揭露私有新聞明細"},
            "score": {"總分": score, "第二階段狀態": status, "主要理由": "；".join(reasons)},
        },
    }


def fallback_stock(item: dict, exc: Exception) -> dict:
    reason = f"公開資料更新失敗：{exc}"
    return {
        "code": item["code"],
        "name": item["name"],
        "market": item.get("market", "TWSE"),
        "category": item.get("category"),
        "shares": None,
        "averageCost": None,
        "price": None,
        "marketValue": None,
        "unrealizedPnl": None,
        "unrealizedPnlRate": None,
        "totalScore": 30,
        "status": "資料不足",
        "technicalStatus": "資料不足",
        "riskReasons": [reason],
        "manualCheck": "是",
        "updatedAt": date.today().isoformat(),
        "sourceStatus": reason,
        "sourceLabel": "FinMind TaiwanStockPrice",
        "technical": {},
        "scores": {"technical": 30, "fundamental": None, "chip": None, "news": None, "total": 30},
        "details": {"score": {"主要理由": reason}},
    }


def main() -> None:
    watchlist = json.loads((ROOT / "config" / "watchlist_public.json").read_text(encoding="utf-8"))
    stocks = []
    for item in watchlist:
        try:
            stocks.append(build_stock(item))
        except Exception as exc:
            stocks.append(fallback_stock(item, exc))
    scores = [s["totalScore"] for s in stocks if isinstance(s.get("totalScore"), (int, float))]
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
            "averageScore": round(sum(scores) / len(scores), 1) if scores else None,
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
