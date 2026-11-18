import sys
import asyncio

from simple_agent.app import SimpleAgentApp
from simple_agent.config import Config
from textual.widgets import Input, RichLog, Static


async def test_missing_api_key_is_explained():
    app = SimpleAgentApp(Config("model", None, "", [], {}))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "OPENAI_API_KEY" in str(app.query_one("#status", Static).render())
        assert app.query_one("#input", Input).disabled


async def test_agent_response_renders_markdown_and_other_messages_remain_literal(monkeypatch):
    answer = (
        "# 報告\n\n**重要**：結果如下\n\n- 第一項\n- 第二項\n\n"
        "```python\nprint('hello')\n```\n\n"
        "| 名稱 | 數值 |\n| --- | --- |\n| 台積電 | 10 |\n\n"
        "[資料來源](https://example.com/source)"
    )

    class FakeAgent:
        def __init__(self, *args):
            pass

        async def respond(self, text, on_tool, confirm_script, on_script_result, on_skill_result, on_tool_error):
            on_tool("search", '{"query":"**literal**"}')
            return answer

    monkeypatch.setattr("simple_agent.app.Agent", FakeAgent)
    app = SimpleAgentApp(Config("model", None, "fake-key", [], {}))
    async with app.run_test(size=(50, 30)) as pilot:
        for _ in range(100):
            if app.ready:
                break
            await pilot.pause(0.02)
        assert app.ready
        field = app.query_one("#input", Input)
        field.value = "**使用者輸入**"
        await field.action_submit()
        for _ in range(100):
            await pilot.pause(0.02)
            log = app.query_one("#chat", RichLog)
            rendered = "\n".join(line.text for line in log.lines)
            if "https://example.com/source" in rendered:
                break
        assert "**使用者輸入**" in rendered
        assert '"query": "**literal**"' in rendered
        assert "報告" in rendered and "# 報告" not in rendered
        assert "重要" in rendered and "**重要**" not in rendered
        assert "第一項" in rendered and "第二項" in rendered
        assert "print('hello')" in rendered and "```" not in rendered
        assert "台積電" in rendered and "數值" in rendered
        assert "資料來源" in rendered and "https://example.com/source" in rendered
        assert max(line.cell_length for line in log.lines) <= log.scrollable_content_region.width


async def test_stdio_server_starts_and_shuts_down_with_ui():
    server = 'from mcp.server.fastmcp import FastMCP; FastMCP("test").run(transport="stdio")'
    config = Config("model", None, "fake-key", [], {"test": {"command": sys.executable, "args": ["-c", server]}})
    app = SimpleAgentApp(config)
    async with app.run_test() as pilot:
        for _ in range(100):
            await pilot.pause(0.1)
            if app.ready:
                break
        assert app.ready
        assert not app.query_one("#input", Input).disabled


async def test_tool_call_displays_arguments_and_handles_invalid_json(monkeypatch):
    messages = []

    class FakeAgent:
        def __init__(self, *args):
            pass

        async def respond(self, text, on_tool, confirm_script, on_script_result, on_skill_result, on_tool_error):
            on_tool("search", '{"query":"台灣", "limit":2}')
            on_tool("broken", '{"query":')
            return "done"

    monkeypatch.setattr("simple_agent.app.Agent", FakeAgent)
    app = SimpleAgentApp(Config("model", None, "fake-key", [], {}))
    original_write = app.write_chat

    def capture(label, text):
        messages.append((label, text))
        original_write(label, text)

    monkeypatch.setattr(app, "write_chat", capture)
    async with app.run_test() as pilot:
        for _ in range(100):
            if app.ready:
                break
            await pilot.pause(0.02)
        assert app.ready
        field = app.query_one("#input", Input)
        field.value = "search"
        await field.action_submit()
        for _ in range(100):
            if any(label == "Agent" for label, _ in messages):
                break
            await pilot.pause(0.02)
        tools = [text for label, text in messages if label == "工具"]
        assert len(tools) == 2
        assert '"query": "台灣"' in tools[0] and '"limit": 2' in tools[0]
        assert '{"query":' in tools[1]


async def test_skill_instructions_and_reference_details_are_displayed(monkeypatch):
    messages = []

    class FakeAgent:
        def __init__(self, *args):
            pass

        async def respond(self, text, on_tool, confirm_script, on_script_result, on_skill_result, on_tool_error):
            on_tool("load_skill", '{"name":"demo"}')
            on_skill_result("load_skill", "Skill: demo\nSkill directory: /skills/demo\nInstructions")
            on_tool("read_skill_resource", '{"name":"demo","path":"refs/a.md"}')
            on_skill_result("read_skill_resource", "Reference content")
            return "done"

    monkeypatch.setattr("simple_agent.app.Agent", FakeAgent)
    app = SimpleAgentApp(Config("model", None, "fake-key", [], {}))
    original_write = app.write_chat

    def capture(label, text):
        messages.append((label, text))
        original_write(label, text)

    monkeypatch.setattr(app, "write_chat", capture)
    async with app.run_test() as pilot:
        for _ in range(100):
            if app.ready:
                break
            await pilot.pause(0.02)
        assert app.ready
        field = app.query_one("#input", Input)
        field.value = "use skill"
        await field.action_submit()
        for _ in range(100):
            if ("Agent", "done") in messages:
                break
            await pilot.pause(0.02)
        assert ("Skill 載入結果", "Skill: demo\nSkill directory: /skills/demo\nInstructions") in messages
        assert ("Skill 參考檔結果", "Reference content") in messages
        assert any(label == "工具" and '"path": "refs/a.md"' in text for label, text in messages)
        assert ("Agent", "done") in messages


async def test_approval_switch_and_prompts(monkeypatch):
    decisions = []

    class FakeAgent:
        def __init__(self, *args):
            pass

        def clear(self):
            pass

        async def respond(self, text, on_tool, confirm_script, on_script_result, on_skill_result, on_tool_error):
            allowed = await confirm_script("demo", "scripts/run.py", ["hello world"])
            decisions.append(allowed)
            if allowed:
                on_script_result("demo", "scripts/run.py", {"status": "completed", "exit_code": 0})
            return "done"

    monkeypatch.setattr("simple_agent.app.Agent", FakeAgent)
    config = Config("model", None, "fake-key", [], {})
    app = SimpleAgentApp(config)
    async with app.run_test() as pilot:
        for _ in range(30):
            await pilot.pause(0.05)
            if app.ready:
                break
        assert app.ready
        field = app.query_one("#input", Input)

        async def wait_until(predicate):
            for _ in range(100):
                if predicate():
                    return
                await pilot.pause(0.02)
            assert predicate(), "Timed out waiting for the UI state"

        async def submit(value):
            await wait_until(lambda: not field.disabled)
            field.value = value
            await field.action_submit()
            await wait_until(lambda: field.value == "")

        await submit("first")
        await wait_until(lambda: len(decisions) == 1 and not field.disabled)
        assert decisions == [True]  # Default is no confirmation.
        await submit("/script-approval on")
        await wait_until(lambda: app.script_approval)
        assert app.script_approval
        await submit("second")
        await wait_until(lambda: app._approval_future is not None)
        assert app._approval_future is not None
        assert not field.disabled
        await submit("maybe")
        assert app._approval_future is not None and not app._approval_future.done()
        await submit("n")
        await wait_until(lambda: len(decisions) == 2 and not field.disabled)
        assert decisions == [True, False]
        await submit("third")
        await wait_until(lambda: app._approval_future is not None)
        assert app._approval_future is not None
        await submit("/script-approval off")
        await wait_until(lambda: not app.script_approval)
        assert not app.script_approval
        assert app._approval_future is not None and not app._approval_future.done()
        await submit("y")
        await wait_until(lambda: len(decisions) == 3 and not field.disabled)
        assert decisions == [True, False, True]
        await submit("fourth")
        await wait_until(lambda: len(decisions) == 4)
        assert decisions == [True, False, True, True]
        assert config.script_approval is False  # Runtime setting was not persisted.


async def test_exiting_while_approval_is_pending_cancels_wait(monkeypatch):
    cancelled = asyncio.Event()

    class FakeAgent:
        def __init__(self, *args):
            pass

        async def respond(self, text, on_tool, confirm_script, on_script_result, on_skill_result, on_tool_error):
            try:
                await confirm_script("demo", "run.py", [])
            except asyncio.CancelledError:
                cancelled.set()
                raise

    monkeypatch.setattr("simple_agent.app.Agent", FakeAgent)
    app = SimpleAgentApp(Config("model", None, "fake-key", [], {}, script_approval=True))
    async with app.run_test() as pilot:
        for _ in range(30):
            await pilot.pause(0.05)
            if app.ready:
                break
        field = app.query_one("#input", Input)
        field.value = "start"
        await field.action_submit()
        await pilot.pause()
        assert app._approval_future is not None
    assert cancelled.is_set()


async def test_debug_switch_controls_diagnostics_but_keeps_errors(monkeypatch):
    messages = []
    cleared = []

    class FakeAgent:
        def __init__(self, *args):
            pass

        def clear(self):
            cleared.append(True)

        async def respond(self, text, on_tool, confirm_script, on_script_result, on_skill_result, on_tool_error):
            on_tool("load_skill", '{"name":"demo"}')
            on_skill_result("load_skill", "skill instructions")
            on_skill_result("read_skill_resource", "reference data")
            assert await confirm_script("demo", "run.py", [])
            on_script_result("demo", "run.py", {"exit_code": 0})
            if text == "with-errors":
                on_tool_error("remote_tool", "network failed")
                on_script_result("demo", "broken.py", {"exit_code": 1})
            return f"answer: {text}"

    monkeypatch.setattr("simple_agent.app.Agent", FakeAgent)
    app = SimpleAgentApp(Config("model", None, "fake-key", [], {}))
    original_write = app.write_chat

    def capture(label, text):
        messages.append((label, text))
        original_write(label, text)

    monkeypatch.setattr(app, "write_chat", capture)
    async with app.run_test() as pilot:
        async def wait_until(predicate):
            for _ in range(100):
                if predicate():
                    return
                await pilot.pause(0.02)
            assert predicate(), "Timed out waiting for the UI state"

        await wait_until(lambda: app.ready)
        field = app.query_one("#input", Input)

        async def submit(value):
            await wait_until(lambda: not field.disabled)
            field.value = value
            await field.action_submit()
            await wait_until(lambda: field.value == "")

        assert app.debug_enabled
        await submit("visible")
        await wait_until(lambda: ("Agent", "answer: visible") in messages)
        labels = [label for label, _ in messages]
        assert all(label in labels for label in ("工具", "Skill 載入結果", "Skill 參考檔結果", "執行 Python 腳本", "Python 腳本結果"))

        await submit("/DBG OFF")
        await wait_until(lambda: not app.debug_enabled)
        await submit("/dbg")
        await wait_until(lambda: any("/dbg" in text and label == "系統" for label, text in messages))
        await submit("/dbg invalid")
        await pilot.pause()
        assert not app.debug_enabled

        await submit("/clear")
        await wait_until(lambda: bool(cleared))
        assert not app.debug_enabled
        messages.clear()
        await submit("with-errors")
        await wait_until(lambda: ("Agent", "answer: with-errors") in messages)
        labels = [label for label, _ in messages]
        assert not any(label in labels for label in ("工具", "Skill 載入結果", "Skill 參考檔結果", "執行 Python 腳本"))
        assert any(label == "工具錯誤" and "remote_tool" in text and "network failed" in text for label, text in messages)
        script_results = [text for label, text in messages if label == "Python 腳本結果"]
        assert len(script_results) == 1 and "broken.py" in script_results[0] and "失敗" in script_results[0]

        await submit("/dbg on")
        await wait_until(lambda: app.debug_enabled)


async def test_debug_can_be_switched_while_script_approval_is_pending(monkeypatch):
    messages = []
    decisions = []

    class FakeAgent:
        def __init__(self, *args):
            pass

        async def respond(self, text, on_tool, confirm_script, on_script_result, on_skill_result, on_tool_error):
            decisions.append(await confirm_script("demo", "run.py", []))
            return "done"

    monkeypatch.setattr("simple_agent.app.Agent", FakeAgent)
    app = SimpleAgentApp(Config("model", None, "fake-key", [], {}, script_approval=True))
    original_write = app.write_chat

    def capture(label, text):
        messages.append((label, text))
        original_write(label, text)

    monkeypatch.setattr(app, "write_chat", capture)
    async with app.run_test() as pilot:
        async def wait_until(predicate):
            for _ in range(100):
                if predicate():
                    return
                await pilot.pause(0.02)
            assert predicate(), "Timed out waiting for the UI state"

        await wait_until(lambda: app.ready)
        field = app.query_one("#input", Input)

        async def submit(value):
            await wait_until(lambda: not field.disabled)
            field.value = value
            await field.action_submit()
            await wait_until(lambda: field.value == "")

        await submit("/dbg off")
        await wait_until(lambda: not app.debug_enabled)
        await submit("run")
        await wait_until(lambda: app._approval_future is not None)
        assert any(label == "腳本執行確認" and "run.py" in text for label, text in messages)
        await submit("/dbg on")
        await wait_until(lambda: app.debug_enabled)
        assert not app._approval_future.done()
        await submit("y")
        await wait_until(lambda: decisions == [True])
