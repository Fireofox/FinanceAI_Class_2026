# yfinance-financial-data (Python venv + pip)

透過 Python `yfinance` 查詢股票、ETF、基金、指數、外匯、加密貨幣資料的跨 Agent Skill。**不使用 uv**。

## 需求

Python 3.10–3.14、pip、venv、網際網路連線。主入口為 `SKILL.md`，程式入口為 `scripts/yf_query.py`。

## 安裝（Linux / macOS）

```bash
cd yfinance-financial-data
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/yf_query.py --help
```

若系統沒有 `venv`，Ubuntu / Debian 可先安裝相應版本的 `python3-venv`。

## 安裝（Windows PowerShell）

```powershell
cd yfinance-financial-data
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts\yf_query.py --help
```

## 查詢範例（已啟用虛擬環境）

```bash
python scripts/yf_query.py info 2330.TW --fields longName,marketCap,trailingPE
python scripts/yf_query.py quote AAPL
python scripts/yf_query.py history NVDA --period 1y --interval 1d
python scripts/yf_query.py fund SPY --kind top_holdings
python scripts/yf_query.py fields --search 市值
```

## 測試

```bash
python -m unittest discover -s tests -v
```

## 更新套件

```bash
python -m pip install --upgrade -r requirements.txt
```

若要可重現的正式部署版本，請在驗證環境後執行 `python -m pip freeze > requirements-lock.txt` 並使用鎖定版本部署。Yahoo Finance 有資料延遲、涵蓋率及授權限制，詳見 `references/usage.md`。

## Full daily history without truncation

```bash
python scripts/yf_query.py history 2330.TW --period 1y --interval 1d --csv 2330_history.csv --output 2330_history.json
```

History defaults to all records (`--limit 0`). JSON response includes `total_rows`, `returned_rows`, and `truncated`. When `--output` is used, stdout contains a compact summary and the complete JSON is written to disk. CSV is UTF-8 BOM for Excel compatibility.
