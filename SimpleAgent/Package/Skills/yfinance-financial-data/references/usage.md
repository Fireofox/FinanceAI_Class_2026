# yfinance 查詢與資料品質參考

## 主要資料面向

- 報價 / 基本資料：`quote`, `info`；info 可能大量欄位缺失，請不要對缺失欄位填 0。
- 行情：`history` 含 OHLCV；`--period` 如 `5d`, `1mo`, `1y`, `5y`, `max`；`--interval` 如 `1m`, `5m`, `1h`, `1d`, `1wk`, `1mo`。短週期通常有較短回溯限制，依 Yahoo 服務調整。
- 財務：年報/季報的三大報表；外匯、指數、加密貨幣可能沒有財報。
- 股數：`shares 2330.TW --limit 0` 取得 Yahoo 提供的帶日期流通在外股數，依日期由新到舊列出；缺資料或無法辨識日期時不得以查詢時間補造。
- 股利與公司行動：可供計算股息，但調整價格、現金分配、稅額和幣別仍需分開處理。
- 分析師：主要見於有研究覆蓋的股票，目標價可能過時。
- ETF：`funds_data` 的持股通常有資料時差；有些市場並不開放基金成分。
- 選擇權：先取 expirations，再按有效到期日取 calls 或 puts；成交價、未平倉量、隱含波動率可能延遲。
- 新聞：僅提供 Yahoo 有涵蓋的新聞來源；日期、標題、發稿人皆需確認。

## 基本資料欄位語意

`marketCap` 市值、`trailingPE` 本益比、`returnOnEquity` ROE、`dividendYield` 股利殖利率、`currentPrice` 目前股價、`financialCurrency` 財報幣別。

`references/info_fields_zh_TW.csv` 由既有中文欄位彙整，包含跨產品與歷史欄位；它不是 yfinance 官方固定 Schema，也不保證每一項仍可取得。對重複 index，Agent 須以目前取得的資料與具體上下文辨識。

## 失敗處理

- `DependencyError`: 在 Skill 根目錄建立 `.venv`，並以虛擬環境的 `python -m pip install -r requirements.txt` 安裝相依套件。
- 連線失敗、403/429、抓取頁面錯誤：降低頻率後重試，或告知 Yahoo 暫不可用；不要無限制重試。
- 空 DataFrame、無數據：回覆目前無資料，不要推斷其不存在或價格為零。
- JSON `retrieved_at_utc`：僅代表本地查詢時間，不是報價撮合時間。
- `--limit`: 限制輸出的資料量；完整資料可用 `--limit 0`，但可能造成巨量輸出。
- 本工具不設快取；重複查詢可能遭 Yahoo 限流。若需要正式服務，外部系統應加入 TTL、排程及授權檢查。

## 服務限制與著作權

Yahoo Finance/yfinance 不應被當作交易所授權的即時行情或有保證 SLA 的資料源。商業 SaaS 產品上線前，請自行確認數據授權、再散布限制及服務條款。來源： https://ranaroussi.github.io/yfinance/ 。

### Full daily history

`python scripts/yf_query.py history AAPL --period 1y --interval 1d --csv aapl.csv --output aapl.json`

`history` defaults to unlimited rows, and `total_rows`/`returned_rows`/`truncated` indicate whether truncation occurred. Chat output may display a preview; the CSV file is the authoritative export.
