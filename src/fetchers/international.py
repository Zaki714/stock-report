"""國際盤擷取（Stooq，免 API key、免申請）。

選 Stooq 的理由：回傳 CSV、無需註冊、沒有免費額度限制。
若之後要更豐富的欄位，可換成 yfinance（pip install yfinance），介面照樣沿用下面的 dict 格式。
"""
from __future__ import annotations

import csv
import io

import requests

from ..config import DRY_RUN
from . import mock

TIMEOUT = 25
STOOQ = "https://stooq.com/q/d/l/"

# 對台股開盤最有解釋力的四個指數：費半權重最高，因為電子股佔台股市值大宗
INDICES = [
    ("^dji", "道瓊"),
    ("^ndq", "那斯達克"),
    ("^spx", "S&P 500"),
    ("^sox", "費半 SOX"),
]

MACRO = [
    ("dx.f", "美元指數"),
    ("cl.f", "西德州原油"),
    ("gc.f", "黃金"),
]


def _fetch_series(symbol: str) -> list[dict]:
    try:
        resp = requests.get(STOOQ, params={"s": symbol, "i": "d"}, timeout=TIMEOUT)
        resp.raise_for_status()
        rows = list(csv.DictReader(io.StringIO(resp.text)))
        return rows[-5:] if rows else []
    except Exception as exc:
        print(f"[intl] {symbol} 擷取失敗：{exc}")
        return []


def _last_change(symbol: str) -> tuple[float, float] | None:
    rows = _fetch_series(symbol)
    if len(rows) < 2:
        return None
    try:
        close = float(rows[-1]["Close"])
        prev = float(rows[-2]["Close"])
        return close, round((close - prev) / prev * 100, 2)
    except (KeyError, ValueError, ZeroDivisionError):
        return None


def _volume_ratio(rows: list[dict]) -> float | None:
    """當日量 / 前幾日均量，當作資金流向的近似值。"""
    try:
        vols = [float(r["Volume"]) for r in rows if r.get("Volume")]
        if len(vols) < 3:
            return None
        today_vol, base = vols[-1], vols[:-1]
        avg = sum(base) / len(base)
        return round(today_vol / avg, 2) if avg > 0 else None
    except (KeyError, ValueError):
        return None


def fetch_sector_etfs(etfs: list[dict]) -> list[dict]:
    """類股 ETF 的價格動能與量能倍數。

    免費資料源拿不到真實 fund flow，用「漲跌幅 + 量能倍數」當近似：
    量增價漲視為資金流入、量增價跌視為資金流出。這是近似值，報告會標明。
    """
    if DRY_RUN:
        return mock.sector_etf_flows()

    out = []
    for etf in etfs:
        symbol, name = etf.get("symbol", ""), etf.get("name", "")
        rows = _fetch_series(symbol)
        change = _last_change(symbol)
        if not change:
            continue
        vr = _volume_ratio(rows)
        pct = change[1]
        if vr and vr >= 1.15:
            flow = "資金流入" if pct >= 0 else "資金流出"
        elif vr and vr <= 0.85:
            flow = "量縮觀望"
        else:
            flow = "持平"
        out.append({
            "name": name, "symbol": symbol,
            "change_pct": pct, "volume_ratio": vr, "flow": flow,
        })
    return out


def fetch_index_history(days: int = 8) -> list[dict]:
    """長假期間國際盤逐日變化，給「假期彙整報告」用。

    回傳格式：[{name, rows: [{date, close, change_pct}, ...]}, ...]
    """
    if DRY_RUN:
        return mock.international_history(days)

    out = []
    for symbol, name in INDICES:
        rows = _fetch_series(symbol)
        if not rows:
            continue
        series = []
        prev = None
        for r in rows[-days:]:
            try:
                close = float(r["Close"])
            except (KeyError, ValueError):
                continue
            change_pct = round((close - prev) / prev * 100, 2) if prev else 0.0
            series.append({"date": r.get("Date", ""), "close": close, "change_pct": change_pct})
            prev = close
        if series:
            out.append({"name": name, "rows": series})
    return out


def fetch_international() -> dict:
    """回傳指數與總經指標。任一項失敗就略過該項，不影響其他。"""
    if DRY_RUN:
        return mock.international_markets()

    indices = []
    for symbol, name in INDICES:
        result = _last_change(symbol)
        if result:
            indices.append({"name": name, "close": result[0], "change_pct": result[1]})

    macro = []
    for symbol, name in MACRO:
        result = _last_change(symbol)
        if result:
            macro.append({"name": name, "value": f"{result[0]:,.1f}（{result[1]:+.2f}%）"})

    # 台積電 ADR 對台股開盤最直接，單獨處理
    adr = _last_change("tsm.us")
    if adr:
        macro.append({"name": "台積電 ADR", "value": f"{adr[0]:,.2f}（{adr[1]:+.2f}%）"})

    if not indices:
        print("[intl] 所有國際指數擷取失敗，改用快取／預設值")
        return mock.international_markets()

    return {"indices": indices, "macro": macro}
