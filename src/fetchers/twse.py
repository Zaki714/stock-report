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


def _roc_to_iso(raw: str) -> str | None:
    """民國年日期（1150904 或 115/09/04）轉西元 ISO。TWSE 好幾個端點都用這個格式。"""
    raw = str(raw).strip().replace("/", "")
    if not raw.isdigit() or len(raw) != 7:
        return None
    try:
        return f"{int(raw[:3]) + 1911}-{raw[3:5]}-{raw[5:]}"
    except ValueError:
        return None


def fetch_index_summary() -> dict:
    """大盤收盤行情：加權指數、成交量、漲跌家數。

    回傳的 data_date 是這筆資料本身「實際是哪一個交易日」（來自 TWSE 回應裡的
    日期欄位），不是呼叫當下的今天。TWSE 不同端點更新時間點不一樣（加權指數
    收盤後很快就有，三大法人要晚一點才落地），用這個欄位讓呼叫端能自己判斷
    抓到的到底是不是「今天」的資料，避免不同端點各自最新、但其實不是同一個
    交易日的資料被混在同一份報告裡。
    """
    if DRY_RUN:
        return mock.index_summary()

    result: dict[str, Any] = {}

    rows = _get("/exchangeReport/MI_INDEX")
    if rows:
        for row in rows:
            name = row.get("指數") or row.get("Name") or ""
            if "發行量加權股價指數" in name and "報酬" not in name:
                # 注意：TWSE 的「漲跌點數」本身不帶正負號，方向另外放在「漲跌」欄位
                # （"+"／"-"）。之前沒處理這個，導致 taiex_change 永遠是正的，
                # 跟正確帶號的「漲跌百分比」對不起來（例如下跌時顯示紅色▲卻搭配負百分比）。
                direction = (row.get("漲跌") or row.get("Direction") or "").strip()
                sign = -1 if direction == "-" else 1
                result["taiex_close"] = _num(row.get("收盤指數") or row.get("ClosingIndex"))
                result["taiex_change"] = sign * _num(row.get("漲跌點數") or row.get("Change"))
                result["taiex_change_pct"] = _num(row.get("漲跌百分比") or row.get("ChangePercent"))
                result["data_date"] = _roc_to_iso(row.get("日期") or row.get("Date") or "")
                break

    # 漲跌家數不能用 MI_INDEX20（那是「成交量前 20 名個股」，只有 20 檔，
    # 不是全市場漲跌家數統計）。改由呼叫端用 fetch_daily_quotes() 的結果
    # 透過 compute_breadth() 算，避免多打一次不對的 API。

    return result or mock.index_summary()


def fetch_index_recent(days: int = 5) -> list[dict]:
    """加權指數最近幾個交易日的開高低收，補齊 index_snapshots 走勢線用。

    跟 tpex.fetch_otc_index() 的 recent 是同樣的用途：櫃買指數那個端點本來就會
    回傳最近幾天，加權指數這邊原本只抓「今天」單一筆，走勢線要等系統跑很多天
    才會長出來；改抓 MI_5MINS_HIST 一次拿到最近幾天，跟櫃買指數一樣馬上就有線。
    """
    if DRY_RUN:
        return mock.taiex_recent(days)

    rows = _get("/indicesReport/MI_5MINS_HIST")
    if not rows:
        return []

    out = []
    prev_close = None
    for row in rows[-days:]:
        iso = _roc_to_iso(row.get("Date") or row.get("日期") or "")
        close = _num(row.get("ClosingIndex") or row.get("收盤指數"))
        if not iso or close <= 0:
            continue
        change = round(close - prev_close, 2) if prev_close else 0.0
        change_pct = round(change / prev_close * 100, 2) if prev_close else 0.0
        out.append({"date": iso, "close": close, "change": change, "change_pct": change_pct})
        prev_close = close
    return out


def compute_breadth(quotes: list[dict]) -> dict:
    """從全市場個股行情算漲跌家數（涨/跌，平盤不計入任一邊）。"""
    advancers = sum(1 for q in quotes if q.get("change", 0) > 0)
    decliners = sum(1 for q in quotes if q.get("change", 0) < 0)
    return {"advancers": advancers, "decliners": decliners}


def fetch_institutional_net() -> dict:
    """三大法人買賣超（單位：億元）。18:00 才抓的主因就是等這份資料落地。

    注意：這個資料集在新版 openapi.twse.com.tw 已經下架（/fund/BFI82U 回 404），
    改走舊版 www.twse.com.tw 的端點，回傳格式跟 fetch_stock_history 一樣是
    {"stat": "OK", "fields": [...], "data": [[...], ...]}，用 fields 對應欄位名。
    """
    if DRY_RUN:
        return mock.institutional_net()

    try:
        resp = requests.get(
            "https://www.twse.com.tw/fund/BFI82U",
            params={"response": "json"}, headers=HEADERS, timeout=TIMEOUT,
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:
        print(f"[twse] 三大法人買賣超擷取失敗：{exc}")
        return {}

    if payload.get("stat") != "OK":
        return {}

    fields = payload.get("fields", [])
    out = {"foreign_net": 0.0, "trust_net": 0.0, "dealer_net": 0.0}
    for row in payload.get("data", []):
        r = dict(zip(fields, row))
        name = r.get("單位名稱", "")
        net = _num(r.get("買賣差額")) / 1e8   # 元 → 億
        # 注意：用 startswith 而不是「in」——實際類別名稱「外資及陸資(不含外資自營商)」
        # 因為括號註記剛好包含「自營」兩個字，若用子字串比對「"自營" not in name」
        # 會被這段括號說明誤判，把整筆外資買賣超歸類到自營商。
        # 自營商拆成「自行買賣」「避險」「外資自營商」三列，全部歸進 dealer_net；
        # 「外資及陸資(不含外資自營商)」才算 foreign_net，避免跟自營商重複計算。
        if name.startswith("自營商") or name.startswith("外資自營商"):
            out["dealer_net"] += net
        elif name.startswith("外資"):
            out["foreign_net"] += net
        elif "投信" in name:
            out["trust_net"] += net
        # 其餘（例如「合計」列）不歸類，避免重複計算
    out["total_net"] = sum(out.values())
    return out


def fetch_institutional_ranking() -> list[dict]:
    """個股（含 ETF）三大法人買賣超排名（上市，單位：股）。

    來源是舊版 www.twse.com.tw/fund/T86，格式跟 fetch_stock_history 一樣是
    stat/fields/data 陣列。回傳依「三大法人買賣超股數」由大到小排序的清單，
    呼叫端自行取排名前後幾名（買超前 N、賣超前 N）。
    """
    if DRY_RUN:
        return mock.institutional_ranking()

    try:
        resp = requests.get(
            "https://www.twse.com.tw/fund/T86",
            params={"response": "json", "date": date.today().strftime("%Y%m%d"),
                    "selectType": "ALLBUT0999"},
            headers=HEADERS, timeout=TIMEOUT,
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:
        print(f"[twse] 個股三大法人排名擷取失敗：{exc}")
        return []

    if payload.get("stat") != "OK":
        return []

    fields = payload.get("fields", [])
    out = []
    for row in payload.get("data", []):
        r = dict(zip(fields, row))
        code = (r.get("證券代號") or "").strip()
        name = (r.get("證券名稱") or "").strip()
        if not code:
            continue
        out.append({
            "code": code, "name": name,
            "is_etf": code.startswith("00"),   # 給模板選擇性標示用，不做過濾
            "foreign_net": _num(r.get("外陸資買賣超股數(不含外資自營商)")),
            "trust_net": _num(r.get("投信買賣超股數")),
            "dealer_net": _num(r.get("自營商買賣超股數")),
            "total_net": _num(r.get("三大法人買賣超股數")),
        })

    out.sort(key=lambda x: x["total_net"], reverse=True)
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
