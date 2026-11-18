# SimpleAgent 系統架構與處理流程

本文件依目前工作目錄中的實作整理，涵蓋 TUI、模型對話、Agent Skills、Skill Python 腳本及 MCP 工具。圖表使用 Mermaid。

## 系統架構

```mermaid
flowchart LR
    User["使用者"]

    subgraph Local["SimpleAgent（本機程序）"]
        Config["設定載入<br/>config.py"]
        TUI["Textual TUI<br/>app.py"]
        Agent["Agent 對話與工具路由<br/>agent.py"]
        History[("對話歷史<br/>記憶體")]
        Skills["Skills 探索與載入<br/>skills.py"]
        Runner["Python 腳本執行器<br/>script_runner.py"]
        MCP["MCP 連線與工具管理<br/>mcp_client.py"]
    end

    Settings["config.json<br/>環境變數"]
    Files["Skill 目錄<br/>SKILL.md、資源、.py 腳本"]
    Python["本機 Python 子程序"]
    Model["OpenAI 相容模型 API<br/>Chat Completions"]
    Servers["MCP 伺服器<br/>stdio / Streamable HTTP"]
    Search["DuckDuckGo MCP 伺服器<br/>Package/MCP/duckduckgo-mcp-server"]
    LangSearch["LangSearch MCP 伺服器<br/>Package/MCP/langsearch-mcp-server"]
    LangAPI["LangSearch Web Search API"]
    Web["DuckDuckGo 與公開網頁"]

    Settings --> Config --> TUI
    Config -. "模型、Skill、MCP 和腳本設定" .-> Agent
    User <-->|"輸入、回覆、確認"| TUI
    TUI <-->|"訊息、狀態、確認回呼"| Agent
    Agent <--> History
    Agent <-->|"提示、工具定義與結果"| Model
    TUI -->|"啟動時探索"| Skills
    Agent <-->|"載入指示與資源"| Skills
    Skills <-->|"讀取"| Files
    Agent <-->|"執行與結果"| Runner
    Runner -->|"驗證並啟動 .py"| Files
    Runner <-->|"參數、標準輸出與錯誤"| Python
    TUI -->|"建立與關閉連線"| MCP
    Agent <-->|"列舉與呼叫工具"| MCP
    MCP <-->|"工具呼叫與結果"| Servers
    MCP <-->|"stdio 工具呼叫與結果"| Search
    Search <-->|"搜尋與選用的 HTML 正文擷取"| Web
    MCP <-->|"stdio 工具呼叫與結果"| LangSearch
    LangSearch <-->|"Bearer 認證、搜尋及正文"| LangAPI
```

| 元件 | 職責 |
| --- | --- |
| [設定載入](../src/simple_agent/config.py) | 讀取 `config.json` 與環境變數，驗證腳本設定。 |
| [TUI](../src/simple_agent/app.py) | 以 Markdown 顯示 Agent 回覆，顯示對話、工具狀態與確認提示，處理 `/clear`、`/script-approval`、`/dbg` 等指令。 |
| [Agent](../src/simple_agent/agent.py) | 組合對話與工具定義、呼叫模型、依序執行工具，並維護記憶體中的歷史。 |
| [Skills](../src/simple_agent/skills.py) | 探索 `SKILL.md` 中繼資料，按需載入完整指示或 Skill 目錄內的文字資源。 |
| [腳本執行器](../src/simple_agent/script_runner.py) | 驗證 Skill 內的 `.py` 路徑，啟動 Python 子程序，收集有限輸出並處理逾時。 |
| [MCP 管理器](../src/simple_agent/mcp_client.py) | 建立 MCP 連線、依 envPassthrough 與 env 傳入 stdio 環境變數、探索工具、轉換工具定義並路由呼叫。 |

## 啟動流程

```mermaid
flowchart TD
    Start(["啟動 simple-agent"]) --> Read["讀取設定與環境變數"]
    Read --> Valid{"設定有效？"}
    Valid -- "否" --> ConfigError["顯示設定錯誤並結束"]
    Valid -- "是" --> App["啟動 Textual TUI 與 session worker"]
    App --> Discover["探索 Skill 中繼資料並顯示警告"]
    Discover --> Key{"有 API 金鑰？"}
    Key -- "否" --> MissingKey["顯示設定金鑰的提示"]
    Key -- "是" --> Connect["初始化所有設定的 MCP 連線"]
    Connect --> Connected{"連線成功？"}
    Connected -- "否" --> Error["顯示錯誤並清理已建立連線"]
    Connected -- "是" --> Create["建立 Agent 並取得 MCP 工具清單"]
    Create --> Ready["開放使用者輸入"]
    Ready --> Quit(["離開時關閉 MCP 連線"])
```

## 對話與工具處理流程

```mermaid
flowchart TD
    Input(["TUI 收到輸入"]) --> Command{"TUI 指令？"}
    Command -- "/clear" --> Clear["清除記憶體中的對話歷史"]
    Command -- "/script-approval on 或 off" --> Toggle["切換本次執行階段的確認設定"]
    Command -- "/dbg on 或 off" --> Debug["切換本次執行階段的工具與 Skill 呼叫細節"]
    Command -- "一般訊息" --> Prepare["組合系統提示、歷史、使用者訊息與工具定義"]
    Prepare --> Call["呼叫模型 Chat Completions"]
    Call --> ToolCalls{"模型要求工具呼叫？"}
    ToolCalls -- "否" --> Answer["保存歷史並在 TUI 顯示回覆"]
    ToolCalls -- "是" --> Route{"工具類型"}
    Route -- "load_skill" --> Load["讀取完整 SKILL.md"]
    Route -- "read_skill_resource" --> Resource["讀取 Skill 目錄內文字資源"]
    Route -- "run_skill_script" --> Script["確認設定與執行 Python 腳本"]
    Route -- "MCP 工具" --> Remote["經 MCP 管理器呼叫伺服器工具"]
    Load --> Result["逐一加入工具結果或錯誤訊息"]
    Resource --> Result
    Script --> Result
    Remote --> Result
    Result --> Limit{"已達本回合 12 次模型請求？"}
    Limit -- "否" --> Call
    Limit -- "是" --> Stop["保存歷史並提示已達上限"]
```

工具結果會加入對話，再交由模型決定是否繼續呼叫工具或產生回覆。同一則模型回覆若包含多個工具呼叫，Agent 會依序處理。若第 12 次模型請求仍要求工具，Agent 會執行工具並保存結果，但須等待下一次使用者輸入才再次呼叫模型。`/clear` 只清除目前程序記憶體中的對話歷史。

## Skill Python 腳本流程

```mermaid
flowchart TD
    Request(["模型呼叫 run_skill_script"]) --> Parse["解析參數並查找 Skill"]
    Parse --> Params{"Skill 與參數有效？"}
    Params -- "否" --> Invalid["將錯誤加入工具結果"]
    Params -- "是" --> Show["依 /dbg 狀態顯示 Skill、腳本及參數"]
    Show --> Approval{"已啟用執行確認？"}
    Approval -- "否，預設" --> Validate
    Approval -- "是" --> Ask["等待使用者輸入 y 或 n"]
    Ask --> Allow{"使用者允許？"}
    Allow -- "否" --> Denied["將拒絕訊息加入工具結果"]
    Allow -- "是" --> Validate["解析路徑並檢查檔案位於 Skill 目錄內且為 .py"]
    Validate --> Valid{"路徑有效？"}
    Valid -- "否" --> Invalid
    Valid -- "是" --> Run["使用目前 Python 環境啟動子程序"]
    Run --> Wait["收集 stdout 與 stderr，套用逾時與輸出上限"]
    Wait --> Result["回傳結束碼、輸出、逾時及截斷狀態"]
    Result --> Model["Agent 加入工具結果，視回合上限決定是否再次呼叫模型"]
    Denied --> Model
    Invalid --> Model
```

腳本工作目錄是啟動 SimpleAgent 的目錄，標準輸入關閉，且不經 shell。預設逾時 60 秒，標準輸出與錯誤輸出共用 32 KiB 上限，均可透過設定調整。腳本繼承本機使用者的權限與環境；路徑檢查並非沙箱。Windows 上若腳本先結束，其仍在執行的子程序可能無法自動終止。

MCP 工具與 Skill 腳本使用不同的執行路徑：腳本確認開關不適用於 MCP 工具。MCP 的 resources、prompts 與 OAuth 目前尚未實作。

## DuckDuckGo 搜尋流程

```mermaid
flowchart TD
    Call(["模型呼叫 MCP web_search"]) --> Search["使用 DuckDuckGo 搜尋"]
    Search --> Success{"搜尋成功？"}
    Success -- "否" --> Error["回報搜尋失敗"]
    Success -- "是" --> Site["依指定網域及子網域篩選結果"]
    Site --> Content{"需要正文？"}
    Content -- "否" --> Result["回傳標題、網址與摘要"]
    Content -- "是" --> Fetch["擷取各結果的 HTML 主要文字"]
    Fetch --> Limits["套用逾時與字元上限；逐筆標示擷取失敗或截斷"]
    Limits --> Result
    Result --> Agent["工具結果送回 Agent"]
```
