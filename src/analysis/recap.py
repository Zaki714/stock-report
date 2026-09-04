"""週報彙整。

不獨立開排程：台股週五 13:30 收盤，但美股週五晚上才交易，
週五發的週報會漏掉整個美股交易日。改成在「當週第一個交易日」的早報裡帶出上週回顧。

資料全部從 market_snapshots 撈，不重新抓 API。
"""
from __future__ import annotations

from datetime import date, timedelta

from .. import db


def weekly_recap(today: str) -> dict:
    """回顧 today 之前 7 天的台股表現。資料不足回傳 {}。"""
    end = date.fromisoformat(today) - timedelta(days=1)
    start = end - timedelta(days=8)
    snaps = db.snapshots_between(start.isoformat(), end.isoformat())
    if len(snaps) < 2:
        return {}

    first, last = snaps[0], snaps[-1]
    try:
        taiex_change_pct = round(
            (last["taiex_close"] - first["taiex_close"]) / first["taiex_close"] * 100, 2
        )
    except (TypeError, ZeroDivisionError):
        taiex_change_pct = None

    foreign_sum = round(sum(s.get("foreign_net") or 0 for s in snaps), 1)
    trust_sum = round(sum(s.get("trust_net") or 0 for s in snaps), 1)

    daily = []
    for s in snaps:
        daily.append({
            "date": s["date"],
            "taiex_close": s.get("taiex_close"),
            "change_pct": s.get("taiex_change") and s.get("taiex_close")
            and round(s["taiex_change"] / (s["taiex_close"] - s["taiex_change"]) * 100, 2),
            "foreign_net": s.get("foreign_net"),
        })

    valid = [d for d in daily if d["change_pct"] is not None]
    best = max(valid, key=lambda d: d["change_pct"], default=None)
    worst = min(valid, key=lambda d: d["change_pct"], default=None)

    return {
        "period": f"{snaps[0]['date']} ～ {snaps[-1]['date']}",
        "sessions": len(snaps),
        "taiex_change_pct": taiex_change_pct,
        "taiex_close": last.get("taiex_close"),
        "foreign_net_sum": foreign_sum,
        "trust_net_sum": trust_sum,
        "best_day": best,
        "worst_day": worst,
        "daily": daily,
    }
