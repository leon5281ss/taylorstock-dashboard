import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from .sources import SourceError

FEEDS = {
    "財政部": "https://www.mof.gov.tw/Rss/384fb3077bb349ea973e7fc6f13b6974",
    "國安基金官方公告": "https://www.mof.gov.tw/multiplehtml/383",
    "金管會": "https://www.fsc.gov.tw/ch/home.jsp?id=96&parentpath=0,2",
}
KEYWORDS = ("國安基金", "金融安定基金", "護盤", "穩定股市", "穩定市場", "八大官股", "公股行庫", "官股銀行", "關稅", "證交稅", "信用交易", "融資融券", "融券", "借券", "放空", "重大政策")


class AnnouncementParser(HTMLParser):
    def __init__(self, base):
        super().__init__()
        self.base = base
        self.links = []
        self.active = None
        self.text = []
        self.row_text = []
        self.row_start = 0
        self.row_tag = None
        self.article_count = 0

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag in ("tr", "li") and self.row_tag is None:
            self.row_tag = tag
            self.row_text = []
            self.row_start = len(self.links)
        if tag == "a":
            self.active = urljoin(self.base, attributes.get("href", ""))
            self.text = []

    def handle_data(self, data):
        if self.row_tag:
            self.row_text.append(data.strip())
        if self.active:
            self.text.append(data.strip())

    def handle_endtag(self, tag):
        if tag == "a" and self.active:
            title = " ".join(part for part in self.text if part)
            article = "/singlehtml/" in self.active or "dataserno=" in self.active
            if article and title and urlparse(self.active).hostname == urlparse(self.base).hostname:
                self.article_count += 1
            if article and title and urlparse(self.active).hostname == urlparse(self.base).hostname and any(word in title for word in KEYWORDS):
                match = re.search(r"(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})", title)
                published = None
                if match:
                    try:
                        published = datetime(*map(int, match.groups()), tzinfo=timezone.utc).date().isoformat()
                    except ValueError:
                        pass
                self.links.append({"title": title, "url": self.active, "publishedDate": published})
            self.active = None
        if tag == self.row_tag:
            match = re.search(r"(?<!\d)(20\d{2}|1\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})", " ".join(self.row_text))
            if match:
                year, month, day = map(int, match.groups())
                try:
                    published = datetime(year + 1911 if year < 1911 else year, month, day).date().isoformat()
                    for item in self.links[self.row_start:]:
                        item["publishedDate"] = published
                except ValueError:
                    pass
            self.row_tag = None


def collect_news(client, now):
    reports = []
    for name, url in FEEDS.items():
        items = []
        try:
            raw = client.get(url, as_text=True)
            if "/Rss/" in url:
                root = ET.fromstring(raw)
                entries = root.findall(".//item")
                if not entries:
                    raise SourceError("schema_changed")
                for entry in entries:
                    title, link = entry.findtext("title", ""), entry.findtext("link", "")
                    if not any(word in title for word in KEYWORDS) or urlparse(link).hostname != urlparse(url).hostname:
                        continue
                    published = None
                    try:
                        published = parsedate_to_datetime(entry.findtext("pubDate", "")).date().isoformat()
                    except (TypeError, ValueError, OverflowError):
                        pass
                    items.append({"title": title, "url": link, "publishedDate": published})
            else:
                parser = AnnouncementParser(url)
                parser.feed(raw)
                items = parser.links
                if parser.article_count == 0:
                    raise SourceError("no_parseable_announcements")
            unique = {item["url"]: item for item in items}
            for item in unique.values():
                item["dateStatus"] = "dated" if item["publishedDate"] else "publication_date_unknown"
                item["isRecent"] = bool(item["publishedDate"] and 0 <= (now.date() - datetime.fromisoformat(item["publishedDate"]).date()).days <= 7)
                item["interpretation"] = "官方標題關鍵字命中，需人工閱讀全文；不代表已進場護盤"
            reports.append({"source": name, "url": url, "status": "ok", "checkedAt": now.isoformat(), "items": list(unique.values())[:30]})
        except (SourceError, ET.ParseError) as exc:
            reports.append({"source": name, "url": url, "status": str(exc) if isinstance(exc, SourceError) else "invalid_feed", "checkedAt": now.isoformat(), "items": []})
    return reports

