# Simple Agent

一個 Python 終端機 AI Agent：在 TUI 中對話，探索本機 [Agent Skills](https://agentskills.io/specification)，並連線至 [MCP](https://modelcontextprotocol.io/) 伺服器使用工具。

系統元件與處理流程請參考[系統架構與處理流程圖](docs/architecture.md)。

要建立自己的 MCP 工具伺服器，可複製 [MCP Server 範例](examples/mcp-server-template/README.md)並依說明修改。

也可參考可獨立執行的 [DuckDuckGo MCP Server](Package/MCP/duckduckgo-mcp-server/README.md)，了解搜尋及網頁正文擷取的實作。

若要讀寫指定目錄中的文字檔，可參考[檔案讀寫 MCP Server](Package/MCP/filesystem-mcp-server/README.md)。

如要建立自己的 Skill，可參考[待辦事項 Skill 範例](examples/skill-template/README.md)，其中包含 Python 工具和參考文件。

台股五項條件篩選可參考[巴菲特選股 Skill 範例](Package/Skills/buffett-stock-screen/README.md)。

## 快速開始

需要 Python 3.11 以上和 [uv](https://docs.astral.sh/uv/getting-started/installation/)。以下為 PowerShell：

```powershell
uv sync
$env:OPENAI_API_KEY = "你的 API 金鑰"
uv run simple-agent
```

輸入訊息後按 Enter 傳送；輸入 `/clear` 清除目前對話；按 Ctrl+Q 離開。對話只保存在記憶體中。也可用 `pip install -e .` 安裝後執行 `simple-agent`。

Agent 回覆會以 Markdown 顯示，支援標題、強調、清單、程式碼區塊、表格與連結；連結的網址也會顯示在文字中。使用者輸入及工具執行資訊以原文顯示。

使用 `/script-approval on` 啟用每次執行 Skill Python 腳本前的確認，或以 `/script-approval off` 關閉。此指令只影響目前執行階段；可在設定檔中設定啟動時的預設值。

使用 `/dbg off` 隱藏工具與 Skill 的一般呼叫細節，使用 `/dbg on` 重新顯示；輸入 `/dbg` 可查看目前狀態。預設為開啟，設定只在本次執行期間有效，`/clear` 不會改變此設定。關閉顯示時，錯誤和腳本執行確認仍會顯示；工具仍會正常執行並將結果提供給 Agent。

預設使用 `gpt-4.1-mini`，可透過 `OPENAI_MODEL` 或下方設定檔修改。支援以 `OPENAI_BASE_URL` 或 `baseUrl` 指定支援 Chat Completions 與 function calling 的相容 API 端點。API 金鑰可設定於 `OPENAI_API_KEY` 或設定檔的 `apiKey`；非空的環境變數優先。相容服務若不驗證金鑰，可提供任意非空字串。不同服務的工具呼叫相容性可能不同。

## 設定

在啟動目錄將 `config.example.json` 複製為 `config.json`，按需修改。未建立設定檔也可使用預設值。`config.json` 已列入 `.gitignore`。

```json
{
  "model": "gpt-4.1-mini",
  "baseUrl": "http://localhost:8000/v1",
  "apiKey": "你的 API 金鑰",
  "skillDirs": [".agents/skills", "skills"],
  "scriptApproval": false,
  "scriptTimeout": 60,
  "scriptOutputLimit": 32768,
  "mcpServers": {
    "system_clock": {
      "command": "uv",
      "args": ["run", "python", "server.py"],
      "cwd": "Package/MCP/system-mcp-server"
    },
    "duckduckgo": {
      "command": "uv",
      "args": ["run", "python", "server.py"],
      "cwd": "Package/MCP/duckduckgo-mcp-server"
    },
    "langsearch": {
      "command": "uv",
      "args": ["run", "python", "server.py"],
      "cwd": "Package/MCP/langsearch-mcp-server",
      "envPassthrough": ["LANGSEARCH_API_KEY"]
    },
    "local": {
      "command": "python",
      "args": ["path/to/server.py"],
      "env": {"EXAMPLE_TOKEN": "your-token"}
    },
    "remote": {
      "type": "http",
      "url": "http://localhost:8000/mcp",
      "headers": {"Authorization": "Bearer your-token"}
    }
  }
}
```

上例是設定格式，使用前請換成實際模型端點、金鑰與 MCP 伺服器；使用預設 OpenAI 端點時可省略 `baseUrl`。`command` 和 `args` 啟動 stdio 伺服器，亦可指定 `cwd`；`type: http` 使用 Streamable HTTP。啟動目錄中的相對路徑依目前工作目錄解析。伺服器啟動或連線失敗時，介面會顯示錯誤。MCP 工具會由模型自動呼叫，可能執行讀寫或其他操作，請只設定信任的伺服器。設定中的金鑰與 token 是明文，請妥善保護設定檔。

## 系統日期時間

專案的 [系統 MCP 伺服器](Package/MCP/system-mcp-server/README.md)提供 `get_system_datetime` 工具，讀取執行伺服器的主機之系統時鐘與本地時區。結果包含 ISO 8601 格式的 `local_datetime`、`utc_datetime`、`timezone_name` 和 `utc_offset`，不需要網路或 API 金鑰。

新的 `config.example.json` 已包含此伺服器。若已有 `config.json`，請將下列項目加入既有的 `mcpServers`，保留其他伺服器設定：

```json
"system_clock": {
  "command": "uv",
  "args": ["run", "python", "server.py"],
  "cwd": "Package/MCP/system-mcp-server"
}
```

在專案目錄執行 `uv sync` 後重新啟動 Simple Agent。伺服器的 `cwd` 須指向其目錄；若從其他目錄啟動，請調整為正確的相對或絕對路徑。首次由 `uv run` 啟動時會安裝伺服器自己的依賴。

## DuckDuckGo 網路搜尋

專案附帶使用 stdio 的 DuckDuckGo MCP 伺服器，提供 `web_search` 工具。將上方範例的 `mcpServers.duckduckgo` 區塊加入 `config.json`，填入模型設定後執行 `uv run simple-agent`。`cwd` 指向 `Package/MCP/duckduckgo-mcp-server`；若從其他目錄啟動，請改為正確的相對或絕對路徑。

模型可透過 `web_search` 搜尋 DuckDuckGo，結果包含標題、網址與摘要。預設回傳 5 筆，可指定 1 至 10 筆；預設地區為台灣、安全搜尋為適度，也可指定時間範圍。以 `site` 指定單一網域時，結果限制在該網域及其子網域。工具不需要搜尋 API 金鑰；DuckDuckGo 連線或搜尋失敗會回報錯誤。

`include_content` 預設關閉；開啟後，工具會嘗試擷取各結果的一般 HTML 網頁主要文字，正文讀取失敗時仍保留該筆標題、網址與摘要，並標示原因。動態產生的頁面、PDF 或需登入的內容可能無法擷取。每頁正文預設最多 20,000 字元，每次合計最多 60,000 字元，超過時會標示截斷。

可在 `mcpServers.duckduckgo.env` 調整以下環境變數，重新啟動 Simple Agent 後生效：

| 環境變數 | 預設值 | 用途 |
| --- | ---: | --- |
| `SIMPLE_AGENT_SEARCH_TIMEOUT` | `15` | 搜尋逾時秒數 |
| `SIMPLE_AGENT_PAGE_TIMEOUT` | `10` | 單一網頁下載逾時秒數 |
| `SIMPLE_AGENT_TOTAL_TIMEOUT` | `60` | 每次工具呼叫的整體逾時秒數 |
| `SIMPLE_AGENT_PAGE_CHAR_LIMIT` | `20000` | 每頁正文最多字元數 |
| `SIMPLE_AGENT_TOTAL_CHAR_LIMIT` | `60000` | 每次回傳正文的總字元上限 |

## LangSearch 網路搜尋

專案附帶的 LangSearch stdio MCP Server 提供另一個 `web_search` 工具，可與 DuckDuckGo 並存。支援搜尋摘要、選用的網頁正文、日期篩選、包含／排除網域清單，並回傳來源網址及 token 用量。

在專案目錄執行 `uv sync`，將上方 `mcpServers.langsearch` 區塊加入既有的 `config.json`，並在啟動 Simple Agent 的 PowerShell 設定金鑰：

```powershell
$env:LANGSEARCH_API_KEY = "你的 LangSearch API 金鑰"
uv run simple-agent
```

若要直接在 `config.json` 填入金鑰，可將該伺服器的 `envPassthrough` 改為 `"env": {"LANGSEARCH_API_KEY": "你的 LangSearch API 金鑰"}`。`envPassthrough` 明確列出要傳入 MCP 子程序的環境變數；`env` 的同名設定優先。金鑰在呼叫時檢查，未設定時仍可啟動及探索工具。

預設回傳 5 筆摘要，最多 50 筆；正文預設每筆 5,000 字元，可調至最多 20,000，每次正文總量最多 60,000。失敗以標準 MCP 錯誤回報，因此 `/dbg off` 時仍會顯示。完整參數、設定與回傳範例請參考 [LangSearch 使用說明](docs/langsearch.md)。

## Skills

預設依序搜尋啟動目錄下的 `.agents/skills/` 和 `skills/`。每個 skill 應放在自己的目錄，並含有帶 YAML frontmatter 的 `SKILL.md`，例如 `skills/example/SKILL.md`。重名時以較早搜尋路徑為準。啟動時讀取名稱與描述，模型選用後才讀取完整指示，也可讀取該 skill 目錄內的文字參考檔案。

預設情況下，TUI 會顯示工具名稱及呼叫參數；載入 Skill 或讀取參考檔時，也會顯示實際載入的內容或錯誤。可使用 `/dbg off` 隱藏一般呼叫細節。

模型可依 Skill 指示執行該 Skill 目錄內的 `.py` 腳本，並提供參數。程式使用執行 Simple Agent 的 Python 環境，不自動安裝套件；工作目錄是啟動 Simple Agent 的目錄。腳本不經 shell 執行，標準輸入關閉，並回傳結束狀態、標準輸出及錯誤輸出。

`scriptApproval` 預設為 `false`，設為 `true` 時每次執行前須在 TUI 確認。`scriptTimeout` 是逾時秒數，預設 60；`scriptOutputLimit` 是回傳輸出上限的位元組數，預設 32768；輸出超過上限會截斷並註明。逾時或離開程式時會終止執行中的腳本。

Windows 上，若腳本先結束而它啟動的子程序仍在執行，這些子程序可能無法被自動終止。

腳本在本機執行，繼承目前使用者的系統權限和環境變數，可存取使用者能存取的檔案、網路及金鑰。限制腳本所在路徑不是沙箱；請只使用信任的 Skill，並依需要啟用執行確認。

此版本支援 MCP 的工具探索和呼叫，尚未實作 MCP resources、prompts、OAuth 或 MCP 工具的互動式確認。

## 開發與測試

```powershell
uv sync --extra dev
uv run pytest
```

目前部分測試仍引用搬移前的 `examples/` 或 `src/simple_agent/` 路徑，完整測試會在收集階段失敗；須先更新這些測試路徑。
