"""國際財經頭條擷取（Google News RSS，免費、免 API key、免申請）。

用途：國際題材追蹤模組的第一手輸入。抓 Bloomberg/Reuters/WSJ 等外電頭條，
交給 LLM 統計高頻關鍵字，判斷當週市場最關注的敘事。

保證失敗回空 list、不拋例外——單一資料源掛掉不該讓整份早報開天窗。
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime
from urllib.parse import quote_plus

import requests

from ..config import DRY_RUN
from . import mock

TIMEOUT = 20
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; stock-report/1.0)"}
RSS = "https://news.google.com/rss/search"

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    return _TAG_RE.sub("", text or "").strip()


def _fetch_query(query: str, hl: str = "en-US", gl: str = "US", ceid: str = "US:en") -> list[dict]:
    """抓單一查詢字串的 RSS 結果。hl/gl/ceid 控制語系與地區（台股新聞用 zh-TW/TW/TW:zh-Hant）。"""
    url = f"{RSS}?q={quote_plus(query)}&hl={hl}&gl={gl}&ceid={ceid}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except Exception as exc:
        print(f"[news] 查詢「{query}」擷取失敗：{exc}")
        return []

    items = []
    for item in root.iter("item"):
        title = _strip_html(item.findtext("title", ""))
        if not title:
            continue
        source_el = item.find("source")
        source = (source_el.text if source_el is not None else "") or ""
        items.append({
            "title": title,
            "source": source,
            "published": item.findtext("pubDate", ""),
            "link": item.findtext("link", ""),
            "query": query,
        })
    return items


def _merge(queries: list[str], limit: int, **locale) -> list[dict]:
    seen: set[str] = set()
    merged: list[dict] = []
    for q in queries:
        for row in _fetch_query(q, **locale):
            key = row["title"].lower()
            if key in seen:
                continue
            seen.add(key)
            merged.append(row)

    def _sort_key(row: dict):
        try:
            return datetime.strptime(row["published"][:25].strip(), "%a, %d %b %Y %H:%M:%S")
        except (ValueError, TypeError):
            return datetime.min

    merged.sort(key=_sort_key, reverse=True)
    return merged[:limit]


def fetch_headlines(queries: list[str], limit: int = 40) -> list[dict]:
    """國際財經頭條（英文），逐條查詢再合併，用標題去重，回傳最新的 `limit` 則。"""
    if DRY_RUN:
        return mock.global_headlines()[:limit]
    return _merge(queries, limit, hl="en-US", gl="US", ceid="US:en")


def fetch_tw_headlines(queries: list[str], limit: int = 20) -> list[dict]:
    """台股中文新聞，用法跟 fetch_headlines 一樣，只是換成台灣地區、繁中查詢。"""
    if DRY_RUN:
        return mock.tw_headlines()[:limit]
    return _merge(queries, limit, hl="zh-TW", gl="TW", ceid="TW:zh-Hant")
