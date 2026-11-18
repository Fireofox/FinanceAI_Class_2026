# DuckDuckGo MCP Server 範例

這是可獨立複製的 Python MCP Server，使用 stdio 提供 DuckDuckGo `web_search` 與網頁正文擷取功能，可作為建立網路工具的參考。

## 複製與安裝

需要 Python 3.11 以上及 [uv](https://docs.astral.sh/uv/getting-started/installation/)。以下從 SimpleAgent 專案目錄執行：

```powershell
New-Item -ItemType Directory -Path ../my-duckduckgo-server -ErrorAction Stop
$exampleFiles = @(
  'Package/MCP/duckduckgo-mcp-server/server.py',
  'Package/MCP/duckduckgo-mcp-server/search_backend.py',
  'Package/MCP/duckduckgo-mcp-server/page_fetch.py',
  'Package/MCP/duckduckgo-mcp-server/verify.py',
  'Package/MCP/duckduckgo-mcp-server/pyproject.toml',
  'Package/MCP/duckduckgo-mcp-server/README.md'
)
Copy-Item -Path $exampleFiles -Destination ../my-duckduckgo-server
Set-Location ../my-duckduckgo-server
uv sync
```

範例有自己的 `pyproject.toml`，不依賴 SimpleAgent 套件。請選擇尚不存在的目標目錄；上述步驟只複製必要檔案，避免帶入既有虛擬環境。

## 執行與驗證

```powershell
uv run python verify.py
```

驗證程式會啟動伺服器，透過 MCP 探索並呼叫 `web_search`；預設驗證不需要網路或模型 API 金鑰。也可執行 `uv run python verify.py --live` 驗證實際搜尋，這需要網路連線，且結果可能受到搜尋服務限流影響。

直接執行伺服器的指令如下；它會等待 MCP 用戶端連線，可按 Ctrl+C 結束。stdio 由 MCP 通訊使用，請將除錯訊息寫入標準錯誤。

```powershell
uv run python server.py
```

## 修改與新增工具

- [server.py](server.py)：定義 `web_search`、參數及 MCP 伺服器。可修改工具實作或參考 `@mcp.tool()` 新增函式。
- [search_backend.py](search_backend.py)：搜尋 DuckDuckGo 並處理網站過濾。
- [page_fetch.py](page_fetch.py)：下載 HTML 並擷取主要文字。
- [verify.py](verify.py)：驗證 MCP 工具探索和呼叫；修改工具介面後可同步調整。

這些檔案是可獨立修改的範例副本；若調整其中的搜尋或擷取邏輯，應自行維護該副本。

## 連接 SimpleAgent

在啟動 SimpleAgent 的目錄，將以下項目加入 `config.json` 的 `mcpServers` 物件：

```json
"my_duckduckgo": {
  "command": "uv",
  "args": ["run", "python", "server.py"],
  "cwd": "../my-duckduckgo-server"
}
```

依實際位置修改 `cwd`；相對路徑相對於 SimpleAgent 的啟動目錄。若已有其他伺服器，保留原有項目並用逗號分隔。重新啟動 SimpleAgent 後，可要求模型使用 `my_duckduckgo` 的 `web_search` 工具；模型 API 須支援工具呼叫。

## 搜尋設定

`query` 是搜尋字串；`max_results` 預設 5，範圍 1～10。`region` 預設 `tw-tzh`，`safesearch` 可設為 `strict`、`moderate`（預設）或 `off`；`timelimit` 可選 `d`、`w`、`m` 或 `y`。以 `site` 指定單一網域及其子網域。`include_content` 預設為 `false`，設為 `true` 時會嘗試擷取每筆結果的一般 HTML 正文。搜尋結果包含標題、網址與摘要；個別網頁無法讀取時會保留結果並回報原因。

可透過 `mcpServers.my_duckduckgo.env` 設定下列環境變數，變更後重新啟動 SimpleAgent：

| 環境變數 | 預設值 | 用途 |
| --- | ---: | --- |
| `SIMPLE_AGENT_SEARCH_TIMEOUT` | `15` | 搜尋逾時秒數 |
| `SIMPLE_AGENT_PAGE_TIMEOUT` | `10` | 單頁擷取逾時秒數 |
| `SIMPLE_AGENT_TOTAL_TIMEOUT` | `60` | 單次工具呼叫的整體逾時秒數 |
| `SIMPLE_AGENT_PAGE_CHAR_LIMIT` | `20000` | 每頁正文最多字元數 |
| `SIMPLE_AGENT_TOTAL_CHAR_LIMIT` | `60000` | 每次回傳正文的總字元上限 |

正文擷取依賴搜尋服務與公開網頁；動態產生的頁面、PDF 或需要登入的內容可能無法擷取。輸出超過上限時會標示截斷。
