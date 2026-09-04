"""上櫃（TPEx）資料擷取：櫃買中心開放 API，免費免申請。

目前只用來抓櫃買指數。跟 twse.py 一樣：失敗一律回空值，不拋例外。
"""
from __future__ import annotations

from typing import Any

import requests

from ..config import DRY_RUN
from . import mock

TIMEOUT = 20
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; stock-report/1.0)"}
BASE = "https://www.tpex.org.tw/openapi/v1"


def _num(value: Any) -> float:
    if value is None:
        return 0.0
    text = str(value).replace(",", "").replace("+", "").strip()
    if text in ("", "--", "-", "N/A"):
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def fetch_otc_index() -> dict:
    """櫃買指數今日開高低收。

    /tpex_index 只回傳最近幾個交易日的滾動視窗（免費 API 沒有長期歷史），
    所以順便把這幾天的資料也一起回傳，讓呼叫端可以拿來補歷史快照。
    """
    if DRY_RUN:
        return mock.otc_index()

    try:
        resp = requests.get(f"{BASE}/tpex_index", headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        rows = resp.json()
    except Exception as exc:
        print(f"[tpex] 櫃買指數擷取失敗：{exc}")
        return {}

    if not isinstance(rows, list) or not rows:
        return {}

    recent = []
    for r in rows:
        close = _num(r.get("Close"))
        if close <= 0:
            continue
        recent.append({
            "date": r.get("Date", ""), "close": close,
            "change": _num(r.get("Change")),
        })
    if not recent:
        return {}

    last = recent[-1]
    change = last["change"]
    prev_close = last["close"] - change
    change_pct = round(change / prev_close * 100, 2) if prev_close > 0 else 0.0

    return {
        "close": last["close"], "change": change, "change_pct": change_pct,
        "recent": recent,   # 給呼叫端補歷史快照用
    }
