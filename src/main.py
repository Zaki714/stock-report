"""主程式入口。

用法：
    python -m src.main morning     # 07:00 國際盤（含國際題材追蹤；當週第一個交易日附上週報）
    python -m src.main evening     # 18:00 台股盤後
    python -m src.main monthly     # 每月 12 日 月報完整版（事後驗證 + HTML 頁面）
    python -m src.main holiday     # 假日功課
    python -m src.main wrapup      # 長假彙整（休市期間國際盤逐日回顧）
    python -m src.main site        # 只重建索引頁
    python -m src.main auto        # 自動判斷今天該跑什麼（排程用這個）

本地測試：DRY_RUN=1 python -m src.main evening
"""
from __future__ import annotations

import sys
import traceback
from datetime import date, timedelta

from . import db, llm, render
from .analysis import charts, global_themes, recap, review, screener, technical
from .config import DRY_RUN, load_config, today_str, now_tpe
from .fetchers import international, mops, news, tpex, twse
from .market_calendar import (classify_day, is_first_trading_day_of_week,
                              is_last_day_before_reopen, next_trading_day,
                              refresh_holidays)
from .notify import send_notification


def _safe(fn, default, label: str):
    """任一資料源失敗都不該讓整份報告開天窗。"""
    try:
        return fn()
    except Exception as exc:
        print(f"[warn] {label} 失敗：{exc}")
        traceback.print_exc()
        return default


def _with_spark(cards: list[dict]) -> list[dict]:
    """幫指數卡片補上迷你走勢線（history 收盤序列 → SVG）。"""
    for c in cards:
        hist = c.get("history")
        if hist and len(hist) >= 2:
            c["spark"] = render.mark_safe(charts.sparkline(hist))
    return cards


# ── 早報：國際盤 ───────────────────────────────────────
def run_morning() -> None:
    cfg = load_config()
    today = today_str()
    print(f"[morning] 產出國際盤報告 {today}")

    intl = _safe(international.fetch_international, {}, "國際盤")
    if intl.get("indices"):
        intl["indices"] = _with_spark(intl["indices"])
    if intl.get("adrs"):
        intl["adrs"] = _with_spark(intl["adrs"])

    calls = _safe(lambda: mops.fetch_earnings_calls(), [], "法說會行事曆")

    commentary = _safe(
        lambda: llm.market_commentary({"international": intl, "type": "morning"}),
        "", "早報評論")

    # 國際題材追蹤：抓外電頭條 + 類股 ETF 資金流向，歸納當週當紅題材
    gthemes = _safe(lambda: global_themes.build_global_themes(today, cfg), [], "國際題材")

    # 台股早報重點新聞：同一套 Google News RSS，換成中文查詢
    gt_cfg = cfg.get("global_themes", {})
    tw_news = _safe(
        lambda: news.fetch_tw_headlines(gt_cfg.get("tw_news_queries", []), 12),
        [], "台股新聞")

    ctx = {
        "report_kind": "早報 · 國際盤摘要",
        "date_label": render.date_label(today),
        "international": intl,
        "intl_commentary": commentary,
        "earnings_calls": calls,
        "global_themes": gthemes,
        "tw_news": tw_news,
    }

    # 週報：併入當週第一個交易日的早報，不獨立開排程
    if cfg.get("weekly", {}).get("enabled") and is_first_trading_day_of_week(date.fromisoformat(today)):
        wk = _safe(lambda: recap.weekly_recap(today), {}, "週報彙整")
        if wk:
            ctx["weekly_recap"] = wk
            ctx["weekly_chart"] = render.mark_safe(charts.line_chart(
                [d["date"][5:] for d in wk["daily"]],
                [d["taiex_close"] for d in wk["daily"]],
            ))
            ctx["report_kind"] = "早報 · 國際盤摘要 + 上週回顧"

    path = render.render_daily(ctx, f"{today}-morning")
    render.render_site()
    print(f"[morning] 完成：{path}")
    send_notification(f"早報已產出：{render.date_label(today)}", commentary)


# ── 盤後：台股完整分析 ─────────────────────────────────
def run_evening() -> None:
    cfg = load_config()
    today = today_str()
    print(f"[evening] 產出台股盤後報告 {today}")

    market = _safe(twse.fetch_index_summary, {}, "大盤行情")
    inst = _safe(twse.fetch_institutional_net, {}, "三大法人")
    quotes = _safe(twse.fetch_daily_quotes, [], "個股行情")
    calls = _safe(lambda: mops.fetch_earnings_calls(), [], "法說會")
    otc = _safe(tpex.fetch_otc_index, {}, "櫃買指數")

    # 漲跌家數不能用 MI_INDEX20（那份資料只有「成交量前 20 名」），改從
    # 已經抓到的全市場個股行情直接算，DRY_RUN 也一併算過，跟假資料的
    # advancers/decliners 保持一致（避免兩邊各算各的）。
    if quotes:
        market.update(twse.compute_breadth(quotes))

    if market:
        db.save_market_snapshot(today, {**market, **inst})

    # 加權指數／櫃買指數卡片：每天存一筆快照，走勢線隨著系統運作天數增長
    # （免費 API 只給最近幾天的滾動視窗，沒有長期歷史可以一次拉）
    index_cards = []
    if market.get("taiex_close"):
        db.save_index_snapshot(today, "taiex", "加權指數", market["taiex_close"],
                               market.get("taiex_change", 0), market.get("taiex_change_pct", 0))
    taiex_hist = [s["close"] for s in db.index_series("taiex", 30)]
    if taiex_hist:
        index_cards.append(_with_spark([{
            "name": "加權指數", "close": market.get("taiex_close", taiex_hist[-1]),
            "change": market.get("taiex_change", 0),
            "change_pct": market.get("taiex_change_pct", 0),
            "history": taiex_hist,
        }])[0])

    if otc.get("close"):
        # tpex_index 一次會回傳最近幾天的資料，順便補齊還沒存過的快照。
        # DRY_RUN 假資料的日期是相對「今天」現算的，跟模擬測試常用的
        # 覆寫 today_str() 對不上，這種情境下只存當天這筆就好，不做回填。
        if not DRY_RUN:
            for r in otc.get("recent", []):
                iso = (f"{r['date'][:4]}-{r['date'][4:6]}-{r['date'][6:]}"
                       if len(r["date"]) == 8 else r["date"])
                db.save_index_snapshot(iso, "otc", "櫃買指數", r["close"], r.get("change", 0), 0)
        db.save_index_snapshot(today, "otc", "櫃買指數", otc["close"], otc["change"], otc["change_pct"])
    otc_hist = [s["close"] for s in db.index_series("otc", 30)]
    if otc_hist:
        index_cards.append(_with_spark([{
            "name": "櫃買指數", "close": otc.get("close", otc_hist[-1]),
            "change": otc.get("change", 0), "change_pct": otc.get("change_pct", 0),
            "history": otc_hist,
        }])[0])

    # 個股三大法人買賣超排名：外資／投信／自營商分開列，不合併成單一排名
    # （合計數字會讓「外資大買、自營小賣」跟「三方都小買」看起來差不多，分開才看得出誰在動）
    inst_ranking = {}
    if cfg.get("institutional_ranking", {}).get("enabled"):
        top_n = cfg["institutional_ranking"].get("top_n", 5)
        ranking = _safe(twse.fetch_institutional_ranking, [], "個股三大法人排名")
        if ranking:
            for key, label in (("foreign_net", "foreign"), ("trust_net", "trust"), ("dealer_net", "dealer")):
                by_metric = sorted(ranking, key=lambda x: x[key], reverse=True)
                inst_ranking[f"{label}_buy"] = [{**r, "net": r[key]} for r in by_metric[:top_n]]
                inst_ranking[f"{label}_sell"] = [{**r, "net": r[key]} for r in reversed(by_metric[-top_n:])]

    # 第一層：強勢股掃描
    # 先用免歷史資料的條件粗篩（漲幅、成交金額），只對少數候選股抓歷史股價算量能倍數，
    # 避免對全部近 2000 檔上市櫃股票逐檔打 API（會很慢，也容易被資料源擋）。
    # candidates 跟 quotes 裡的是同一批 dict 物件，這裡對 candidates 補上的 volume_ratio
    # 之後透過 quotes_by_code 查得到（見下方黑馬判定）。
    candidates = screener.prefilter_candidates(quotes, cfg)
    candidates = screener.attach_volume_ratio(candidates, twse.fetch_stock_history)
    strong = screener.scan_strong_stocks(candidates, cfg)
    print(f"[evening] 強勢股 {len(strong)} 檔（粗篩候選 {len(candidates)} / 全市場 {len(quotes)} 檔）")

    # 第二層：題材聚類（含孤立訊號分流）
    call_context = "\n".join(f"{c['code']} {c['name']} 法說會：{c['note']}" for c in calls)
    clustered = _safe(lambda: llm.cluster_themes(strong, call_context),
                      {"themes": [], "orphans": []}, "題材聚類")

    themes_raw = clustered.get("themes", [])
    orphans = clustered.get("orphans", [])

    # 第三層：寫進題材知識庫（有就更新、沒有才新建）
    themes_view = []
    for t in themes_raw:
        theme_id = db.upsert_theme(
            name=t["name"], summary=t.get("summary", ""),
            confidence=t.get("confidence", "mid"), verdict=t.get("verdict", "unknown"),
            related_stocks=t.get("stocks", []), today=today,
            note=t.get("reasoning", ""),
        )
        stored = db.get_theme(t["name"]) or {}
        view = render.decorate_theme({**stored, **t})
        view["stocks"] = t.get("stocks", [])
        view["tracked_days"] = stored.get("update_count", 1)
        if stored.get("id"):
            series = db.theme_confidence_series(stored["id"])
            if len(series) >= 2:
                view["conf_chart"] = render.mark_safe(
                    charts.sparkline([p["level"] for p in series]))
        themes_view.append(view)

        # 判斷快照：現在存下來，14/30 天後才能回頭驗證
        for stock in t.get("stocks", []):
            q = next((x for x in quotes if x["code"] == stock.get("code")), None)
            if q:
                db.save_judgment(today, stock["code"], stock.get("name", ""),
                                 t["name"], t.get("confidence", "mid"),
                                 "theme_pick", q["close"], market.get("taiex_close", 0))

    # 黑馬：不套題材，走獨立風險標記
    quotes_by_code = {q["code"]: q for q in quotes}
    dark_horses = screener.identify_dark_horses(orphans, quotes_by_code, cfg)
    for dh in dark_horses:
        db.save_judgment(today, dh["code"], dh["name"], "", "",
                         "dark_horse", dh.get("close", 0), market.get("taiex_close", 0))

    # 技術分析：只對入選個股跑，省算力。
    # 候選股優先抓「持續被追蹤的活躍題材」龍頭股（例如散熱題材連燒好幾天，
    # 就抓奇鋐、雙鴻這種代表股），而不是只看今天當下這次聚類剛好分到誰；
    # 今天新聚類出來的題材股、黑馬則補在後面，維持新鮮訊號也看得到。
    active_themes = _safe(lambda: db.list_themes("active"), [], "活躍題材清單")
    persistent_leaders = {}
    for t in active_themes:
        if t.get("update_count", 1) < 2:   # 只算追蹤過一次以上、有持續性的題材
            continue
        for s in render.decorate_theme(t).get("stocks", [])[:2]:   # 每個題材取前 2 檔當代表
            if s.get("code"):
                persistent_leaders[s["code"]] = s.get("name", "")

    candidates = dict(persistent_leaders)
    candidates.update({s["code"]: s["name"] for t in themes_raw for s in t.get("stocks", [])})
    candidates.update({dh["code"]: dh["name"] for dh in dark_horses})

    # 題材聚類跟黑馬當天可能就是很少（LLM 找到的題材、孤立訊號本來就會有天數差異），
    # 名單太短就沒東西可看。用今天的強勢股掃描結果（已依量能*漲幅排序）補到至少
    # MIN_TECHNICALS 檔，這些原本就是當天客觀上最強勢的個股，不是隨便湊數。
    MIN_TECHNICALS = 8
    if len(candidates) < MIN_TECHNICALS:
        for s in strong:
            if len(candidates) >= MIN_TECHNICALS:
                break
            candidates.setdefault(s["code"], s.get("name", ""))

    watch_codes = {w["code"] for w in cfg["watchlist"]}

    technicals = []
    for code, name in list(candidates.items())[:16]:
        hist = _safe(lambda c=code: twse.fetch_stock_history(c, cfg["technical"]["lookback_days"]),
                     [], f"{code} 歷史股價")
        result = technical.analyze_stock(code, hist, cfg)
        result.update({"name": f"{code} {name}", "is_watchlist": code in watch_codes})
        technicals.append(result)
    technicals.sort(key=lambda x: not x["is_watchlist"])

    # 自選股命中，置頂
    hits = screener.watchlist_hits(themes_raw, dark_horses, cfg["watchlist"])

    commentary = _safe(
        lambda: llm.market_commentary({"market": market, "institutional": inst,
                                       "themes": themes_raw, "type": "evening"}),
        "", "盤後評論")

    # 法人買賣超趨勢圖：從近期市場快照撈外資單日買賣超
    recent_snaps = _safe(
        lambda: db.snapshots_between(
            (date.fromisoformat(today) - timedelta(days=16)).isoformat(), today),
        [], "法人趨勢資料")
    inst_chart = render.mark_safe(charts.diverging_bars(
        [{"label": s["date"][5:], "value": s.get("foreign_net")}
         for s in recent_snaps if s.get("foreign_net") is not None],
    )) if len(recent_snaps) >= 2 else ""

    ctx = {
        "report_kind": "盤後 · 每日市場摘要",
        "date_label": render.date_label(today),
        "market": market, "inst": inst,
        "watchlist_hits": hits,
        "themes": themes_view,
        "dark_horses": dark_horses,
        "technicals": technicals,
        "earnings_calls": calls,
        "commentary": commentary,
        "inst_chart": inst_chart,
        "index_cards": index_cards,
        "inst_ranking": inst_ranking,
    }

    path = render.render_daily(ctx, f"{today}-evening")

    # 題材生命週期：退場機制
    lc = cfg["theme_lifecycle"]
    changed = db.apply_theme_lifecycle(today, lc["dormant_after_days"],
                                       lc["archive_after_declines"])
    if changed["dormant"] or changed["archived"]:
        print(f"[evening] 題材狀態更新：{changed}")

    # 深度報告：只有夠格的題材才動用重量級分析
    for theme in db.themes_ready_for_deep_dive(lc["deep_dive_min_days"]):
        if theme.get("deep_dive_slug"):
            continue
        timeline = db.get_theme_timeline(theme["id"])
        article = _safe(lambda t=theme, tl=timeline: llm.write_deep_dive(t, tl),
                        {}, f"深度報告 {theme['name']}")
        if article:
            slug = render.slugify(theme["name"])
            render.render_article(theme, article, slug)
            db.set_deep_dive_slug(theme["id"], slug)
            print(f"[evening] 深度報告已產出：{theme['name']}")

    render.render_site()
    print(f"[evening] 完成：{path}")
    send_notification(f"盤後報告已產出：{render.date_label(today)}", commentary)


# ── 月報：含事後驗證 ───────────────────────────────────
def run_monthly() -> None:
    cfg = load_config()
    today = today_str()
    print(f"[monthly] 產出月報 {today}")

    def price_fn(code: str, _d: str) -> float | None:
        hist = twse.fetch_stock_history(code, 5)
        return hist[-1]["close"] if hist else None

    def index_fn(_d: str) -> float | None:
        return twse.fetch_index_summary().get("taiex_close")

    summary = _safe(
        lambda: review.run_review(today, cfg["review"]["horizons_days"], price_fn, index_fn),
        {}, "事後驗證")

    scorecards = []
    lines = []
    for horizon, data in summary.items():
        verdict = review.format_scorecard(data["scorecard"])
        lines.append(f"【{horizon} 天回顧】{verdict}")
        scorecards.append({
            "horizon": horizon,
            "reviewed": data.get("reviewed", 0),
            "rows": data["scorecard"],
            "verdict": verdict,
        })
    verdict_text = "\n".join(lines) or "尚無足夠驗證樣本。"

    # 本月題材增減
    d = date.fromisoformat(today)
    month_start = d.replace(day=1).isoformat()
    added = _safe(lambda: db.themes_first_seen_between(month_start, today), [], "本月新增題材")
    retired = _safe(lambda: db.themes_retired_between(month_start, today), [], "本月退場題材")
    dist = _safe(db.confidence_distribution, [], "信心度分布")

    ctx = {
        "report_kind": "月報 · 事後驗證",
        "date_label": render.date_label(today),
        "month_label": f"{d.year} 年 {d.month} 月",
        "scorecards": scorecards,
        "themes_added": [render.decorate_theme(t) for t in added],
        "themes_retired": [render.decorate_theme(t) for t in retired],
        "confidence_dist": dist,
        "verdict_text": verdict_text,
    }
    path = _safe(lambda: render.render_monthly(ctx, f"{today}-monthly"), None, "月報頁面")

    print(f"[monthly] {verdict_text}")
    render.render_site()
    if path:
        print(f"[monthly] 完成：{path}")
    send_notification(f"月報已產出：{today}", verdict_text)


# ── 假日功課 ───────────────────────────────────────────
def run_holiday() -> None:
    cfg = load_config()
    today = today_str()
    print(f"[holiday] 產出假日功課 {today}")

    themes = [render.decorate_theme(t) for t in db.list_themes("active")]
    upcoming = _safe(lambda: mops.fetch_upcoming_calls(7), [], "下週法說會")

    ctx = {
        "report_kind": "假日功課",
        "date_label": render.date_label(today),
        "themes": themes,
        "earnings_calls": upcoming,
        "commentary": (f"目前追蹤中題材 {len(themes)} 個。"
                       f"下一個交易日為 {next_trading_day()}。"),
    }
    path = render.render_daily(ctx, f"{today}-holiday")
    render.render_site()
    print(f"[holiday] 完成：{path}")


# ── 長假彙整：休市期間國際盤逐日變化 ───────────────────
def run_holiday_wrapup() -> None:
    cfg = load_config()
    today = today_str()
    print(f"[wrapup] 產出長假彙整報告 {today}")

    from .market_calendar import consecutive_closed_days
    window = max(consecutive_closed_days() + 2, 5)
    history = _safe(lambda: international.fetch_index_history(window), [], "國際盤歷史")

    index_charts = []
    for idx in history:
        rows = idx.get("rows", [])
        if len(rows) < 2:
            continue
        index_charts.append({
            "name": idx["name"],
            "rows": rows,
            "total_change": round(
                (rows[-1]["close"] - rows[0]["close"]) / rows[0]["close"] * 100, 2),
            "chart": render.mark_safe(charts.line_chart(
                [r["date"][5:] for r in rows], [r["close"] for r in rows])),
        })

    themes = [render.decorate_theme(t) for t in db.list_themes("active")]

    ctx = {
        "report_kind": "長假彙整 · 國際盤逐日回顧",
        "date_label": render.date_label(today),
        "index_charts": index_charts,
        "themes": themes,
        "next_open": str(next_trading_day()),
        "commentary": ("休市期間國際盤逐日變化如下，開盤前先掃一遍，"
                       "遇到跳空缺口時心裡有個底。"),
    }
    path = _safe(lambda: render.render_holiday_wrapup(ctx, f"{today}-wrapup"), None, "長假彙整頁面")
    render.render_site()
    if path:
        print(f"[wrapup] 完成：{path}")
    send_notification(f"長假彙整已產出：{render.date_label(today)}", ctx["commentary"])


# ── 自動分支（排程呼叫這個） ───────────────────────────
def run_auto(slot: str) -> None:
    """slot = morning / evening，由 cron 傳入時段，再由行事曆決定實際跑什麼。"""
    refresh_holidays()
    kind = classify_day()
    print(f"[auto] slot={slot} 今日類型={kind}")

    if kind == "full_holiday":
        if slot == "morning":
            run_holiday()
        return

    if slot == "morning":
        run_morning()
        return

    # slot == evening
    if kind == "trading":
        run_evening()
    else:
        print("[auto] 台股今日休市，略過盤後報告")
        if is_last_day_before_reopen():
            print("[auto] 長假最後一日，產出假期彙整")
            run_holiday_wrapup()


def main() -> None:
    db.init_db()
    mode = sys.argv[1] if len(sys.argv) > 1 else "auto"

    dispatch = {
        "morning": run_morning,
        "evening": run_evening,
        "monthly": run_monthly,
        "holiday": run_holiday,
        "wrapup": run_holiday_wrapup,
        "site": lambda: render.render_site(),
    }

    if mode == "auto":
        run_auto(sys.argv[2] if len(sys.argv) > 2 else "evening")
    elif mode in dispatch:
        dispatch[mode]()
    else:
        print(f"未知模式：{mode}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
