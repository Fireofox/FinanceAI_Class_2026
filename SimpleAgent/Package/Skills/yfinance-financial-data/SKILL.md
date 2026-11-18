---
name: yfinance-financial-data
description: 使用 Python yfinance 查詢全球股票、台股、ETF、共同基金、指數、外匯與加密貨幣的即時或延遲報價、歷史行情、公司資訊、財報、配息、拆股、基金持股、分析師評估、股權結構、選擇權及新聞；在用戶詢問金融商品資料、比較、資料匯出或需要原始可追溯證據時啟用。
compatibility: Requires Python 3.10-3.14, pip, virtualenv (venv) and internet access. Yahoo Finance coverage, latency and licensing vary by market.
---

# YFinance Financial Data Skill

使用 `scripts/yf_query.py` 作為**唯一的金融資料擷取入口**，回傳規範化 JSON，避免 Agent 任意發明欄位。依需求選擇最小查詢；不要每次都下載所有資料。

## Installation

本 Skill 不依賴 uv。獨立執行時可使用 Python 3.10–3.14 與標準 Python `venv` + `pip` 管理依賴。在 Skill 根目錄執行：

Linux / macOS：

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/yf_query.py --help
```

Windows PowerShell：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts\yf_query.py --help
```

後續執行命令時，請使用已啟用虛擬環境中的 `python`（或直接以 `.venv` 下的 Python 執行）。不要將依賴安裝到系統層級的 Python。若在 Linux 系統尚未提供 `venv`，需先安裝發行版對應的 `python3-venv` 套件。

透過 SimpleAgent 的 `run_skill_script` 執行時，腳本使用 SimpleAgent 的 Python 環境，而非此 Skill 的 `.venv`。請使用者先將 `requirements.txt` 的套件安裝到執行 SimpleAgent 的環境；套件不存在時回報錯誤，勿自動修改環境。

請在 Agent 所在主機執行 Python；需要連線 Yahoo Finance。此 Skill 不包含經紀商下單、即時交易執行或投資建議功能。

## Intent → Tool

| 使用者意圖 | 子命令 | 主要來源 |
|---|---|---|
| 公司名稱、產業、市值、PE、財務比率、基本面 | `info` | `Ticker.info` |
| 快速報價、最新價格、前收盤 | `quote` | `Ticker.fast_info`、可用時補充 info |
| 日/週/月 OHLCV、區間報酬、技術分析基礎 | `history` | `Ticker.history` |
| 損益表、資產負債表、現金流量表 | `financials` | `income_stmt`, `balance_sheet`, `cashflow` 及季度版本 |
| 含日期的流通在外股數 | `shares` | `Ticker.get_shares_full`，可用性依商品而異 |
| 股息、分割、公司行動 | `actions` | `dividends`, `splits`, `actions`, `capital_gains` |
| 分析師目標價、評級、盈餘/營收預估 | `analysis` | `analyst_price_targets`, `recommendations`, `earnings_estimate` 等 |
| 主要股東、機構、基金持有人 | `holders` | `major_holders`, `institutional_holders`, `mutualfund_holders` |
| ETF 基金說明、Top holdings、資產與產業配置 | `fund` | `Ticker.funds_data` |
| 選擇權到期日、call/put chain | `options` | `Ticker.options`, `Ticker.option_chain` |
| 商品相關新聞 | `news` | `Ticker.get_news` / `Ticker.news` |
| 特定 info 欄位、全部 index 或中文對照 | `fields` | 本地 `references/info_fields_zh_TW.csv` |

## Commands

```bash
python scripts/yf_query.py info 2330.TW --fields longName,marketCap,trailingPE,returnOnEquity
python scripts/yf_query.py info AAPL --all
python scripts/yf_query.py quote BTC-USD
python scripts/yf_query.py history 0050.TW --period 1y --interval 1d --adjust auto --csv 0050_history.csv --output 0050_history.json
python scripts/yf_query.py financials MSFT --statement income --frequency quarterly
python scripts/yf_query.py shares 2330.TW --limit 0
python scripts/yf_query.py actions 2330.TW --kind dividends
python scripts/yf_query.py analysis NVDA --kind targets
python scripts/yf_query.py fund SPY --kind top_holdings
python scripts/yf_query.py options AAPL --kind expirations
python scripts/yf_query.py options AAPL --expiration 2027-01-15 --kind calls --limit 20
python scripts/yf_query.py holders AAPL --kind institutional
python scripts/yf_query.py news NVDA --limit 5
python scripts/yf_query.py fields --search 股利
python scripts/yf_query.py info AAPL MSFT NVDA --fields currentPrice,marketCap --output /tmp/quotes.json
```

商品代碼必須是 Yahoo Finance 格式：台股上市 `2330.TW`、上櫃 `6488.TWO`、美股 `AAPL`、ETF `0050.TW`/`SPY`、指數 `^GSPC`、外匯 `USDJPY=X`、加密貨幣 `BTC-USD`。商品名稱不等於 ticker；代碼不明時先向使用者確認交易市場，或透過可用搜尋工具查證，不要猜測。

## Response contract & reasoning

1. 讀取 CLI 輸出的 JSON `{ok, command, symbol, retrieved_at_utc, source, data, warnings, error}`；多商品查詢以 `results` 包裝。`ok=false` 代表本次查詢失敗，絕不可將失敗推論成 0 值。
2. 優先採用輸出中的原始值與單位；`null`、空表或缺少欄位解釋為「目前未提供」，不能解釋為零。把幣別、數值時點、頻率、日期與是否調整除權息一併說清楚。
3. `info` 是動態非固定 schema；`references/info_fields_zh_TW.csv` 是中文翻譯對照與候選 key 清單，不是所有欄位都可取得的保證。遇到未列欄位，保留原始 key。
   `shares` 的 `data.shares` 為按日期新到舊排列的 `{index, value}` 清單；`index` 是來源提供的日期，`value` 是股數。空清單表示無可用帶日期資料，不可使用查詢時間推定股數日期。
4. **價格不是保證即時**；市場可能延遲、暫停、休市或行情來源不同。從 `retrieved_at_utc` 只能得知查詢時間，不得聲稱是交易所撮合時間。需要精準行情時應另外確認市場時間戳與資料授權。
5. `history` 的 `auto_adjust` 會影響 OHLC，不可混用不同設定；當談報酬率時區分價格報酬與含息總報酬。
6. 每次輸出標註「資料來源：Yahoo Finance（透過 yfinance）」；若不能連線、限流、403/429、來源格式變更、資料缺漏，透明回報，不補造數字。
7. 金融決策屬高風險領域；可提供計算與分析，但不要把資料當成個人化買賣指令。不要使用公開 yfinance 資料替代交易所或企業授權的商業即時資料。

## Reference files

- `references/info_fields_zh_TW.csv`：原始 `.info` 英文 key／繁體中文名稱候選表（沿用對話的欄位字典）
- `references/usage.md`：涵蓋率、頻率、指令與錯誤處理
- `requirements.txt`：透過 pip 安裝的 Python 套件依賴
- `.venv/`：使用標準 Python venv 建立的本地環境（不包含在交付包中）

## Full history retrieval (important)

- `history` defaults to `--limit 0` (all records), unlike other table commands (default 100).
- `--period 1y --interval 1d` normally has about 240–253 rows, varying by exchange holidays. Never interpret a 10-row preview as the full dataset.
- For user requests to **download, export, retrieve all historical prices**, execute with `--csv prices.csv --output prices.json` and supply the generated files, not a 10-row chat preview.
- Report `total_rows`, `returned_rows`, and `truncated`. Any explicit `--limit N` truncates to N.
- Avoid printing the full price series in chat; summarize the coverage and provide the file.
