# 本機 Python Tavily MCP server

這是一個獨立的 Python MCP server，透過 stdio 提供 `web_search` 工具。SimpleAgent 啟動本機的 `server.py`，由它使用 `httpx` 呼叫 Tavily Search REST API。不連接 Tavily 的雲端 MCP，也不依賴 SimpleAgent 或 Tavily SDK。

```text
SimpleAgent → 本機 server.py（MCP stdio）→ tavily_backend.py → Tavily HTTPS API
```

搜尋請求仍會送往 Tavily 雲端 API；本機執行的是 MCP server。原有 DuckDuckGo MCP 不受影響。

## 共用主專案環境

需要 Python 3.11 以上及 uv。以下 PowerShell 指令均從 SimpleAgent 專案根目錄執行。只準備主專案的 `.venv`，Tavily 共用其中的 Python 與套件，不需要在本目錄另外執行 `uv sync`。

```powershell
uv sync --locked
```

## 接到 SimpleAgent

先完成上述安裝，再從 SimpleAgent 專案根目錄啟動 Agent。以下是 Windows 設定。把 `config.example.json` 中的 `tavily` 項目合併進主專案 `config.json` 的 `mcpServers`，保留模型、金鑰及其他設定：

```json
{
  "mcpServers": {
    "tavily": {
      "command": ".venv/Scripts/python.exe",
      "args": ["examples/MCP/tavily-mcp-server/server.py"],
      "cwd": ".",
      "env": {
        "TAVILY_AUTH_MODE": "keyless"
      }
    }
  }
}
```

這份相對路徑設定以主專案根目錄為啟動目錄。若從其他目錄啟動，將 `command`、`args` 中的腳本路徑及 `cwd` 都改成實際安裝位置的絕對路徑。`command` 直接指向主專案 Python，啟動 Tavily 時不需要 uv，也不會建立 server 專用 `.venv`。重新啟動 Agent 後，可要求：

> 使用 tavily 的 web_search 搜尋 LCP 選手 Doggo 最近一個月的消息。附上來源網址與可取得的文章日期；沒有資料或搜尋失敗時請直接說明。

這份範例設定不會自動改寫主專案 `config.json`。同時啟用多個搜尋 MCP 時，可在需求中指定使用 tavily。

## 複製與發佈

Tavily 的 `pyproject.toml` 保留獨立使用所需的相依套件清單。若要單獨使用，將 `server.py` 及 `tavily_backend.py` 複製到目標目錄，使用已安裝 `httpx`、`mcp` 與 `pydantic` 的既有 Python 環境執行。無須另外建立 `.venv`。

隨 SimpleAgent 發佈時，帶入 `examples/MCP/tavily-mcp-server` 中的腳本，讓設定指向發佈位置的共用 Python。主專案 wheel 目前只包含 `src/simple_agent`，不會自動收錄這個 examples 目錄。本次驗證涵蓋共用 Python 啟動，尚未驗證 PyInstaller 等凍結執行檔打包。

## API key 與免金鑰模式

預設 `TAVILY_AUTH_MODE=auto`：有 `TAVILY_API_KEY` 時使用 Bearer 認證，否則送出 `X-Tavily-Access-Mode: keyless`。上方範例明確使用 `keyless`，適合先測試，不會使用環境中的 API key。

要使用自己的 API key，將 MCP 設定中的 `env` 改為：

```json
{
  "TAVILY_AUTH_MODE": "key",
  "TAVILY_API_KEY": "填入自己的 Tavily API key"
}
```

API key 只放在送往 Tavily API 的 Authorization header，不放在網址或工具結果。不要把含真實金鑰的設定提交到版本控制。keyless 有流量限制，使用金鑰時依帳號額度計費；`advanced` 搜尋及正文擷取的額度規則請以官方文件為準。

## 工具參數

| 參數 | 預設 | 用途 |
| --- | --- | --- |
| `query` | 必填 | 搜尋字串 |
| `max_results` | `5` | 1 至 10 筆 |
| `site` | `null` | 單一網域，例如 `python.org`，包含子網域 |
| `timelimit` | `null` | `d`、`w`、`m`、`y`，對應日、週、月、年 |
| `include_content` | `false` | 請 Tavily 在同一個 Search API 回應中附帶網頁正文 |
| `topic` | `general` | `general` 或 `news` |
| `search_depth` | `basic` | `basic` 或 `advanced` |

工具名稱沿用 `web_search`，結果保留 `title`、`url`、`body`，可另外取得 `score`、`published_date` 和正文。此工具沒有暴露 DuckDuckGo 的 `region`、`safesearch` 參數；Agent 會依探索到的新 schema 呼叫。

## 結果與錯誤

- `ok`：有搜尋結果。
- `empty`：請求成功，但沒有符合條件的結果。
- `partial`：有結果，但部分正文未提供，仍保留摘要及原因。
- `error`：參數、設定、認證、限流、網路或上游回應錯誤。

錯誤附有 `error_code`、`retryable`，HTTP 錯誤另有 `http_status`。每次有效搜尋只發出一次 API 請求，不自動重試。正文使用 `content_truncated` 標示截斷；查詢時間與文章發佈日期的意義不同，搜尋結果也不保證涵蓋所有最新消息。

| 環境變數 | 預設 | 用途 |
| --- | --- | --- |
| `TAVILY_AUTH_MODE` | `auto` | `auto`、`key`、`keyless` |
| `TAVILY_API_KEY` | 空 | 自己的 API key |
| `TAVILY_TIMEOUT` | `30` | 單次 API 呼叫逾時秒數 |
| `TAVILY_PAGE_CHAR_LIMIT` | `20000` | 單頁正文最多字元數 |
| `TAVILY_TOTAL_CHAR_LIMIT` | `60000` | 每次工具回傳正文的合計上限 |

## 檔案與官方契約

- `server.py`：MCP 工具定義與錯誤結果。
- `tavily_backend.py`：認證、HTTP 請求、參數轉換及結果整理。

API 契約依據 [Tavily Search](https://docs.tavily.com/documentation/api-reference/endpoint/search) 與 [Keyless access](https://docs.tavily.com/documentation/keyless)。
