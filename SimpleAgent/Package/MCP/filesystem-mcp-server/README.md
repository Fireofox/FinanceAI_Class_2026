# 檔案讀寫 MCP Server 範例

這個可獨立複製的 Python MCP Server 使用 stdio 提供 `read_file` 和 `write_file` 工具，示範如何讓 SimpleAgent 在指定工作目錄內讀寫 UTF-8 文字檔。

## 複製與安裝

需要 Python 3.11 以上及 [uv](https://docs.astral.sh/uv/getting-started/installation/)。從 SimpleAgent 專案目錄使用 PowerShell：

```powershell
New-Item -ItemType Directory -Path ../my-filesystem-server -ErrorAction Stop
Copy-Item Package/MCP/filesystem-mcp-server/server.py, Package/MCP/filesystem-mcp-server/verify.py, Package/MCP/filesystem-mcp-server/pyproject.toml, Package/MCP/filesystem-mcp-server/README.md -Destination ../my-filesystem-server
Set-Location ../my-filesystem-server
uv sync
```

範例包含獨立的 `pyproject.toml`，可複製到其他目錄；上述步驟只複製必要檔案。若目標已存在，請使用另一個名稱。

## 執行與驗證

```powershell
uv run python verify.py
```

驗證程式會以暫存工作目錄啟動伺服器，透過 MCP 測試工具探索、檔案寫入、讀取與預設的覆寫限制，不需要模型 API 金鑰。

也可直接執行 `uv run python server.py`。伺服器會等待 MCP 用戶端透過標準輸入／輸出連線；可按 Ctrl+C 結束。請將除錯訊息寫入標準錯誤，讓標準輸出維持 MCP 通訊用途。

## 工具與存取範圍

- `read_file(path)`：以 UTF-8 讀取文字，成功時回傳狀態、相對路徑、內容及位元組數。
- `write_file(path, content, overwrite=false)`：以 UTF-8 建立文字檔，成功時回傳狀態、路徑、位元組數及 `created` 或 `overwritten`。既有檔案須明確指定 `overwrite=true` 才可覆寫；上層目錄必須已存在。

`path` 是相對於工作目錄的路徑，例如 `notes/example.txt`。工作目錄可由 `FILE_MCP_ROOT` 指定，預設為伺服器啟動目錄；該目錄必須已存在。伺服器拒絕絕對路徑、目錄外路徑，以及經過符號連結或 Windows junction 等 reparse point 的路徑。

每次讀寫預設上限為 1 MiB（1,048,576 位元組）；可使用 `FILE_MCP_MAX_BYTES` 設定正整數位元組上限。超出上限、內容不是有效 UTF-8、檔案或上層目錄不存在，以及其他存取失敗時，工具會回傳錯誤狀態和原因。

## 連接 SimpleAgent

回到 SimpleAgent 的啟動目錄，在既有 `config.json` 的 `mcpServers` 物件中新增：

```json
"my_files": {
  "command": "uv",
  "args": ["run", "python", "server.py"],
  "cwd": "../my-filesystem-server",
  "env": {
    "FILE_MCP_ROOT": "C:/Work/Source/my-files",
    "FILE_MCP_MAX_BYTES": "1048576"
  }
}
```

請將 `cwd` 改為複製後的伺服器目錄，並將 `FILE_MCP_ROOT` 改為實際存在、允許讀寫的目錄。`cwd` 的相對路徑以啟動 SimpleAgent 的工作目錄為準；如省略 `FILE_MCP_ROOT`，伺服器以 `cwd` 為工作目錄。Windows JSON 路徑可使用正斜線。若已有其他伺服器，保留原有項目並以逗號分隔。

重新啟動 SimpleAgent 後，可請模型使用 `my_files` 的讀寫工具。模型 API 須支援工具呼叫。目前 MCP 工具由模型選用後直接執行，`scriptApproval` 不適用；請選擇適合授權的工作目錄。
