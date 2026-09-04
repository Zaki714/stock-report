"""第一層：強勢股掃描 + 黑馬判定。

刻意不預設任何產業分類 —— 黑馬之所以是黑馬，就是因為它不在既有的分類裡。
只看「漲幅 + 量能異常」這種客觀訊號，讓題材歸納交給下一層的 LLM。
"""
from __future__ import annotations

from typing import Any


def prefilter_candidates(quotes: list[dict], cfg: dict) -> list[dict]:
    """在抓歷史股價（算量能倍數）之前，先用不需要歷史資料的條件粗篩。

    台股上市櫃合計近 2000 檔，若對全部個股逐檔打歷史股價 API 才篩選，
    等於一次發出數千個請求，實務上會很慢、也容易被資料源判定為爬蟲擋掉。
    這裡先用漲幅、成交金額（跟 scan_strong_stocks 一樣的門檻）篩掉大多數，
    只對剩下的少數候選股呼叫 attach_volume_ratio，結果與不做這層篩選完全一致
    ——因為漲幅／成交金額不合格的個股，本來就會在 scan_strong_stocks 被刷掉。
    """
    s = cfg["screener"]
    return [
        q for q in quotes
        if q.get("change_pct", 0) >= s["min_change_pct"]
        and q.get("turnover", 0) >= s["min_turnover"]
    ]


def scan_strong_stocks(quotes: list[dict], cfg: dict) -> list[dict]:
    """依漲幅、量能、成交金額篩出今日強勢股。"""
    s = cfg["screener"]
    picked = []

    for q in quotes:
        if q.get("change_pct", 0) < s["min_change_pct"]:
            continue
        if q.get("turnover", 0) < s["min_turnover"]:
            continue
        ratio = q.get("volume_ratio")
        if ratio is not None and ratio < s["min_volume_ratio"]:
            continue
        picked.append(q)

    picked.sort(key=lambda x: (x.get("volume_ratio") or 0) * x.get("change_pct", 0), reverse=True)
    return picked[: s["top_n"]]


def attach_volume_ratio(quotes: list[dict], history_fn) -> list[dict]:
    """補上量能倍數（當日量 / 20日均量）。

    history_fn 由呼叫端注入，方便測試時替換掉真實 API。
    """
    for q in quotes:
        if q.get("volume_ratio") is not None:
            continue
        hist = history_fn(q["code"], 25)
        vols = [h["volume"] for h in hist[-21:-1] if h.get("volume")]
        avg = sum(vols) / len(vols) if vols else 0
        q["volume_ratio"] = round(q["volume"] / avg, 2) if avg > 0 else None
    return quotes


def identify_dark_horses(
    orphans: list[dict], quotes_by_code: dict[str, dict], cfg: dict
) -> list[dict]:
    """把 LLM 標記為「孤立訊號」的個股，加上風險欄位。

    重點：黑馬不給「信心度」，只給「風險標記」——
    資訊不對稱的標的，用同一套信心度語言會誤導人。
    """
    dh_cfg = cfg["dark_horse"]
    results = []

    for orphan in orphans:
        code = orphan.get("code", "")
        quote = quotes_by_code.get(code, {})
        ratio = quote.get("volume_ratio") or 0

        risk_flags = []
        if ratio >= dh_cfg["volume_ratio"]:
            risk_flags.append(f"量能達 20 日均量 {ratio:.1f} 倍")
        risk_flags.append("無同族群呼應，題材脈絡不明")
        risk_flags.append("籌碼未經法人驗證")

        results.append({
            "code": code,
            "name": orphan.get("name") or quote.get("name", ""),
            "reason": orphan.get("reason", ""),
            "volume_ratio": ratio,
            "change_pct": quote.get("change_pct", 0),
            "close": quote.get("close", 0),
            "risk_flags": risk_flags,
            "risk_level": "高" if ratio >= dh_cfg["volume_ratio"] else "中",
            "advice": "建議列為觀察而非追蹤標的",
        })
    return results


def mark_watchlist(items: list[dict], watchlist: list[dict]) -> list[dict]:
    """標記自選股並置頂 —— 你最在意的永遠是手上那幾檔。"""
    codes = {w["code"] for w in watchlist}
    for item in items:
        item["is_watchlist"] = item.get("code") in codes
    items.sort(key=lambda x: not x.get("is_watchlist", False))
    return items


def watchlist_hits(
    themes: list[dict], dark_horses: list[dict], watchlist: list[dict]
) -> list[dict]:
    """今天有哪些自選股被掃到，放報告最上方。"""
    codes = {w["code"]: w["name"] for w in watchlist}
    hits: list[dict[str, Any]] = []

    for theme in themes:
        for stock in theme.get("stocks", []):
            if stock.get("code") in codes:
                hits.append({
                    "code": stock["code"],
                    "name": codes[stock["code"]],
                    "context": f"出現在題材「{theme['name']}」",
                    "confidence": theme.get("confidence", ""),
                })

    for dh in dark_horses:
        if dh.get("code") in codes:
            hits.append({
                "code": dh["code"],
                "name": codes[dh["code"]],
                "context": "被標記為異常訊號／疑似黑馬",
                "confidence": "",
            })

    return hits
