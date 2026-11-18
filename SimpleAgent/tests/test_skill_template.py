import shutil
from pathlib import Path

import pytest

from simple_agent.script_runner import run_skill_script
from simple_agent.skills import discover_skills


@pytest.fixture
def copied_skill(tmp_path):
    source = Path(__file__).resolve().parents[1] / "examples" / "skill-template" / "todo-organizer"
    skill_root = tmp_path / "skills"
    skill_root.mkdir()
    shutil.copytree(source, skill_root / "todo-organizer", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    skills, warnings = discover_skills([skill_root])
    assert not warnings
    assert list(skills) == ["todo-organizer"]
    return skills["todo-organizer"]


async def test_copied_skill_loads_references_and_executes_both_tools(copied_skill, tmp_path):
    instructions = copied_skill.load()
    assert "references/format-guide.md" in instructions
    assert "scripts/format_todos.py" in instructions
    assert "scripts/count_todos.py" in instructions
    guide = copied_skill.read_resource("references/format-guide.md")
    assert "- [ ]" in guide
    assert "待辦事項數量" in guide

    # Skill scripts run from the user's working directory rather than their own.
    formatted = await run_skill_script(
        copied_skill, "scripts/format_todos.py", ["--title", "今日任務", "整理文件", "傳送訊息"], cwd=tmp_path
    )
    assert formatted["exit_code"] == 0
    assert formatted["stdout"].splitlines() == ["# 今日任務", "", "- [ ] 整理文件", "- [ ] 傳送訊息"]
    assert not formatted["timed_out"] and not formatted["truncated"]

    counted = await run_skill_script(
        copied_skill, "scripts/count_todos.py", ["整理文件", "傳送訊息"], cwd=tmp_path
    )
    assert counted["exit_code"] == 0
    assert counted["stdout"].strip() == "待辦事項數量：2"


@pytest.mark.parametrize("script", ["format_todos.py", "count_todos.py"])
async def test_example_tools_reject_empty_tasks(copied_skill, tmp_path, script):
    result = await run_skill_script(copied_skill, f"scripts/{script}", ["   "], cwd=tmp_path)
    assert result["exit_code"] != 0
    assert result["stderr"]
