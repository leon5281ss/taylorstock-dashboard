import hashlib
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .sources import government_bank


def article_key(url):
    parts = urlsplit(url)
    query = [(key, value) for key, value in parse_qsl(parts.query) if not key.lower().startswith("utm_")]
    canonical = urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, urlencode(sorted(query)), ""))
    return hashlib.sha256(canonical.encode()).hexdigest()


def market_monitor(feeds):
    unique = {}
    for feed in feeds:
        for item in feed["items"]:
            key = article_key(item["url"])
            if key in unique:
                if feed["source"] not in unique[key]["sources"]:
                    unique[key]["sources"].append(feed["source"])
                continue
            title = item["title"]
            topics = []
            if "國安基金" in title or "金融安定基金" in title:
                topics.append("國安基金")
            if any(word in title for word in ("護盤", "穩定股市", "穩定市場")):
                topics.append("政府護盤")
            if any(word in title for word in ("八大官股", "公股行庫", "官股銀行")):
                topics.append("八大官股")
            unique[key] = {**item, "eventId": key, "sources": [feed["source"]], "topics": topics or ["其他市場政策"]}
    return {
        "items": list(unique.values()),
        "sources": [{key: feed[key] for key in ("source", "url", "status", "checkedAt")} for feed in feeds],
        "governmentBank": government_bank(None, "", "", ""),
        "notice": "官方公告候選不代表已進場護盤；不加入個股警報或人工確認計數。",
    }


def related_industry_news(stock, items):
    result = []
    seen = set()
    for item in items:
        if not item.get("isRecent") or not item.get("publishedDate") or not item.get("url") or not item.get("source"):
            continue
        if stock["code"] not in item.get("relatedSymbols", []):
            continue
        if item.get("scope") != "industry" or not item.get("relevanceEvidence"):
            continue
        key = article_key(item["url"])
        if key in seen:
            continue
        seen.add(key)
        result.append({"rule": "industry_news", "message": item["title"], "date": item["publishedDate"], "source": item["source"], "url": item["url"], "relevanceEvidence": item["relevanceEvidence"]})
    return result
