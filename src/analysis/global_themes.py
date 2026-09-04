"""國際題材追蹤模組。

流程與台股題材相同，只是輸入換成外電頭條 + 類股 ETF 資金流向：

    抓頭條（Google News RSS）+ 類股 ETF 動能
        ↓
    LLM 歸納當週當紅題材、評估信心度
        ↓
    寫進同一個題材知識庫（scope='intl'），與台股題材並列
        ↓
    回傳裝飾後的檢視物件給 render 用

設計原則沿用專案慣例：任何一步失敗都回空結果，不拋例外中斷早報。
"""
from __future__ import annotations

from .. import db, llm, render
from ..fetchers import international, news


def _safe(fn, default, label: str):
    try:
        return fn()
    except Exception as exc:
        print(f"[global_themes] {label} 失敗：{exc}")
        return default


def build_global_themes(today: str, cfg: dict) -> list[dict]:
    """產出並落庫國際題材，回傳給模板用的檢視 list。"""
    gt_cfg = cfg.get("global_themes", {})
    if not gt_cfg.get("enabled", False):
        return []

    headlines = _safe(
        lambda: news.fetch_headlines(gt_cfg.get("news_queries", []),
                                     gt_cfg.get("max_headlines", 40)),
        [], "頭條擷取")
    etf_flows = _safe(
        lambda: international.fetch_sector_etfs(gt_cfg.get("sector_etfs", [])),
        [], "ETF 資金流向")

    if not headlines and not etf_flows:
        print("[global_themes] 無任何輸入資料，略過國際題材")
        return []

    digest = _safe(lambda: llm.global_theme_digest(headlines, etf_flows),
                   {"themes": []}, "LLM 歸納")

    views: list[dict] = []
    for t in digest.get("themes", []):
        name = t.get("name")
        if not name:
            continue

        stocks = t.get("stocks", [])
        note_bits = [t.get("reasoning", "")]
        if t.get("etf_signal"):
            note_bits.append(f"ETF：{t['etf_signal']}")
        if t.get("institution_signal"):
            note_bits.append(f"機構：{t['institution_signal']}")

        db.upsert_theme(
            name=name,
            summary=t.get("summary", ""),
            confidence=t.get("confidence", "mid"),
            verdict=t.get("verdict", "watch"),
            related_stocks=stocks,
            today=today,
            scope="intl",
            note="　".join(b for b in note_bits if b),
        )
        stored = db.get_theme(name) or {}
        view = render.decorate_theme({**stored, **t})
        view["stocks"] = stocks
        view["keywords"] = t.get("keywords", [])
        view["etf_signal"] = t.get("etf_signal", "")
        view["institution_signal"] = t.get("institution_signal", "")
        view["tracked_days"] = stored.get("update_count", 1)
        views.append(view)

    print(f"[global_themes] 國際題材 {len(views)} 個")
    return views
