---
name: todo-organizer
description: Organize user-provided tasks into a Markdown checklist or count the tasks in a list.
---

# 整理待辦事項

使用者要求整理待辦清單或統計待辦數量時，使用本 Skill。只處理使用者提供的事項；若沒有事項，先請使用者提供。

1. 使用 `read_skill_resource` 讀取 `references/format-guide.md`，了解清單格式與範例。
2. 將每個待辦事項作為獨立字串，使用 `run_skill_script` 呼叫所需的 Python 腳本：
   - 產生清單：`name` 為 `todo-organizer`、`path` 為 `scripts/format_todos.py`、`args` 為事項字串陣列。可在事項之前加入 `--title` 和標題。
   - 統計數量：`name` 為 `todo-organizer`、`path` 為 `scripts/count_todos.py`、`args` 為相同的事項字串陣列。
3. 將腳本的標準輸出呈現給使用者；若腳本失敗，回報錯誤並依情況請使用者修正輸入。

腳本路徑相對於 Skill 目錄；每個參數都是 `args` 的獨立元素，不需透過 shell 組合命令。
