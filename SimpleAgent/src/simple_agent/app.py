"""Textual terminal interface."""

import asyncio
import json

from rich.console import Group
from rich.markdown import Markdown
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import Footer, Header, Input, RichLog, Static

from .agent import Agent
from .config import load_config
from .mcp_client import MCPManager
from .skills import discover_skills


class SimpleAgentApp(App):
    TITLE = "Simple Agent"
    CSS = """
    Screen { layout: vertical; }
    #status { height: auto; padding: 0 1; color: $text-muted; }
    #chat { height: 1fr; border: round $primary; padding: 0 1; }
    #input { dock: bottom; }
    """
    BINDINGS = [("ctrl+q", "quit", "離開")]

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.queue = asyncio.Queue()
        self.ready = False
        self.script_approval = config.script_approval
        self.debug_enabled = True
        self._approval_future = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            yield Static("正在啟動…", id="status")
            yield RichLog(id="chat", min_width=1, wrap=True, markup=False)
            yield Input(placeholder="輸入訊息；/clear；/dbg on|off；/script-approval on|off；Ctrl+Q 離開", id="input", disabled=True)
        yield Footer()

    def write_chat(self, label, text):
        if label == "Agent":
            # Show URLs in the text as terminal hyperlink support varies.
            content = Group(Text(label), Markdown(text, hyperlinks=False), Text(""))
        else:
            content = Text(f"{label}\n{text}\n")
        self.query_one("#chat", RichLog).write(content)

    def show_tool_call(self, name: str, arguments: str):
        if not self.debug_enabled:
            return
        try:
            formatted = json.dumps(json.loads(arguments), ensure_ascii=False, indent=2)
        except (ValueError, TypeError):
            formatted = arguments
        self.write_chat("工具", f"{name}\n參數：\n{formatted}")

    def show_skill_result(self, name: str, result: str):
        if not self.debug_enabled:
            return
        label = "Skill 載入結果" if name == "load_skill" else "Skill 參考檔結果"
        self.write_chat(label, result)

    def show_tool_error(self, name: str, reason: str):
        self.write_chat("工具錯誤", f"{name}\n{reason[:500]}{'…' if len(reason) > 500 else ''}")

    def on_mount(self):
        self.run_worker(self.session(), name="agent-session")

    def set_script_approval(self, text: str) -> bool:
        """Handle the runtime-only approval command; return whether it was a command."""
        parts = text.split()
        if not parts or parts[0].lower() != "/script-approval":
            return False
        if len(parts) != 2 or parts[1].lower() not in ("on", "off"):
            self.write_chat("系統", "用法：/script-approval on|off")
        else:
            self.script_approval = parts[1].lower() == "on"
            state = "開啟" if self.script_approval else "關閉"
            self.write_chat("系統", f"腳本執行確認已{state}（僅本次執行有效）。")
        return True

    def set_debug(self, text: str) -> bool:
        """Handle the runtime-only debug display command."""
        parts = text.split()
        if not parts or parts[0].lower() != "/dbg":
            return False
        if len(parts) == 1:
            state = "開啟" if self.debug_enabled else "關閉"
            self.write_chat("系統", f"工具與 Skill 呼叫顯示目前為{state}。用法：/dbg on|off")
        elif len(parts) == 2 and parts[1].lower() in ("on", "off"):
            self.debug_enabled = parts[1].lower() == "on"
            state = "開啟" if self.debug_enabled else "關閉"
            self.write_chat("系統", f"工具與 Skill 呼叫顯示已{state}（僅本次執行有效）。")
        else:
            self.write_chat("系統", "用法：/dbg on|off")
        return True

    async def confirm_script(self, skill_name: str, path: str, args: list[str]) -> bool:
        details = f"Skill: {skill_name}\n腳本: {path}\n參數: {json.dumps(args, ensure_ascii=False)}"
        if not self.script_approval:
            if self.debug_enabled:
                self.write_chat("執行 Python 腳本", details)
            return True

        field = self.query_one("#input", Input)
        future = asyncio.get_running_loop().create_future()
        self._approval_future = future
        self.write_chat("腳本執行確認", details + "\n允許執行？輸入 y 或 n。")
        field.disabled = False
        field.focus()
        try:
            return await future
        finally:
            self._approval_future = None
            field.disabled = True

    def on_script_result(self, skill_name: str, path: str, result: dict):
        exit_code = result.get("exit_code")
        status = "逾時" if result.get("timed_out") else ("成功" if exit_code == 0 else "失敗")
        if not self.debug_enabled and status == "成功":
            return
        truncated = "（輸出已截斷）" if result.get("truncated") else ""
        self.write_chat("Python 腳本結果", f"Skill: {skill_name}\n腳本: {path}\n狀態: {status}{truncated}\n結束碼: {exit_code}")

    async def session(self):
        skills, warnings = discover_skills(self.config.skill_dirs)
        for warning in warnings:
            self.write_chat("Skill 提示", warning)
        if not self.config.api_key:
            self.query_one("#status", Static).update("請設定 OPENAI_API_KEY 或 config.json 中的 apiKey 後重新啟動。")
            return
        manager = MCPManager(self.config.mcp_servers)
        try:
            await manager.connect()
            agent = Agent(self.config, skills, manager)
            self.query_one("#status", Static).update(
                f"模型：{self.config.model}  |  Skills：{len(skills)}  |  MCP 工具：{len(await manager.list_tools())}"
            )
            self.write_chat("歡迎", "輸入訊息開始對話。輸入 /clear 可清除對話。")
            self.ready = True
            field = self.query_one("#input", Input)
            field.disabled = False
            field.focus()
            while True:
                text = await self.queue.get()
                if text == "/clear":
                    agent.clear()
                    self.query_one("#chat", RichLog).clear()
                    self.write_chat("系統", "對話已清除。")
                elif self.set_script_approval(text) or self.set_debug(text):
                    continue
                else:
                    self.write_chat("你", text)
                    field.disabled = True
                    try:
                        answer = await agent.respond(text, self.show_tool_call,
                                                     confirm_script=self.confirm_script,
                                                     on_script_result=self.on_script_result,
                                                     on_skill_result=self.show_skill_result,
                                                     on_tool_error=self.show_tool_error)
                        self.write_chat("Agent", answer)
                    except Exception as exc:
                        self.write_chat("錯誤", str(exc))
                    finally:
                        field.disabled = False
                        field.focus()
        except Exception as exc:
            self.query_one("#status", Static).update("啟動失敗；請檢查設定後重新啟動。")
            self.write_chat("錯誤", str(exc))
        finally:
            self.ready = False
            await manager.aclose()

    def on_input_submitted(self, event: Input.Submitted):
        text = event.value.strip()
        if self.ready and text:
            event.input.value = ""
            if self._approval_future is not None:
                if self._approval_future.done():
                    return
                if self.set_script_approval(text) or self.set_debug(text):
                    self.write_chat("系統", "目前的執行仍需輸入 y 或 n 確認。")
                    return
                choice = text.lower()
                if choice in ("y", "yes", "允許"):
                    self._approval_future.set_result(True)
                elif choice in ("n", "no", "拒絕"):
                    self.write_chat("系統", "已拒絕執行腳本。")
                    self._approval_future.set_result(False)
                else:
                    self.write_chat("系統", "請輸入 y（允許）或 n（拒絕）。")
                return
            self.queue.put_nowait(text)


def main():
    try:
        config = load_config()
    except (OSError, ValueError) as exc:
        raise SystemExit(f"無法讀取設定：{exc}") from exc
    SimpleAgentApp(config).run()


if __name__ == "__main__":
    main()
