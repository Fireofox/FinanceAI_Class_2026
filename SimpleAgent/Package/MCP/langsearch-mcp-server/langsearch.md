# LangSearch MCP 搜尋工具

本專案以 [LangSearch stdio MCP Server](../Package/MCP/langsearch-mcp-server/server.py) 呼叫 [LangSearch Web Search API](https://docs.langsearch.com/reference/search-api-guide-for-coding-agents)。在伺服器目錄使用 `uv run python server.py` 啟動，工具名稱為 `web_search`；SimpleAgent 會依 MCP 伺服器名稱為工具加上識別名稱，因此可與 DuckDuckGo 的 `web_search` 並存，不會自動切換搜尋來源。

## 設定

先在專案目錄執行 `uv sync`。將以下 `langsearch` 項目合併至既有 `config.json` 的 `mcpServers`，保留其他伺服器設定：

```json
{
  "mcpServers": {
    "langsearch": {
      "command": "uv",
      "args": ["run", "python", "server.py"],
      "cwd": "Package/MCP/langsearch-mcp-server",
      "envPassthrough": ["LANGSEARCH_API_KEY"]
    }
  }
}
```

在同一個 PowerShell 設定環境變數並啟動：

```powershell
$env:LANGSEARCH_API_KEY = "你的 LangSearch API 金鑰"
uv run simple-agent
```

也可直接在 `config.json` 指定金鑰：

```json
{
  "mcpServers": {
    "langsearch": {
      "command": "uv",
      "args": ["run", "python", "server.py"],
      "cwd": "Package/MCP/langsearch-mcp-server",
      "env": {"LANGSEARCH_API_KEY": "你的 LangSearch API 金鑰"}
    }
  }
}
```

MCP 子程序只會收到 SDK 預設保留的環境變數，以及 `envPassthrough`、`env` 指定的變數。`envPassthrough` 必須是變數名稱清單；父程序未設定的變數會略過。若 `env` 有同名設定，以 `env` 優先；明確設定空字串也會覆蓋父程序的值。此選項適用於所有 stdio MCP Server，與 HTTP Server 的 `headers` 設定無關。

範例 `cwd` 相對於 SimpleAgent 的啟動目錄；若從其他目錄啟動，請調整為指向 LangSearch 伺服器目錄的相對或絕對路徑。LangSearch 金鑰與模型的頂層 `apiKey` 分開設定；不需要在聊天訊息或工具參數中傳入金鑰。未設定金鑰時仍可列出工具，搜尋時才會提示設定方式。

## 工具參數

| 參數 | 預設值 | 用途 |
| --- | --- | --- |
| `query` | 必填 | 非空白搜尋字串 |
| `max_results` | `5` | 結果筆數，1–50 |
| `include_content` | `false` | 請 LangSearch 回傳網頁正文 |
| `max_content_chars` | `5000` | 每筆正文字元上限，1–20,000；僅開啟正文時傳給 API |
| `freshness` | `noLimit` | `noLimit`、`oneDay`、`oneWeek`、`oneMonth`、`oneYear`，或 UTC 日期／區間 |
| `include_domains` | 未指定 | 限定來源網域清單，例如 `["python.org"]` |
| `exclude_domains` | 未指定 | 排除來源網域清單 |

日期使用 `YYYY-MM-DD`；日期區間使用 `YYYY-MM-DD..YYYY-MM-DD`，包含起訖日期，起日不可晚於迄日。網域清單使用網域字串，空清單代表不限制；篩選由 LangSearch 處理。

呼叫範例：

```json
{
  "query": "Python MCP SDK",
  "max_results": 5,
  "include_content": true,
  "max_content_chars": 5000,
  "freshness": "oneMonth",
  "include_domains": ["github.com", "modelcontextprotocol.io"],
  "exclude_domains": []
}
```

在 SimpleAgent 對話中也可直接要求：「使用 LangSearch 搜尋近一個月 Python MCP SDK 的資料，限定 github.com，取得正文並附上來源網址。」由模型決定實際工具呼叫。

## 回傳與長度限制

```json
{
  "status": "ok",
  "results": [
    {
      "title": "來源標題",
      "url": "https://example.com/page",
      "body": "搜尋摘要",
      "content": "正文內容",
      "content_truncated": false,
      "date_published": "2026-09-01"
    }
  ],
  "usage": {"input_tokens": 3, "output_tokens": 200},
  "log_id": "供診斷的請求識別碼"
}
```

結果依 API 順序保留；少於要求筆數或沒有結果都屬正常，沒有結果時 `status` 為 `empty`。`body` 使用 API 的 `snippet`，缺少時為空字串；發布日期缺少時不提供 `date_published`，不推測日期。API 在正文模式可能只提供 `text` 而沒有摘要，因此 `body` 可能為空。

開啟正文才會提供 `content` 與 `content_truncated`。正文不存在時使用可用摘要，再沒有則為空字串。`content_truncated` 僅表示本地因每筆／總量上限截斷；API 也會依請求的每筆上限裁切，回傳 `false` 不代表取得了整頁所有內容。正文字元按 Unicode 計算，單次總量最多 60,000，按結果順序分配，超過總量的後續結果仍保留標題及網址。

`usage` 保留 API 回報的 token 用量，`log_id` 在可用時提供。擷取內容屬於外部資料，不能當成覆蓋使用者任務的指令。

## 錯誤與重試

每次 HTTP 請求最多 15 秒；整次搜尋最多 60 秒，包含重試等待。暫時性連線／傳輸失敗、逾時與 HTTP 500／502／503／504 最多重試兩次，等待時間逐次增加並加入隨機延遲。HTTP 400、401、403、429 不重試：分別檢查參數、金鑰／權限與帳戶額度。

錯誤使用 MCP `isError`，因此 SimpleAgent 的 `/dbg off` 模式仍可顯示失敗原因。HTTP 錯誤保留狀態碼與可用的 `log_id`；不將金鑰加入工具參數或錯誤訊息。沒有結果不會觸發重試，也不會自動呼叫 DuckDuckGo。

## 驗證

目前根目錄的 LangSearch 測試仍引用搬移前的模組路徑，須更新後才能直接執行。實際 API 驗證需要設定有效金鑰，再由 Agent 呼叫工具，確認取得來源網址與用量。
