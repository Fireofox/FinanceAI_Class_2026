import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from simple_agent.script_runner import resolve_skill_script, run_skill_script


@pytest.fixture
def skill(tmp_path):
    root = tmp_path / "sample"
    root.mkdir()
    path = root / "SKILL.md"
    path.write_text("---\nname: sample\ndescription: sample\n---\n", encoding="utf-8")
    return SimpleNamespace(path=path)


async def test_script_receives_literal_args_cwd_environment_and_closed_stdin(skill, tmp_path, monkeypatch):
    script = skill.path.parent / "run.py"
    script.write_text(
        "import json, os, sys\n"
        "print(json.dumps({'args': sys.argv[1:], 'cwd': os.getcwd(), "
        "'env': os.environ['SKILL_RUNNER_TEST'], 'stdin': sys.stdin.read()}))\n"
        "print('error output', file=sys.stderr)\n", encoding="utf-8")
    monkeypatch.setenv("SKILL_RUNNER_TEST", "present")
    result = await run_skill_script(skill, "run.py", ["hello world", "; echo no shell"], cwd=tmp_path)
    import json
    payload = json.loads(result["stdout"])
    assert payload == {"args": ["hello world", "; echo no shell"], "cwd": str(tmp_path), "env": "present", "stdin": ""}
    assert "error output" in result["stderr"]
    assert result["exit_code"] == 0
    assert not result["timed_out"] and not result["truncated"]


async def test_output_is_bounded_without_blocking_process(skill):
    (skill.path.parent / "run.py").write_text(
        "import sys\nsys.stdout.write('x'*100000)\nsys.stderr.write('y'*100000)\n", encoding="utf-8")
    result = await run_skill_script(skill, "run.py", [], output_limit=1024)
    assert result["exit_code"] == 0
    assert result["truncated"]
    assert len((result["stdout"] + result["stderr"]).encode()) == 1024


async def test_chinese_output_round_trips(skill, monkeypatch):
    monkeypatch.delenv("PYTHONIOENCODING", raising=False)
    (skill.path.parent / "run.py").write_text("print('你好，世界')\n", encoding="utf-8")
    result = await run_skill_script(skill, "run.py", [])
    assert result["stdout"].strip() == "你好，世界"


async def test_timeout_kills_script_and_keeps_partial_output(skill):
    (skill.path.parent / "run.py").write_text(
        "import time\nprint('started', flush=True)\ntime.sleep(30)\n", encoding="utf-8")
    result = await run_skill_script(skill, "run.py", [], timeout=1)
    assert result["timed_out"]
    assert result["exit_code"] != 0
    assert "started" in result["stdout"]


async def test_cancellation_stops_script(skill, tmp_path):
    marker = tmp_path / "finished"
    (skill.path.parent / "run.py").write_text(
        "import sys, time\ntime.sleep(2)\nopen(sys.argv[1], 'w').write('finished')\n", encoding="utf-8")
    task = asyncio.create_task(run_skill_script(skill, "run.py", [str(marker)]))
    await asyncio.sleep(0.3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(2)
    assert not marker.exists()


async def test_timeout_returns_if_exited_script_left_inherited_pipes_open(skill):
    (skill.path.parent / "run.py").write_text(
        "import subprocess, sys\n"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(3)'])\n",
        encoding="utf-8",
    )
    result = await asyncio.wait_for(run_skill_script(skill, "run.py", [], timeout=0.5), 2)
    assert result["timed_out"]


def test_script_path_must_resolve_to_python_file_inside_skill(skill, tmp_path):
    external = tmp_path / "outside.py"
    external.write_text("pass", encoding="utf-8")
    internal = skill.path.parent / "inside.py"
    internal.write_text("pass", encoding="utf-8")
    assert resolve_skill_script(skill, "inside.py") == internal.resolve()
    for value in ("../outside.py", str(external), "SKILL.md", "missing.py"):
        with pytest.raises(ValueError):
            resolve_skill_script(skill, value)
    link = skill.path.parent / "link.py"
    try:
        os.symlink(external, link)
    except OSError:
        return  # Windows may prohibit unprivileged symlink creation.
    with pytest.raises(ValueError):
        resolve_skill_script(skill, "link.py")
