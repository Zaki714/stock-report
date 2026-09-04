# 盤後快訊 — 台股／國際盤自動分析系統

每日自動產出市場分析報告，發佈成靜態網站並推播到 Telegram。全部跑在免費額度內。

## 這套系統做什麼

| 時間 | 產出 |
|---|---|
| 每日 07:00 | 早報：國際四大指數 + 海外 ADR 卡片（含走勢線）、總經、國際題材追蹤、台股中文新聞、當日法說會 |
| 每日 18:00 | 盤後：加權/櫃買指數卡片（含走勢線）、三大法人動向 + 個股買賣超排名、題材分析、黑馬觀察、技術面 |
| 每月 12 日 | 月報 + 事後驗證（回頭檢查過去判斷準不準） |
| 假日 | 假日功課（題材回顧、下週行事曆） |

分析層四道關卡：**強勢股掃描 → LLM 題材聚類 → 真假驗證 → 信心度評分**。
找不到同族群呼應的個股不會被硬套題材，會分流到「黑馬觀察」給風險標記。

**指數卡片＋迷你走勢線**：加權指數、櫃買指數（盤後）、國際四大指數、海外 ADR（早報）
都用同一種「數字＋漲跌＋走勢線」卡片呈現。台股指數的免費 API 只給最近幾天的滾動視窗，
所以自己每天存一筆快照（`index_snapshots`），走勢線會隨系統運作天數增長；
國際指數／ADR 用 yfinance 一次能拿一個月歷史，不受此限制。

**個股三大法人買賣超排名**：上市個股（含 ETF）依三大法人合計買賣超股數排名，
盤後報告列出買超／賣超前 N 名（`config.yaml` 的 `institutional_ranking.top_n`）。

早報另含**國際題材追蹤**（外電頭條 + 類股 ETF 資金流向 → LLM 歸納當週當紅題材，
寫進同一個題材知識庫，`scope='intl'`）跟**台股中文新聞**（同一套 Google News RSS，
換成台灣地區、繁中查詢）。當週第一個交易日的早報會附上**上週回顧**。
長假最後一天會產出**長假彙整報告**，把休市期間國際盤逐日變化整理好，避免開紅盤被跳空嚇到。

## 快速開始（本地）

最快的方式是跑一鍵設定腳本：

```bash
bash setup.sh
```

它會檢查環境、安裝套件、跑一次測試、初始化 git。
涉及帳號憑證的步驟（API key、GitHub Secrets）不在腳本範圍內，需要你自己操作。

手動步驟：

```bash
git clone <你的 repo 網址>
cd stock-report
pip install -r requirements.txt

# 用假資料跑一次，不需要任何 API key
DRY_RUN=1 python -m src.main evening

# 開啟結果
open docs/index.html          # macOS
start docs/index.html         # Windows
```

跑真實資料：

```bash
cp .env.example .env          # 填入 ANTHROPIC_API_KEY
export $(cat .env | xargs)
DRY_RUN=0 python -m src.main evening
```

## 指令

```bash
python -m src.main morning         # 國際盤早報（含國際題材追蹤；當週第一個交易日附上週回顧）
python -m src.main evening         # 台股盤後
python -m src.main monthly         # 月報 + 事後驗證（產出 HTML 頁面）
python -m src.main holiday         # 假日功課
python -m src.main wrapup          # 長假彙整（休市期間國際盤逐日回顧）
python -m src.main site            # 只重建索引頁
python -m src.main auto evening    # 自動判斷（排程用）
```

## 專案結構

```
config.yaml              ← 日常只需要改這個檔案
src/
  config.py              設定與時區（一律用台北時間）
  market_calendar.py     開休市判斷（查 TWSE，不用星期幾猜）
  db.py                  SQLite：題材知識庫、判斷快照、市場快照
  llm.py                 Claude API：題材聚類、深度報告
  render.py              Jinja2 → docs/ 靜態網頁
  notify.py              Telegram 推播
  main.py                入口與分支
  fetchers/
    twse.py              台股（TWSE 開放 API）+ 個股三大法人買賣超排名（T86）
    tpex.py              櫃買指數（TPEx 開放 API）
    international.py     國際盤指數／ADR + 類股 ETF 資金流向（yfinance）
    mops.py              法說會（公開資訊觀測站）
    news.py              財經頭條（Google News RSS，免 key；英文/繁中皆可）
    mock.py              DRY_RUN 假資料
  analysis/
    screener.py          強勢股掃描、黑馬判定、自選股比對
    technical.py         均線／KD／RSI／MACD／量價
    review.py            事後驗證（超額報酬）
    global_themes.py     國際題材追蹤（頭條 + ETF → LLM 歸納）
    recap.py             週報彙整（從市場快照撈，不重抓）
    charts.py            輕量 SVG 圖表（無外部相依）
templates/               網頁模板（daily / monthly / holiday_wrapup / article / index / archive / themes）
docs/                    產出的網站（GitHub Pages 根目錄）
data/market.db           資料庫（跟著 git 走，等於自動備份）
```

## 設定

改 `config.yaml`：

- `watchlist` — 你的自選股，被掃到會置頂標記
- `screener` — 強勢股門檻（漲幅、量能倍數、成交金額）
- `theme_lifecycle` — 題材休眠／退場條件、深度報告觸發門檻
- `site.base_url` — 部署後填入，推播訊息會附上連結

機密資訊走環境變數，不要寫進 `config.yaml`：
`ANTHROPIC_API_KEY`、`TELEGRAM_BOT_TOKEN`、`TELEGRAM_CHAT_ID`

## 部署

見 `DEPLOY.md`。

## 設計上的幾個決定

**為什麼盤後是 18:00 不是 13:30**
13:30 只是停止交易，三大法人、融資融券、期貨籌碼的官方統計都還沒落地。
18:00 留足緩衝，確保抓到的是完整且修正過的版本。

**為什麼月報是 12 日**
月營收依規定須在次月 10 日前公告（遇假日順延）。抓 12 日留兩天緩衝。
農曆年前後那個月建議手動確認公告進度，長假可能順延超過兩天。

**為什麼黑馬不給信心度**
黑馬的本質是資訊不對稱。套用跟題材股同一套信心度語言會誤導人，
所以改成風險標記（量能倍數、公告佐證、法人動向），明確標示「觀察而非追蹤」。

**為什麼要存判斷快照**
沒有回饋迴路的分析系統只是播報器。每次說「值得留意」都先存檔，
14／30 天後回頭算超額報酬（個股 − 大盤），才知道判斷邏輯到底準不準。

**為什麼用 SQLite**
單一檔案、免架服務、可直接 commit 進 git 當版本備份。
撐不住時再換 Postgres，schema 不用重寫。

## 免責

本系統為個人研究工具，產出內容僅供參考，不構成投資建議。
