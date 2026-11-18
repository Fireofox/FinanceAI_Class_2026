# 系統日期時間 MCP Server

這個獨立的 stdio MCP Server 提供 `get_system_datetime` 工具，讀取伺服器所在主機的系統時鐘與本地時區。它不需要網路搜尋服務或 API 金鑰。

## 安裝與驗證

需要 Python 3.11 以上和 [uv](https://docs.astral.sh/uv/getting-started/installation/)。從 SimpleAgent 專案目錄執行：

```powershell
Set-Location Package/MCP/system-mcp-server
uv sync
uv run python verify.py
```

驗證程式啟動 `server.py`，透過 MCP stdio 探索並呼叫 `get_system_datetime`，檢查本地與 UTC 時間是否為同一時刻，且落在呼叫時間範圍內。也可使用 `uv run python server.py` 直接啟動；伺服器會等待 MCP 用戶端透過標準輸入／輸出連線。

## 連接 SimpleAgent

從 SimpleAgent 專案目錄啟動時，將下列項目加入 `config.json` 的 `mcpServers`；`config.example.json` 已提供此設定：

```json
"system_clock": {
  "command": "uv",
  "args": ["run", "python", "server.py"],
  "cwd": "Package/MCP/system-mcp-server"
}
```

`cwd` 相對於 SimpleAgent 的啟動目錄；若從其他目錄啟動，請調整為正確的相對或絕對路徑。`uv run` 會使用伺服器目錄的 `pyproject.toml` 安裝並執行其依賴。

## 回傳值

`get_system_datetime` 不需要參數，回傳以下欄位：

| 欄位 | 內容 |
| --- | --- |
| `local_datetime` | 附本地 UTC 偏移的 ISO 8601 日期時間 |
| `utc_datetime` | 同一時刻的 UTC ISO 8601 日期時間 |
| `timezone_name` | 主機的本地時區名稱 |
| `utc_offset` | 本地時區與 UTC 的偏移量 |

如果想在其他位置使用，可複製本目錄的 `server.py`、`verify.py` 和 `pyproject.toml`，再將 SimpleAgent 的 `cwd` 改為新目錄。
