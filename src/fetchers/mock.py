"""DRY_RUN 用的假資料。

作用：沒有網路、沒有 API key 時也能把整條流程跑完，用來驗證版面與邏輯。
上線後設 DRY_RUN=0 就會走真實 API，這個檔案不會被呼叫到。
"""
from __future__ import annotations

import random
from datetime import date, timedelta

random.seed(42)   # 固定亂數，讓每次測試輸出一致


def index_summary() -> dict:
    return {
        "taiex_close": 24586.12,
        "taiex_change": 186.42,
        "taiex_change_pct": 0.76,
        "turnover": 384_200_000_000,
        "advancers": 612,
        "decliners": 398,
    }


def institutional_net() -> dict:
    return {
        "foreign_net": 48.2,
        "trust_net": 18.6,
        "dealer_net": -4.4,
        "total_net": 62.4,
    }


_MOCK_STOCKS = [
    ("1590", "亞德客-KY", 6.8, 4.2), ("2049", "上銀", 5.9, 3.1),
    ("4551", "智伸科", 8.2, 5.4), ("2330", "台積電", 1.8, 1.2),
    ("3017", "奇鋐", 6.1, 2.8), ("3661", "世芯-KY", 5.2, 2.4),
    ("6187", "萬潤", 9.4, 6.7), ("2454", "聯發科", 2.1, 1.4),
    ("3324", "雙鴻", 5.5, 2.9), ("1521", "大銀微系統", 7.3, 3.8),
]


def daily_quotes() -> list[dict]:
    quotes = []
    for code, name, pct, vol_ratio in _MOCK_STOCKS:
        close = round(random.uniform(80, 900), 1)
        quotes.append({
            "code": code, "name": name, "close": close,
            "change": round(close * pct / 100, 2), "change_pct": pct,
            "volume": int(vol_ratio * 5_000_000),
            "turnover": int(close * vol_ratio * 5_000_000),
            "volume_ratio": vol_ratio,
        })
    # 補一些平盤股，讓掃描器的篩選邏輯真的有東西可以濾
    for i in range(40):
        quotes.append({
            "code": f"9{i:03d}", "name": f"測試股{i}", "close": 50.0,
            "change": 0.2, "change_pct": 0.4, "volume": 500_000,
            "turnover": 25_000_000, "volume_ratio": 0.9,
        })
    return quotes


def stock_history(code: str, days: int = 120) -> list[dict]:
    """生一段有趨勢的假 K 線，讓技術指標算出來的結果有意義。"""
    rows = []
    price = 100.0
    drift = 0.004 if code in ("1590", "2049", "4551") else -0.001
    today = date.today()
    for i in range(days, 0, -1):
        price *= (1 + drift + random.gauss(0, 0.015))
        price = max(price, 5.0)
        rows.append({
            "date": (today - timedelta(days=i)).isoformat(),
            "open": round(price * 0.995, 2), "high": round(price * 1.012, 2),
            "low": round(price * 0.988, 2), "close": round(price, 2),
            "volume": int(random.uniform(3_000, 12_000) * 1000),
        })
    return rows


def _fake_history(base: float, days: int = 22, drift: float = 0.0) -> list[float]:
    """生一段假的收盤序列，給指數卡片的迷你走勢線用。"""
    rows, price = [], base
    for _ in range(days):
        price *= (1 + drift + random.gauss(0, 0.008))
        rows.append(round(price, 2))
    return rows


def _index_card(name: str, base: float, drift: float = 0.0) -> dict:
    hist = _fake_history(base, drift=drift)
    close, prev = hist[-1], hist[-2]
    change = round(close - prev, 2)
    return {
        "name": name, "close": close, "change": change,
        "change_pct": round(change / prev * 100, 2) if prev else 0.0,
        "history": hist,
    }


def international_markets() -> dict:
    return {
        "indices": [
            _index_card("道瓊", 45218.0, -0.001),
            _index_card("那斯達克", 19864.0, 0.002),
            _index_card("S&P 500", 6142.0, 0.001),
            _index_card("費半 SOX", 5712.0, 0.003),
        ],
        "adrs": [
            _index_card("台積電 ADR", 198.4, 0.002),
            _index_card("聯電 ADR", 8.6, 0.001),
            _index_card("日月光 ADR", 9.2, -0.001),
        ],
        "macro": [
            {"name": "美元指數", "value": "102.4（+0.12%）"},
            {"name": "西德州原油", "value": "78.3（-0.45%）"},
            {"name": "黃金", "value": "2,634.5（+0.30%）"},
        ],
    }


def otc_index() -> dict:
    hist = _fake_history(238.0, drift=0.0015)
    close, prev = hist[-1], hist[-2]
    change = round(close - prev, 2)
    return {
        "close": close, "change": change,
        "change_pct": round(change / prev * 100, 2) if prev else 0.0,
        "recent": [{"date": (date.today() - timedelta(days=i)).isoformat(),
                    "close": c, "change": 0.0}
                   for i, c in enumerate(reversed(hist[-4:]))],
    }


def taiex_recent(days: int = 5) -> list[dict]:
    """DRY_RUN：加權指數最近幾天走勢，補齊 index_snapshots 用。跟 otc_index() 的
    recent 一樣特意不用 date.today()（見 main.py 的 DRY_RUN 回填判斷）。"""
    hist = _fake_history(24500.0, drift=0.0008)[-days:]
    out, prev = [], None
    for i, c in enumerate(hist):
        change = round(c - prev, 2) if prev else 0.0
        out.append({"date": f"mock-day-{i}", "close": c, "change": change,
                    "change_pct": round(change / prev * 100, 2) if prev else 0.0})
        prev = c
    return out


def institutional_ranking() -> list[dict]:
    """DRY_RUN：個股三大法人買賣超排名。買超／賣超各給 12 檔，
    數量刻意大於 config 預設的 top_n（10），避免排行榜前後兩段重疊。"""
    buys = [("2330", "台積電"), ("2317", "鴻海"), ("2454", "聯發科"),
            ("2303", "聯電"), ("3231", "緯創"), ("00878", "國泰永續高股息"),
            ("2308", "台達電"), ("2382", "廣達"), ("3661", "世芯-KY"),
            ("6669", "緯穎"), ("2412", "中華電"), ("2603", "長榮")]
    sells = [("2327", "國巨"), ("2481", "強茂"), ("2409", "友達"),
             ("6770", "力積電"), ("3481", "群創"), ("2834", "臺企銀"),
             ("2610", "華航"), ("2618", "長榮航"), ("1216", "統一"),
             ("2891", "中信金"), ("2882", "國泰金"), ("2884", "玉山金")]

    out = []
    for code, name in buys:
        net = random.randint(2_000_000, 30_000_000)
        out.append({"code": code, "name": name, "is_etf": code.startswith("00"),
                    "foreign_net": net * 0.7, "trust_net": net * 0.1,
                    "dealer_net": net * 0.2, "total_net": net})
    for code, name in sells:
        net = -random.randint(2_000_000, 30_000_000)
        out.append({"code": code, "name": name, "is_etf": code.startswith("00"),
                    "foreign_net": net * 0.7, "trust_net": net * 0.1,
                    "dealer_net": net * 0.2, "total_net": net})

    out.sort(key=lambda x: x["total_net"], reverse=True)
    return out


def tw_headlines() -> list[dict]:
    return [
        {"title": "台積電法說會釋樂觀展望，外資喊上看新高",
         "source": "經濟日報", "published": "Fri, 04 Sep 2026 08:10:00", "link": "", "query": "台積電"},
        {"title": "外資連三日買超台股，加權指數收復所有均線",
         "source": "工商時報", "published": "Fri, 04 Sep 2026 07:50:00", "link": "", "query": "台股 大盤"},
        {"title": "機器人減速機族群走強，法人點名這幾檔受惠",
         "source": "MoneyDJ", "published": "Fri, 04 Sep 2026 07:30:00", "link": "", "query": "台股 大盤"},
    ]


def earnings_calls() -> list[dict]:
    return [
        {"code": "2049", "name": "上銀", "time": "14:00",
         "note": "市場關注機器人減速機訂單能見度"},
        {"code": "3017", "name": "奇鋐", "time": "15:00",
         "note": "AI 伺服器散熱出貨展望"},
    ]


def global_headlines() -> list[dict]:
    """DRY_RUN：代替 Google News RSS 的國際財經頭條。"""
    return [
        {"title": "Nvidia suppliers rally as AI datacenter capex guidance raised",
         "source": "Reuters", "published": "Mon, 01 Sep 2025 12:10:00",
         "link": "https://example.com/1", "query": "AI datacenter capex"},
        {"title": "US semiconductor stocks extend gains on strong chip demand outlook",
         "source": "Bloomberg", "published": "Mon, 01 Sep 2025 11:40:00",
         "link": "https://example.com/2", "query": "semiconductor OR AI chip demand"},
        {"title": "Fed officials signal patience on rate cuts amid sticky inflation",
         "source": "WSJ", "published": "Mon, 01 Sep 2025 09:20:00",
         "link": "https://example.com/3", "query": "Federal Reserve rate decision"},
        {"title": "Analysts lift price targets across AI server supply chain",
         "source": "CNBC", "published": "Sun, 31 Aug 2025 22:05:00",
         "link": "https://example.com/4", "query": "AI datacenter capex"},
        {"title": "Tech megacaps lead S&P 500 higher as Treasury yields ease",
         "source": "Financial Times", "published": "Sun, 31 Aug 2025 20:30:00",
         "link": "https://example.com/5", "query": "US technology stocks rally OR selloff"},
        {"title": "Memory chip prices firm on datacenter restocking",
         "source": "Nikkei Asia", "published": "Sun, 31 Aug 2025 18:00:00",
         "link": "https://example.com/6", "query": "semiconductor OR AI chip demand"},
    ]


def sector_etf_flows() -> list[dict]:
    """DRY_RUN：類股 ETF 的價格動能與量能倍數（資金流向近似值）。"""
    return [
        {"name": "科技 XLK", "symbol": "XLK", "change_pct": 1.12, "volume_ratio": 1.34, "flow": "資金流入"},
        {"name": "半導體 SMH", "symbol": "SMH", "change_pct": 1.86, "volume_ratio": 1.52, "flow": "資金流入"},
        {"name": "金融 XLF", "symbol": "XLF", "change_pct": -0.24, "volume_ratio": 0.92, "flow": "持平"},
        {"name": "能源 XLE", "symbol": "XLE", "change_pct": -0.71, "volume_ratio": 1.28, "flow": "資金流出"},
    ]


def international_history(days: int = 8) -> list[dict]:
    """DRY_RUN：長假期間國際盤逐日變化。"""
    base = {"道瓊": 45000.0, "那斯達克": 19600.0, "S&P 500": 6100.0, "費半 SOX": 5600.0}
    out = []
    for name, start in base.items():
        rows, price = [], start
        for i in range(days):
            price *= (1 + random.gauss(0.0015, 0.011))
            prev = rows[-1]["close"] if rows else start
            rows.append({
                "date": (date.today() - timedelta(days=days - i)).isoformat(),
                "close": round(price, 2),
                "change_pct": round((price - prev) / prev * 100, 2) if rows else 0.0,
            })
        out.append({"name": name, "rows": rows})
    return out


def llm_global_theme_response() -> dict:
    """DRY_RUN：代替 Claude API 回傳的國際題材歸納結果。"""
    return {
        "themes": [
            {
                "name": "AI 伺服器資本支出上修",
                "summary": "雲端業者上修 AI datacenter capex 指引，外電高頻提及，半導體與科技 ETF 同步量增價漲。",
                "confidence": "high",
                "verdict": "real",
                "reasoning": "頭條關鍵字一致集中於 AI capex 與晶片需求；SMH／XLK 量增價漲顯示資金流入；"
                             "多家投行同步調升 AI 伺服器供應鏈目標價，機構態度一致性高。",
                "keywords": ["AI datacenter capex", "semiconductor demand", "price target raised"],
                "etf_signal": "SMH +1.86%（量能 1.52 倍，資金流入）、XLK +1.12%（資金流入）",
                "institution_signal": "投行評等調升 > 調降，一致性高",
                "stocks": [
                    {"code": "NVDA", "name": "Nvidia"},
                    {"code": "AVGO", "name": "Broadcom"},
                    {"code": "SMH", "name": "半導體 ETF"},
                ],
            },
            {
                "name": "降息預期降溫",
                "summary": "Fed 官員表態對降息保持耐心，通膨仍黏著，債券殖利率牽動風險性資產評價。",
                "confidence": "mid",
                "verdict": "watch",
                "reasoning": "頭條有明確脈絡但方向未定；金融 ETF 表現平淡，尚無一致資金流向訊號。",
                "keywords": ["Federal Reserve", "rate cuts", "sticky inflation"],
                "etf_signal": "XLF -0.24%（量能持平）",
                "institution_signal": "分歧，無一致調升／調降",
                "stocks": [],
            },
        ],
    }


def llm_theme_response() -> dict:
    """DRY_RUN 時代替 Claude API 回傳的題材聚類結果。"""
    return {
        "themes": [
            {
                "name": "機器人減速機",
                "summary": "日系機器人大廠上修資本支出，帶動台廠訂單能見度轉佳。",
                "confidence": "high",
                "verdict": "real",
                "reasoning": "產業鏈上下游同步表態，外資投信同步買超，月營收年增加速。",
                "stocks": [
                    {"code": "1590", "name": "亞德客-KY"},
                    {"code": "2049", "name": "上銀"},
                    {"code": "1521", "name": "大銀微系統"},
                ],
            },
            {
                "name": "AI 伺服器散熱",
                "summary": "液冷散熱滲透率提升，台廠散熱模組訂單同步走揚。",
                "confidence": "mid",
                "verdict": "real",
                "reasoning": "族群廣度足夠，但部分個股營收尚未同步反映。",
                "stocks": [
                    {"code": "3017", "name": "奇鋐"},
                    {"code": "3324", "name": "雙鴻"},
                    {"code": "2330", "name": "台積電"},
                ],
            },
        ],
        "orphans": [
            {
                "code": "6187", "name": "萬潤",
                "reason": "爆量上漲但無同族群呼應，亦無明確題材脈絡。",
            }
        ],
    }
