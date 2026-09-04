"""國際盤擷取（yfinance，免 API key、免申請）。

原本用 Stooq（純 CSV、無需註冊），但實測發現 Stooq 近期會對非瀏覽器的請求
跳反爬蟲驗證頁（JS 算圖驗證），不是回傳資料。改用 yfinance：
一次呼叫就能拿到一個月的完整歷史（免去像台股指數那樣要自己每天存快照才有
走勢線可看的問題），也還沒遇到擋爬蟲的狀況。
"""
from __future__ import annotations

from typing import Any

from ..config import DRY_RUN
from . import mock

# 對台股開盤最有解釋力的四個指數：費半權重最高，因為電子股佔台股市值大宗
INDICES = [
    ("^DJI", "道瓊"),
    ("^IXIC", "那斯達克"),
    ("^GSPC", "S&P 500"),
    ("^SOX", "費半 SOX"),
]

# 海外掛牌的台股 ADR，對台股開盤最直接
ADRS = [
    ("TSM", "台積電 ADR"),
    ("UMC", "聯電 ADR"),
    ("ASX", "日月光 ADR"),
]

MACRO = [
    ("DX-Y.NYB", "美元指數"),
    ("CL=F", "西德州原油"),
    ("GC=F", "黃金"),
]


def _history(symbol: str, period: str = "1mo"):
    """回傳 yfinance 的歷史資料（DataFrame），失敗回 None。獨立函式方便測試時替換。"""
    try:
        import yfinance as yf
        df = yf.Ticker(symbol).history(period=period)
        return df if not df.empty else None
    except Exception as exc:
        print(f"[intl] {symbol} 擷取失敗：{exc}")
        return None


def _card(symbol: str, name: str, period: str = "1mo") -> dict | None:
    """單一指數/ADR 卡片：名稱、收盤、漲跌、漲跌幅、歷史收盤序列（畫迷你走勢線用）。"""
    df = _history(symbol, period)
    if df is None or len(df) < 2:
        return None
    closes = [round(float(c), 2) for c in df["Close"].tolist()]
    close, prev = closes[-1], closes[-2]
    change = round(close - prev, 2)
    change_pct = round(change / prev * 100, 2) if prev else 0.0
    return {
        "symbol": symbol, "name": name,
        "close": close, "change": change, "change_pct": change_pct,
        "history": closes,
    }


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
        df = _history(symbol, "1mo")
        if df is None or len(df) < 2:
            continue
        close, prev = float(df["Close"].iloc[-1]), float(df["Close"].iloc[-2])
        pct = round((close - prev) / prev * 100, 2) if prev else 0.0

        vr = None
        vols = df["Volume"].tolist()
        if len(vols) >= 3:
            today_vol, base = vols[-1], vols[:-1]
            avg = sum(base) / len(base)
            vr = round(today_vol / avg, 2) if avg > 0 else None

        if vr and vr >= 1.15:
            flow = "資金流入" if pct >= 0 else "資金流出"
        elif vr and vr <= 0.85:
            flow = "量縮觀望"
        else:
            flow = "持平"
        out.append({"name": name, "symbol": symbol, "change_pct": pct,
                    "volume_ratio": vr, "flow": flow})
    return out


def fetch_index_history(days: int = 8) -> list[dict]:
    """長假期間國際盤逐日變化，給「假期彙整報告」用。

    回傳格式：[{name, rows: [{date, close, change_pct}, ...]}, ...]
    """
    if DRY_RUN:
        return mock.international_history(days)

    out = []
    for symbol, name in INDICES:
        df = _history(symbol, "3mo")
        if df is None:
            continue
        tail = df.tail(days)
        series = []
        prev = None
        for idx, row in tail.iterrows():
            close = float(row["Close"])
            change_pct = round((close - prev) / prev * 100, 2) if prev else 0.0
            series.append({"date": idx.strftime("%Y-%m-%d"), "close": round(close, 2),
                          "change_pct": change_pct})
            prev = close
        if series:
            out.append({"name": name, "rows": series})
    return out


def fetch_international() -> dict:
    """回傳指數／ADR 卡片與總經指標。任一項失敗就略過該項，不影響其他。"""
    if DRY_RUN:
        return mock.international_markets()

    indices = [c for c in (_card(s, n) for s, n in INDICES) if c]
    adrs = [c for c in (_card(s, n) for s, n in ADRS) if c]

    macro: list[dict[str, Any]] = []
    for symbol, name in MACRO:
        card = _card(symbol, name)
        if card:
            macro.append({"name": name,
                          "value": f"{card['close']:,.1f}（{card['change_pct']:+.2f}%）"})

    if not indices:
        print("[intl] 所有國際指數擷取失敗，改用快取／預設值")
        return mock.international_markets()

    return {"indices": indices, "adrs": adrs, "macro": macro}
