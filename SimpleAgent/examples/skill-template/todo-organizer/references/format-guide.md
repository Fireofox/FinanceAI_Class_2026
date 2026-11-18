# 待辦清單格式參考

本文件示範可隨 Skill 自訂的業務規則。整理使用者提供的待辦事項時：

- 依使用者提供的順序列出事項，不自行新增事項或判定完成狀態。
- 清單以 Markdown 標題開頭，每個事項使用未完成的核取方塊 `- [ ]`。
- 需要統計時，統計輸入的事項數量；每個命令列參數代表一個事項。

## 範例

使用 `run_skill_script` 產生清單：

```json
{
  "name": "todo-organizer",
  "path": "scripts/format_todos.py",
  "args": ["--title", "今日待辦", "回覆郵件", "準備會議"]
}
```

預期標準輸出：

```markdown
# 今日待辦

- [ ] 回覆郵件
- [ ] 準備會議
```

使用 `run_skill_script` 統計相同事項：

```json
{
  "name": "todo-organizer",
  "path": "scripts/count_todos.py",
  "args": ["回覆郵件", "準備會議"]
}
```

預期標準輸出為 `待辦事項數量：2`。兩個腳本均需至少一個非空事項。自訂 Skill 時可修改此參考文件，並同步調整腳本與 `SKILL.md` 的指示。
