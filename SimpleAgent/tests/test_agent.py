import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from simple_agent.agent import Agent
from simple_agent.config import Config
from simple_agent.skills import discover_skills


class Message:
    def __init__(self, content=None, calls=None):
        self.content = content
        self.tool_calls = calls

    def model_dump(self, exclude_none=True):
        data = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            data["tool_calls"] = [
                {"id": call.id, "type": "function", "function": {"name": call.function.name, "arguments": call.function.arguments}}
                for call in self.tool_calls
            ]
        return data


async def test_model_can_load_skill_and_call_mcp_before_reply():
    calls = [
        SimpleNamespace(id="1", function=SimpleNamespace(name="load_skill", arguments='{"name":"demo"}')),
        SimpleNamespace(id="2", function=SimpleNamespace(name="remote_tool", arguments='{"value": 7}')),
    ]
    completion = AsyncMock(side_effect=[
        SimpleNamespace(choices=[SimpleNamespace(message=Message(calls=calls))]),
        SimpleNamespace(choices=[SimpleNamespace(message=Message(content="finished"))]),
    ])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=completion)))
    mcp = SimpleNamespace(list_tools=AsyncMock(return_value=[]), call_tool=AsyncMock(return_value="result"))
    skill = SimpleNamespace(name="demo", description="test", load=lambda: "instructions")
    config = Config("test-model", None, "test-key", [], {})
    agent = Agent(config, {"demo": skill}, mcp, client=client)
    seen = []

    assert await agent.respond("hello", lambda name, args: seen.append((name, args))) == "finished"
    assert seen == [("load_skill", '{"name":"demo"}'), ("remote_tool", '{"value": 7}')]
    mcp.call_tool.assert_awaited_once_with("remote_tool", {"value": 7})
    sent = completion.await_args_list[1].kwargs["messages"]
    assert [message["content"] for message in sent if message["role"] == "tool"] == ["instructions", "result"]
    assert json.loads(sent[2]["tool_calls"][1]["function"]["arguments"]) == {"value": 7}
    assert agent.history[-1]["content"] == "finished"
    agent.clear()
    assert agent.history == []


async def test_skill_results_include_instructions_resource_and_errors(tmp_path):
    skill_dir = tmp_path / "demo"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nname: demo\ndescription: Test\n---\nFollow these steps.\n", encoding="utf-8")
    (skill_dir / "reference.md").write_text("Reference details.", encoding="utf-8")
    skills, _ = discover_skills([tmp_path])
    calls = [
        SimpleNamespace(id="1", function=SimpleNamespace(name="load_skill", arguments='{"name":"demo"}')),
        SimpleNamespace(id="2", function=SimpleNamespace(name="read_skill_resource", arguments='{"name":"demo","path":"reference.md"}')),
        SimpleNamespace(id="3", function=SimpleNamespace(name="read_skill_resource", arguments='{"name":"demo","path":"missing.md"}')),
        SimpleNamespace(id="4", function=SimpleNamespace(name="load_skill", arguments='{')),
        SimpleNamespace(id="5", function=SimpleNamespace(name="remote_tool", arguments='{}')),
    ]
    completion = AsyncMock(side_effect=[
        SimpleNamespace(choices=[SimpleNamespace(message=Message(calls=calls))]),
        SimpleNamespace(choices=[SimpleNamespace(message=Message(content="done"))]),
    ])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=completion)))
    mcp = SimpleNamespace(list_tools=AsyncMock(return_value=[]), call_tool=AsyncMock(return_value="remote result"))
    agent = Agent(Config("model", None, "test", [], {}), skills, mcp, client=client)
    shown = []
    assert await agent.respond("use skill", on_skill_result=lambda name, result: shown.append((name, result))) == "done"
    assert [name for name, _ in shown] == ["load_skill", "read_skill_resource", "read_skill_resource", "load_skill"]
    assert "Follow these steps." in shown[0][1] and str(skill_dir) in shown[0][1]
    assert shown[1][1] == "Reference details."
    assert shown[2][1].startswith("Tool error:") and "missing.md" in shown[2][1]
    assert shown[3][1].startswith("Tool error:")
    assert [message["content"] for message in agent.history if message["role"] == "tool"][:4] == [result for _, result in shown]


async def test_model_runs_skill_script_and_receives_output(tmp_path):
    skill_dir = tmp_path / "demo"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nname: demo\ndescription: A test skill\n---\nRun the script.\n", encoding="utf-8")
    (skill_dir / "run.py").write_text("import sys\nprint('hello ' + sys.argv[1])\n", encoding="utf-8")
    skills, _ = discover_skills([tmp_path])
    call = SimpleNamespace(id="1", function=SimpleNamespace(name="run_skill_script", arguments=json.dumps({"name": "demo", "path": "run.py", "args": ["world"]})))
    completion = AsyncMock(side_effect=[
        SimpleNamespace(choices=[SimpleNamespace(message=Message(calls=[call]))]),
        SimpleNamespace(choices=[SimpleNamespace(message=Message(content="done"))]),
    ])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=completion)))
    mcp = SimpleNamespace(list_tools=AsyncMock(return_value=[]))
    agent = Agent(Config("model", None, "test", [], {}), skills, mcp, client=client)
    confirm = AsyncMock(return_value=True)
    results = []

    assert await agent.respond("run", confirm_script=confirm, on_script_result=lambda *args: results.append(args)) == "done"
    confirm.assert_awaited_once_with("demo", "run.py", ["world"])
    result = json.loads(next(message["content"] for message in agent.history if message["role"] == "tool"))
    assert result["exit_code"] == 0
    assert result["stdout"].strip() == "hello world"
    assert results[0][0:2] == ("demo", "run.py")


async def test_denied_skill_script_does_not_run(tmp_path):
    skill_dir = tmp_path / "demo"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nname: demo\ndescription: A test skill\n---\n", encoding="utf-8")
    marker = skill_dir / "ran"
    (skill_dir / "run.py").write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\n", encoding="utf-8")
    skills, _ = discover_skills([tmp_path])
    agent = Agent(Config("model", None, "test", [], {}), skills, None, client=object())
    result = await agent._call_tool("run_skill_script", json.dumps({"name": "demo", "path": "run.py", "args": []}), AsyncMock(return_value=False))
    assert "denied" in result
    assert not marker.exists()


async def test_required_approval_without_interface_does_not_run(tmp_path):
    skill_dir = tmp_path / "demo"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nname: demo\ndescription: A test skill\n---\n", encoding="utf-8")
    marker = skill_dir / "ran"
    (skill_dir / "run.py").write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\n", encoding="utf-8")
    skills, _ = discover_skills([tmp_path])
    agent = Agent(Config("model", None, "test", [], {}, script_approval=True), skills, None, client=object())
    result = await agent._call_tool("run_skill_script", json.dumps({"name": "demo", "path": "run.py", "args": []}))
    assert "requires confirmation" in result
    assert not marker.exists()


async def test_tool_errors_are_reported_and_still_sent_to_model():
    calls = [
        SimpleNamespace(id="1", function=SimpleNamespace(name="load_skill", arguments='{"name":"missing"}')),
        SimpleNamespace(id="2", function=SimpleNamespace(name="remote_tool", arguments='{}')),
        SimpleNamespace(id="3", function=SimpleNamespace(name="successful_tool", arguments='{}')),
    ]
    completion = AsyncMock(side_effect=[
        SimpleNamespace(choices=[SimpleNamespace(message=Message(calls=calls))]),
        SimpleNamespace(choices=[SimpleNamespace(message=Message(content="done"))]),
    ])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=completion)))
    failure = json.dumps({"content": [{"type": "text", "text": "remote failure"}], "isError": True})
    success = json.dumps({"content": [{"type": "text", "text": "success"}], "isError": False})
    mcp = SimpleNamespace(list_tools=AsyncMock(return_value=[]), call_tool=AsyncMock(side_effect=[failure, success]))
    agent = Agent(Config("model", None, "test", [], {}), {}, mcp, client=client)
    errors = []

    assert await agent.respond("run", on_tool_error=lambda name, reason: errors.append((name, reason))) == "done"
    assert [name for name, _ in errors] == ["load_skill", "remote_tool"]
    assert "missing" in errors[0][1]
    assert "remote failure" in errors[1][1]
    sent = [message["content"] for message in agent.history if message["role"] == "tool"]
    assert sent[0].startswith("Tool error:")
    assert sent[1:] == [failure, success]


async def test_tool_error_fallback_and_skill_text_do_not_change_tool_results():
    calls = [
        SimpleNamespace(id="1", function=SimpleNamespace(name="load_skill", arguments='{"name":"demo"}')),
        SimpleNamespace(id="2", function=SimpleNamespace(name="empty_error", arguments='{}')),
        SimpleNamespace(id="3", function=SimpleNamespace(name="raises", arguments='{}')),
    ]
    completion = AsyncMock(side_effect=[
        SimpleNamespace(choices=[SimpleNamespace(message=Message(calls=calls))]),
        SimpleNamespace(choices=[SimpleNamespace(message=Message(content="done"))]),
    ])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=completion)))
    empty_failure = json.dumps({"content": [], "isError": True})
    mcp = SimpleNamespace(list_tools=AsyncMock(return_value=[]),
                          call_tool=AsyncMock(side_effect=[empty_failure, RuntimeError("disconnected")]))
    text = "Tool error: this is ordinary skill documentation"
    skill = SimpleNamespace(name="demo", description="test", load=lambda: text)
    agent = Agent(Config("model", None, "test", [], {}), {"demo": skill}, mcp, client=client)
    errors = []
    skills = []

    assert await agent.respond("run", on_tool_error=lambda name, reason: errors.append((name, reason)),
                               on_skill_result=lambda name, result: skills.append((name, result))) == "done"
    assert skills == [("load_skill", text)]
    assert [name for name, _ in errors] == ["empty_error", "raises"]
    assert errors[0][1]
    assert "disconnected" in errors[1][1]
    sent = [message["content"] for message in agent.history if message["role"] == "tool"]
    assert sent == [text, empty_failure, "Tool error: disconnected"]
