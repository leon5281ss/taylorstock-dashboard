"""Opt-in Telegram delivery. Private ledger protects against duplicate sends."""
import base64
import hashlib
import json
from datetime import date, datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from .notifications import notification_plan
from .pipeline import assert_public
from .risk import LEVELS


class DeliveryError(Exception):
    pass


def validate(payload, now=None):
    assert_public(payload)
    s = payload.get("summary", {})
    if payload.get("riskModelVersion") != 1 or len(payload.get("stocks", [])) != 22 or s.get("stockCount") != 22:
        raise DeliveryError("invalid_public_snapshot")
    if payload.get("reportStatus") == "failed" or s.get("completeCount", 0) < 15:
        raise DeliveryError("insufficient_market_data")
    try:
        day = date.fromisoformat(s["asOf"])
    except (KeyError, TypeError, ValueError):
        raise DeliveryError("invalid_market_date") from None
    today = (now or datetime.now(ZoneInfo("Asia/Taipei"))).astimezone(ZoneInfo("Asia/Taipei")).date()
    if day > today or (today - day).days > 4:
        raise DeliveryError("stale_or_future_report")
    return s["asOf"]


def candidates(payload, state, now=None):
    day = validate(payload, now)
    delivered = {key: row["level"] for key, row in state.get("events", {}).items()
                 if row.get("status") in ("pending", "sent", "unknown") and row.get("level") in LEVELS}
    events = notification_plan(payload, delivered)
    daily_key = hashlib.sha256(("daily|" + day).encode()).hexdigest()
    if daily_key not in delivered:
        events.insert(0, {"scope": "digest", "eventKey": daily_key,
                          "level": "一般觀察", "date": day, "action": "new"})
    return events


def grouped_messages(payload, events):
    s = payload["summary"]
    header = ("台股22檔風險日報 " + s["asOf"] +
              "\n資料完整 " + str(s["completeCount"]) + "/22，人工確認 " +
              str(s.get("manualCheckCount", "未知")) +
              "；風險高 " + str(s.get("riskCounts", {}).get("高", "未知")) +
              "／中 " + str(s.get("riskCounts", {}).get("中", "未知")) +
              "\n僅公開市場警報；核對各項資料日期。")
    result, block, lines = [], [], []
    stock_lookup = {stock["code"]: stock for stock in payload["stocks"]}
    news_lookup = {item["eventId"]: item for item in payload.get("marketMonitor", {}).get("items", [])}
    for event in events:
        if event["scope"] == "digest":
            line = "每日摘要"
        elif event["scope"] == "market":
            item = news_lookup.get(event.get("article"), {})
            title = item.get("title", "公告標題待核對")
            line = event["date"] + " 市場政策：" + title[:75] + "（公告不代表實際護盤）"
        else:
            stock = stock_lookup.get(event["symbol"], {})
            matched = next((a for a in stock.get("alerts", [])
                            if a.get("rule") == event["rule"] and a.get("date") == event["date"]),
                           {})
            line = (event["date"] + " " + event["symbol"] + " " +
                    str(stock.get("name", ""))[:14] + " " + event["level"] +
                    "：" + str(matched.get("message", event["rule"]))[:95])
            if event.get("action") == "escalation":
                line += " [風險升級]"
        line = "• " + line[:180]
        if block and len(header + "\n".join(lines + [line])) > 3300:
            result.append((block, header + "\n\n" + "\n".join(lines)))
            block, lines = [], []
        block.append(event)
        lines.append(line)
    if block:
        result.append((block, header + "\n\n" + "\n".join(lines)))
    return result


class PrivateLedger:
    def __init__(self, repo, token):
        parts = repo.split("/")
        if len(parts) != 2 or not all(p and p.replace("-", "").replace("_", "").isalnum() for p in parts):
            raise DeliveryError("invalid_private_repository_name")
        if not token:
            raise DeliveryError("missing_ledger_token")
        self.url = "https://api.github.com/repos/" + repo
        self.token = token

    def api(self, path, method="GET", body=None):
        req = Request(self.url + path, data=json.dumps(body).encode() if body is not None else None,
                      method=method, headers={"Authorization": "Bearer " + self.token,
                                              "Accept": "application/vnd.github+json",
                                              "User-Agent": "taylorstock-ledger"})
        try:
            with urlopen(req, timeout=15) as res:
                return json.load(res)
        except HTTPError as e:
            status = e.code
            e.close()
            raise DeliveryError("ledger_not_found" if status == 404 else
                                "ledger_conflict" if status in (409, 422) else "ledger_http_error") from None
        except (URLError, TimeoutError, OSError, ValueError):
            raise DeliveryError("ledger_network_error") from None

    def load(self):
        meta = self.api("")
        if meta.get("private") is not True or meta.get("default_branch") != "main":
            raise DeliveryError("ledger_must_be_private_with_main")
        try:
            record = self.api("/contents/telegram-ledger.json?ref=main")
        except DeliveryError as e:
            if str(e) == "ledger_not_found":
                return {"version": 1, "events": {}}, None
            raise
        try:
            state = json.loads(base64.b64decode(record["content"].replace("\n", "")))
            if state["version"] != 1 or not isinstance(state["events"], dict):
                raise ValueError("schema")
            return state, record["sha"]
        except (ValueError, KeyError, TypeError):
            raise DeliveryError("invalid_private_ledger") from None

    def save(self, state, sha):
        body = {"message": "chore: update private Telegram notification ledger", "branch": "main",
                "content": base64.b64encode(json.dumps(state).encode()).decode()}
        if sha:
            body["sha"] = sha
        return self.api("/contents/telegram-ledger.json", "PUT", body)["content"]["sha"]


def send_message(token, chat_id, message):
    if not token or not chat_id:
        raise DeliveryError("telegram_credentials_missing")
    req = Request("https://api.telegram.org/bot" + token + "/sendMessage",
                  data=json.dumps({"chat_id": chat_id, "text": message,
                                   "link_preview_options": {"is_disabled": True}}).encode(),
                  headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(req, timeout=18) as res:
            response = json.load(res)
        if response.get("ok") is not True or not isinstance(response.get("result", {}).get("message_id"), int):
            raise DeliveryError("telegram_delivery_unknown")
        return response["result"]["message_id"]
    except HTTPError as e:
        status = e.code
        e.close()
        raise DeliveryError("telegram_rejected_" + str(status)) from None
    except (URLError, TimeoutError, OSError, ValueError):
        raise DeliveryError("telegram_delivery_unknown") from None


def deliver(payload, store=None, sender=None, dry_run=True, now=None):
    validate(payload, now)
    ledger, sha = ({"version": 1, "events": {}}, None) if dry_run else store.load()
    events = candidates(payload, ledger, now)
    batches = grouped_messages(payload, events)
    if dry_run:
        return {"mode": "dry-run", "events": len(events), "messages": len(batches)}
    for batch, message in batches:
        # A pending reservation prevents blind duplicate sends after runner crashes.
        for event in batch:
            ledger["events"][event["eventKey"]] = {"date": event["date"],
                                                    "level": event["level"], "status": "pending"}
        sha = store.save(ledger, sha)
        try:
            message_id = sender(message)
        except DeliveryError as e:
            status = "unknown" if str(e) == "telegram_delivery_unknown" else "failed"
            for event in batch:
                ledger["events"][event["eventKey"]]["status"] = status
            store.save(ledger, sha)
            raise
        for event in batch:
            ledger["events"][event["eventKey"]].update(status="sent", message_id=message_id)
        sha = store.save(ledger, sha)
    return {"mode": "sent", "events": len(events), "messages": len(batches)}
