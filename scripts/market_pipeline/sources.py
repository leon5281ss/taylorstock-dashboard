import json
import math
import time
from datetime import date
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

FINMIND = "https://api.finmindtrade.com/api/v4/data"
DATASETS = {
    "price": "TaiwanStockPrice",
    "institutional": "TaiwanStockInstitutionalInvestorsBuySell",
    "margin": "TaiwanStockMarginPurchaseShortSale",
}
OFFICIAL = {
    "TWSE_price": "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL",
    "TPEX_price": "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes",
    "TPEX_institutional": "https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading",
    "TPEX_margin": "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_margin_balance",
}
HOLIDAYS = "https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule"


class SourceError(Exception):
    pass


def number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(str(value).replace(",", "").strip())
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def iso_date(value):
    text = str(value).strip().replace("/", "-")
    if "-" in text:
        year, month, day = map(int, text[:10].split("-"))
    elif len(text) in (7, 8):
        year, month, day = int(text[:-4]), int(text[-4:-2]), int(text[-2:])
    else:
        raise ValueError("invalid_date")
    return date(year + 1911 if year < 1911 else year, month, day).isoformat()


class HttpClient:
    def __init__(self, token="", attempts=3, sleep=time.sleep):
        self.token = token
        self.attempts = attempts
        self.sleep = sleep

    def get(self, url, params=None, authenticated=False, as_text=False):
        headers = {"User-Agent": "taylorstock-dashboard/3", "Accept": "application/json,application/xml,text/html"}
        if authenticated and self.token:
            headers["Authorization"] = "Bearer " + self.token
        target = url + ("?" + urlencode(params) if params else "")
        failure = "network_error"
        for attempt in range(self.attempts):
            try:
                with urlopen(Request(target, headers=headers), timeout=25) as response:
                    raw = response.read(15_000_000).decode("utf-8-sig")
                payload = raw if as_text else json.loads(raw)
                if authenticated and isinstance(payload, dict):
                    message = str(payload.get("msg", "")).lower()
                    if "update your user level" in message:
                        raise SourceError("permission_denied")
                    if payload.get("status", 200) != 200:
                        raise SourceError("api_error")
                return payload
            except HTTPError as exc:
                if exc.code in (400, 401, 403):
                    if authenticated:
                        body = exc.read(4096).decode("utf-8", errors="replace").lower()
                        if "update your user level" in body:
                            raise SourceError("permission_denied") from None
                    raise SourceError("http_" + str(exc.code)) from None
                failure = "http_" + str(exc.code)
                if exc.code not in (429, 500, 502, 503, 504):
                    break
            except (URLError, TimeoutError, OSError):
                failure = "network_error"
            except (ValueError, UnicodeError):
                failure = "invalid_response"
            if attempt + 1 < self.attempts:
                self.sleep(2 ** attempt)
        raise SourceError(failure) from None

    def dataset(self, dataset, start, end, code=None):
        params = {"dataset": dataset, "start_date": start, "end_date": end}
        if code:
            params["data_id"] = code
        payload = self.get(FINMIND, params, authenticated=True)
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise SourceError("invalid_response")
        return payload["data"]


def normalize_finmind(kind, records, code, start, end):
    grouped, issues = {}, []
    for raw in records:
        try:
            day = iso_date(raw["date"])
        except (KeyError, ValueError, TypeError):
            issues.append("invalid_date")
            continue
        if raw.get("stock_id") != code or not start <= day <= end:
            issues.append("wrong_symbol_or_date")
            continue
        grouped.setdefault(day, []).append(raw)
    normalized = []
    for day, group in sorted(grouped.items()):
        fields = {}
        if kind == "institutional":
            names = {row.get("name"): row for row in group}
            if len(names) != len(group):
                issues.append(day + ":duplicate")
                continue
            for field, members in {
                "foreign": ["Foreign_Investor", "Foreign_Dealer_Self"],
                "trust": ["Investment_Trust"],
                "dealer": ["Dealer_self", "Dealer_Hedging"],
            }.items():
                pairs = [(number(names.get(name, {}).get("buy")), number(names.get(name, {}).get("sell"))) for name in members]
                fields[field] = sum(buy - sell for buy, sell in pairs) if all(buy is not None and sell is not None and buy >= 0 and sell >= 0 for buy, sell in pairs) else None
        elif len(group) != 1:
            issues.append(day + ":duplicate")
            continue
        elif kind == "price":
            raw = group[0]
            fields = {field: number(raw.get(source)) for field, source in {"close": "close", "volume": "Trading_Volume", "open": "open", "high": "max", "low": "min"}.items()}
            if any(value is None for value in fields.values()) or not (0 < fields["low"] <= min(fields["close"], fields["open"]) <= max(fields["close"], fields["open"]) <= fields["high"]) or fields["volume"] < 0:
                issues.append(day + ":invalid_ohlcv")
                continue
        else:
            raw = group[0]
            for prefix, source in (("margin", "MarginPurchase"), ("short", "ShortSale")):
                current, previous = number(raw.get(source + "TodayBalance")), number(raw.get(source + "YesterdayBalance"))
                fields[prefix] = current if current is not None and current >= 0 else None
                fields[prefix + "Previous"] = previous if previous is not None and previous >= 0 else None
                fields[prefix + "Change"] = current - previous if fields[prefix] is not None and fields[prefix + "Previous"] is not None else None
        if any(value is None for value in fields.values()):
            issues.append(day + ":missing_fields")
        normalized.append({"date": day, **fields, "source": DATASETS[kind], "units": "TWD/shares" if kind == "price" else "shares" if kind == "institutional" else "lots"})
    return normalized, sorted(set(issues))


def official_snapshots(client, target):
    output = {}
    for key, url in OFFICIAL.items():
        try:
            records = client.get(url)
            if not isinstance(records, list):
                raise SourceError("invalid_response")
            output[key] = {"rows": records, "url": url, "status": "ok"}
        except SourceError as exc:
            output[key] = {"rows": [], "url": url, "status": str(exc)}
    for kind, path, select in (("price", "afterTrading/MI_INDEX", "ALLBUT0999"), ("institutional", "fund/T86", "ALLBUT0999"), ("margin", "marginTrading/MI_MARGN", "ALL")):
        url = "https://www.twse.com.tw/rwd/zh/" + path
        try:
            payload = client.get(url, {"date": target.replace("-", ""), "response": "json", "type" if kind == "price" else "selectType": select})
            if payload.get("stat") != "OK" or iso_date(payload.get("date")) != target:
                raise SourceError("not_published")
            if kind == "price":
                tables = [table for table in payload["tables"] if "證券代號" in table.get("fields", []) and "收盤價" in table.get("fields", [])]
                if len(tables) != 1:
                    raise SourceError("schema_changed")
                records = []
                for values in tables[0]["data"]:
                    row = dict(zip(tables[0]["fields"], values))
                    records.append({"Code": row["證券代號"], "ClosingPrice": row["收盤價"], "TradeVolume": row["成交股數"]})
            elif kind == "institutional":
                fields = payload["fields"]
                records = [dict(zip(fields, row)) for row in payload["data"]]
            else:
                tables = [table for table in payload["tables"] if table.get("fields", [])[:2] == ["代號", "名稱"]]
                if len(tables) != 1 or len(tables[0]["fields"]) != 16:
                    raise SourceError("schema_changed")
                records = [{"Code": row[0], "margin": row[6], "marginPrevious": row[5], "short": row[12], "shortPrevious": row[11]} for row in tables[0]["data"]]
            output["TWSE_" + kind] = {"rows": [{**row, "Date": target} for row in records], "url": url, "status": "ok"}
        except (SourceError, KeyError, ValueError, TypeError, IndexError) as exc:
            failure = str(exc) if isinstance(exc, SourceError) else "schema_changed"
            if kind == "price" and output["TWSE_price"]["status"] == "ok":
                output["TWSE_price"]["fallbackReason"] = failure
            else:
                output["TWSE_" + kind] = {"rows": [], "url": url, "status": failure}
    return output


def official_record(snapshot, market, kind, code):
    for raw in snapshot["rows"]:
        candidate = raw.get("Code", raw.get("SecuritiesCompanyCode", raw.get("證券代號", "")))
        if str(candidate).strip() != code:
            continue
        try:
            day = iso_date(raw.get("Date"))
        except (ValueError, TypeError):
            return None
        if kind == "price":
            values = {"close": number(raw.get("ClosingPrice" if market == "TWSE" else "Close")), "volume": number(raw.get("TradeVolume" if market == "TWSE" else "TradingShares"))}
        elif kind == "institutional" and market == "TWSE":
            foreign = [number(raw.get(field)) for field in ("外陸資買賣超股數(不含外資自營商)", "外資自營商買賣超股數")]
            values = {"foreign": sum(foreign) if all(value is not None for value in foreign) else None, "trust": number(raw.get("投信買賣超股數")), "dealer": number(raw.get("自營商買賣超股數"))}
        elif kind == "institutional":
            cleaned = {key.replace(" ", ""): value for key, value in raw.items()}
            values = {"foreign": number(cleaned.get("ForeignInvestorsIncludeMainlandAreaInvestors-Difference")), "trust": number(cleaned.get("SecuritiesInvestmentTrustCompanies-Difference")), "dealer": number(cleaned.get("Dealers-Difference"))}
        elif market == "TWSE":
            values = {key: number(raw.get(key)) for key in ("margin", "marginPrevious", "short", "shortPrevious")}
        else:
            values = {key: number(raw.get(field)) for key, field in {"margin": "MarginPurchaseBalance", "marginPrevious": "MarginPurchaseBalancePreviousDay", "short": "ShortSaleBalance", "shortPrevious": "ShortSaleBalancePreviousDay"}.items()}
        return {"date": day, **values}
    return None


def compare_official(latest, official, source):
    result = {"source": source["url"], "status": "unverified", "officialDate": official.get("date") if official else None}
    if source["status"] != "ok":
        result["reason"] = source["status"]
    elif not official or not latest:
        result["reason"] = "missing_record"
    elif official["date"] != latest["date"]:
        result["reason"] = "date_mismatch"
    elif any(value is None for value in official.values()):
        result["reason"] = "missing_fields"
    else:
        differences = {key: {"finmind": latest.get(key), "official": value} for key, value in official.items() if key != "date" and (latest.get(key) is None or abs(latest[key] - value) > (0.005 if key == "close" else 0))}
        result.update(status="mismatch" if differences else "verified", differences=differences)
    return result


def government_bank(client, code, start, end, enabled=False):
    source = "TaiwanStockGovernmentBankBuySell"
    if not enabled:
        return {"status": "permission_denied", "label": "無權限", "source": source, "date": None, "netBuy": None, "reason": "register 帳戶無 Sponsor 權限；模組尚未啟用"}
    try:
        rows = client.dataset(source, start, end, code)
        aggregate = [row for row in rows if row.get("bank_name") == "八大官股" and row.get("stock_id") == code and start <= row.get("date", "") <= end]
        return {"status": "adapter_pending", "label": "待接入驗證", "source": source, "date": max((row["date"] for row in aggregate), default=None), "netBuy": None, "reason": "已取得回應，需驗證單位及欄位後才啟用數值"}
    except SourceError as exc:
        return {"status": str(exc), "label": "無權限" if str(exc) == "permission_denied" else "查詢失敗", "source": source, "date": None, "netBuy": None}

