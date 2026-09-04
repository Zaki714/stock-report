"""台股資料擷取（TWSE 開放 API，免費免申請）。

每個函式都保證「失敗回傳空值而不拋例外」——單一資料源掛掉不該讓整份報告開天窗。
"""
from __future__ import annotations

from datetime import date
from typing import Any

import requests

from ..config import DRY_RUN
from . import mock

BASE = "https://openapi.twse.com.tw/v1"
TIMEOUT = 25
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; stock-report/1.0)"}


def _get(path: str) -> list[dict] | None:
    try:
        resp = requests.get(f"{BASE}{path}", headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else None
    except Exception as exc:
        print(f"[twse] {path} 擷取失敗：{exc}")
        return None


def _num(value: Any) -> float:
    """TWSE 回傳的數字都是帶逗號的字串，還可能是 '--'。"""
    if value is None:
        return 0.0
    text = str(value).replace(",", "").replace("+", "").strip()
    if text in ("", "--", "-", "N/A"):
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def fetch_index_summary() -> dict:
    """大盤收盤行情：加權指數、成交量、漲跌家數。"""
    if DRY_RUN:
        return mock.index_summary()

    result: dict[str, Any] = {}

    rows = _get("/exchangeReport/MI_INDEX")
    if rows:
        for row in rows:
            name = row.get("指數") or row.get("Name") or ""
            if "發行量加權股價指數" in name and "報酬" not in name:
                result["taiex_close"] = _num(row.get("收盤指數") or row.get("ClosingIndex"))
                result["taiex_change"] = _num(row.get("漲跌點數") or row.get("Change"))
                result["taiex_change_pct"] = _num(row.get("漲跌百分比") or row.get("ChangePercent"))
                break

    breadth = _get("/exchangeReport/MI_INDEX20")
    if breadth:
        result["advancers"] = sum(1 for r in breadth if str(r.get("漲跌", "")).startswith("+"))
        result["decliners"] = sum(1 for r in breadth if str(r.get("漲跌", "")).startswith("-"))

    return result or mock.index_summary()


def fetch_institutional_net() -> dict:
    """三大法人買賣超（單位：億元）。18:00 才抓的主因就是等這份資料落地。"""
    if DRY_RUN:
        return mock.institutional_net()

    rows = _get("/fund/BFI82U")
    if not rows:
        return {}

    out = {"foreign_net": 0.0, "trust_net": 0.0, "dealer_net": 0.0}
    for row in rows:
        name = row.get("單位名稱") or row.get("Name") or ""
        net = _num(row.get("買賣差額") or row.get("Difference")) / 1e8   # 元 → 億
        if "外資" in name and "自營" not in name:
            out["foreign_net"] += net
        elif "投信" in name:
            out["trust_net"] += net
        elif "自營" in name:
            out["dealer_net"] += net
    out["total_net"] = sum(out.values())
    return out


def fetch_daily_quotes() -> list[dict]:
    """全上市個股當日行情，強勢股掃描的原料。"""
    if DRY_RUN:
        return mock.daily_quotes()

    rows = _get("/exchangeReport/STOCK_DAY_ALL")
    if not rows:
        return []

    quotes = []
    for row in rows:
        close = _num(row.get("ClosingPrice"))
        change = _num(row.get("Change"))
        if close <= 0:
            continue
        prev = close - change
        quotes.append({
            "code": row.get("Code", ""),
            "name": row.get("Name", ""),
            "close": close,
            "change": change,
            "change_pct": round(change / prev * 100, 2) if prev > 0 else 0.0,
            "volume": _num(row.get("TradeVolume")),
            "turnover": _num(row.get("TradeValue")),
        })
    return quotes


def fetch_stock_history(code: str, days: int = 120) -> list[dict]:
    """個股日 K，技術分析用。TWSE 是按月查，抓最近幾個月再截斷。"""
    if DRY_RUN:
        return mock.stock_history(code, days)

    today = date.today()
    out: list[dict] = []
    months_needed = days // 20 + 2

    for offset in range(months_needed):
        year, month = today.year, today.month - offset
        while month <= 0:
            month += 12
            year -= 1
        try:
            resp = requests.get(
                "https://www.twse.com.tw/exchangeReport/STOCK_DAY",
                params={"response": "json", "date": f"{year}{month:02d}01", "stockNo": code},
                headers=HEADERS, timeout=TIMEOUT,
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:
            print(f"[twse] {code} 歷史股價擷取失敗：{exc}")
            continue

        if payload.get("stat") != "OK":
            continue
        for row in payload.get("data", []):
            try:
                roc_date = row[0].split("/")
                iso = f"{int(roc_date[0]) + 1911}-{roc_date[1]}-{roc_date[2]}"
                out.append({
                    "date": iso,
                    "open": _num(row[3]), "high": _num(row[4]),
                    "low": _num(row[5]), "close": _num(row[6]),
                    "volume": _num(row[1]),
                })
            except (IndexError, ValueError):
                continue

    out.sort(key=lambda r: r["date"])
    return out[-days:]
