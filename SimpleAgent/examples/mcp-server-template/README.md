# MCP Server 範例

此目錄是可獨立複製的 Python MCP Server。它使用標準輸入／輸出（stdio），提供一個可直接呼叫的 `greet` 工具；複製後修改 [server.py](server.py) 即可建立自己的伺服器。

## 複製與安裝

需要 Python 3.11 以上和 [uv](https://docs.astral.sh/uv/getting-started/installation/)。以下從 SimpleAgent 專案目錄以 PowerShell 執行：

```powershell
New-Item -ItemType Directory -Path ../my-mcp-server -ErrorAction Stop
Copy-Item examples/mcp-server-template/server.py, examples/mcp-server-template/verify.py, examples/mcp-server-template/pyproject.toml, examples/mcp-server-template/README.md -Destination ../my-mcp-server
Set-Location ../my-mcp-server
uv sync
```

範例包含自己的 `pyproject.toml`，可以複製到其他目錄或專案。若目標目錄已存在，請選用另一個名稱。

## 執行與驗證

在複製後的伺服器目錄執行：

```powershell
uv run python verify.py
```

驗證程式會啟動伺服器，透過 MCP 列出工具並以 `name=World` 呼叫 `greet`。預期結果為 `Hello, World!`；不需要模型 API 金鑰。

也可直接啟動伺服器：

```powershell
uv run python server.py
```

伺服器會等待 MCP 用戶端透過標準輸入／輸出連線；此時不會出現一般命令列提示。可按 Ctrl+C 結束。請將除錯訊息寫到標準錯誤，避免干擾 stdio 通訊。

## 填入自己的功能

1. 修改 `server.py` 中的伺服器名稱。
2. 將 `greet` 的函式名稱、型別標註、說明文字及函式內容改成實際功能。MCP 會使用函式名稱、參數與說明產生工具定義；請讓說明清楚描述用途。
3. 參考檔案中的註解範本，以另一個 `@mcp.tool()` 函式新增工具。需要其他 Python 套件時，將依賴加入此目錄的 `pyproject.toml`，再執行 `uv sync`。
4. 修改 `verify.py` 以測試新工具；保留 `greet` 時也可先執行原有驗證。

## 連接 SimpleAgent

回到 SimpleAgent 的啟動目錄，在既有 `config.json` 的 `mcpServers` 物件中新增：

```json
"my_server": {
  "command": "uv",
  "args": ["run", "python", "server.py"],
  "cwd": "../my-mcp-server"
}
```

請依實際位置修改 `cwd`；相對路徑相對於啟動 SimpleAgent 的工作目錄。若有其他伺服器，保留原有項目並用逗號分隔。也可使用絕對路徑；Windows JSON 路徑可用正斜線，例如 `C:/Work/Source/my-mcp-server`。

啟動 `uv run simple-agent` 後，畫面會顯示 MCP 工具數量。輸入「使用 my_server 的 greet 工具，名稱是 World」即可請模型嘗試呼叫。模型和 API 必須支援工具呼叫。

需要環境變數時，可在上述伺服器設定中加入 `"env": {"MY_VARIABLE": "value"}`。具體設定與金鑰應放在被 Git 忽略的 `config.json`，不要寫進範例程式。
