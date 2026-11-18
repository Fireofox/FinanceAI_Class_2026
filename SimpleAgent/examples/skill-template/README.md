# Skill 範例：整理待辦事項

`todo-organizer` 是可複製的 Agent Skill 範例，示範如何結合 Skill 指示、自訂 Python 工具和參考文件。

```text
todo-organizer/
├── SKILL.md                     # 何時使用及工具呼叫方式
├── scripts/
│   ├── format_todos.py          # 產生 Markdown 待辦清單
│   └── count_todos.py           # 統計待辦數量
└── references/
    └── format-guide.md          # 待辦清單的範例規則
```

兩個腳本只使用 Python 標準函式庫。它們是 Skill 附帶的 Python 腳本，由 SimpleAgent 的 `run_skill_script` 工具執行。

## 複製並啟用

從 SimpleAgent 專案目錄執行：

```powershell
if (Test-Path -LiteralPath 'skills/todo-organizer') {
    throw 'skills/todo-organizer 已存在，請先確認目的地。'
}
Copy-Item -LiteralPath 'examples/skill-template/todo-organizer' -Destination 'skills/todo-organizer' -Recurse
```

重新啟動 `uv run simple-agent`，即可請 Agent「使用 todo-organizer 整理回覆郵件和準備會議兩項待辦事項」。預設的 Skill 搜尋目錄也包含 `.agents/skills/`；若設定了其他 `skillDirs`，請複製到其中一個目錄。Skill 目錄名稱須與 `SKILL.md` 的 `name` 一致；若改名，請一併更新檔案中的名稱。

模型需支援工具呼叫。是否在執行腳本前確認，遵循 SimpleAgent 的 `scriptApproval` 設定；也可以在 TUI 輸入 `/script-approval on` 或 `/script-approval off` 切換。

## 獨立測試腳本

以下從 SimpleAgent 專案目錄執行，無需模型 API 金鑰：

```powershell
uv run python examples/skill-template/todo-organizer/scripts/format_todos.py --title '今日待辦' '回覆郵件' '準備會議'
uv run python examples/skill-template/todo-organizer/scripts/count_todos.py '回覆郵件' '準備會議'
```

第一個指令輸出：

```markdown
# 今日待辦

- [ ] 回覆郵件
- [ ] 準備會議
```

第二個指令輸出 `待辦事項數量：2`。每個待辦事項都是獨立的命令列參數；至少需要一項，空白項目會回報錯誤。

## 修改成自己的 Skill

1. 修改 `SKILL.md` 的 `name`、`description` 和步驟，說明何時使用及要讀取哪些參考文件。
2. 修改 `references/format-guide.md`，或新增自己的文件；在 `SKILL.md` 明確引用需要的檔案。
3. 修改或新增 `scripts/` 內的 Python 工具，並在 `SKILL.md` 說明相對於 Skill 目錄的腳本路徑與參數。
4. 以腳本的 `--help`、範例指令及 SimpleAgent 對話驗證結果。腳本工作目錄是**啟動 SimpleAgent 的目錄**；若腳本要讀取同一 Skill 內的檔案，可使用 `Path(__file__).resolve()` 定位，避免依賴目前工作目錄。

如自訂腳本需要第三方套件，請事先將套件安裝到**執行 SimpleAgent 的 Python 環境**。使用本專案的 uv 環境時，可從 SimpleAgent 專案目錄以 `uv add 套件名稱` 加入依賴；SimpleAgent 不會自動為 Skill 安裝套件。重新啟動程式後，確認腳本可在相同環境執行。
