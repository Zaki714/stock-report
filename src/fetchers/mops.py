"""法說會行事曆（公開資訊觀測站 / TWSE 開放 API）。

法說會是題材知識庫「基本面驗證」最重要的第一手來源：
公司在法說會上對訂單能見度的說法，可以直接拿去驗證題材是真是假。
"""
from __future__ import annotations

from datetime import date

import requests

from ..config import DRY_RUN
from . import mock

TIMEOUT = 25
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; stock-report/1.0)"}
CONF_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap38_L"


def _normalize_roc(raw: str) -> str | None:
    raw = str(raw).strip().replace("/", "").replace("-", "")
    if not raw.isdigit():
        return None
    try:
        if len(raw) == 7:
            return f"{int(raw[:3]) + 1911}-{raw[3:5]}-{raw[5:]}"
        if len(raw) == 8:
            return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
    except ValueError:
        return None
    return None


def fetch_earnings_calls(target: date | None = None) -> list[dict]:
    """回傳指定日期召開法說會的公司清單。"""
    if DRY_RUN:
        return mock.earnings_calls()

    target = target or date.today()
    target_iso = target.isoformat()

    try:
        resp = requests.get(CONF_URL, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        rows = resp.json()
    except Exception as exc:
        print(f"[mops] 法說會行事曆擷取失敗：{exc}")
        return []

    calls = []
    for row in rows if isinstance(rows, list) else []:
        raw_date = (row.get("出席法人說明會日期") or row.get("SpokenDate")
                    or row.get("Date") or "")
        if _normalize_roc(raw_date) != target_iso:
            continue
        calls.append({
            "code": row.get("公司代號") or row.get("Code", ""),
            "name": row.get("公司名稱") or row.get("Name", ""),
            "time": row.get("時間") or row.get("Time", ""),
            "note": (row.get("法人說明會擇要訊息")
                     or row.get("Description") or "")[:120],
        })
    return calls


def fetch_upcoming_calls(days_ahead: int = 7) -> list[dict]:
    """未來 N 天的法說會，給假日功課的「下週行事曆預告」用。"""
    from datetime import timedelta
    if DRY_RUN:
        return mock.earnings_calls()

    today = date.today()
    upcoming = []
    for offset in range(1, days_ahead + 1):
        day = today + timedelta(days=offset)
        for call in fetch_earnings_calls(day):
            call["date"] = day.isoformat()
            upcoming.append(call)
    return upcoming
