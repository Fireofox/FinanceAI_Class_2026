"""Model conversation and tool execution."""

import json
from collections.abc import Callable

from openai import AsyncOpenAI

from .script_runner import run_skill_script


def skill_tools():
    def tool(name, description, properties, required):
        return {"type": "function", "function": {"name": name, "description": description,
                "parameters": {"type": "object", "properties": properties, "required": required}}}
    return [
        tool("load_skill", "Read the full instructions of an available skill before following it.",
             {"name": {"type": "string", "description": "Skill name"}}, ["name"]),
        tool("read_skill_resource", "Read a text file relative to a skill directory.",
             {"name": {"type": "string", "description": "Skill name"},
              "path": {"type": "string", "description": "Relative file path"}}, ["name", "path"]),
        tool("run_skill_script", "Run a Python script inside an available skill. Load the skill first.",
             {"name": {"type": "string", "description": "Skill name"},
              "path": {"type": "string", "description": "Python script path relative to the skill directory"},
              "args": {"type": "array", "items": {"type": "string"}, "description": "Command-line arguments"}},
             ["name", "path", "args"]),
    ]


class Agent:
    def __init__(self, config, skills, mcp, client=None):
        self.config, self.skills, self.mcp = config, skills, mcp
        self.client = client or AsyncOpenAI(api_key=config.api_key, base_url=config.base_url)
        self.history = []

    def clear(self):
        self.history.clear()

    async def _call_tool(self, name, arguments, confirm_script=None, on_script_result=None,
                         on_tool_error=None):
        try:
            args = json.loads(arguments)
            if not isinstance(args, dict):
                raise ValueError("Tool arguments must be a JSON object")
            if name in ("load_skill", "read_skill_resource"):
                skill = self.skills[args["name"]]
                return skill.load() if name == "load_skill" else skill.read_resource(args["path"])
            if name == "run_skill_script":
                skill = self.skills[args["name"]]
                path, script_args = args["path"], args["args"]
                if not isinstance(path, str) or not isinstance(script_args, list) or not all(isinstance(arg, str) for arg in script_args):
                    raise ValueError("Script path must be a string and args must be a list of strings")
                if confirm_script is None:
                    if self.config.script_approval:
                        raise ValueError("script execution requires confirmation, but no confirmation interface is available.")
                elif not await confirm_script(skill.name, path, script_args):
                    return "Script execution was denied by the user."
                result = await run_skill_script(skill, path, script_args,
                                                timeout=self.config.script_timeout,
                                                output_limit=self.config.script_output_limit)
                if on_script_result:
                    on_script_result(skill.name, path, result)
                return json.dumps(result, ensure_ascii=False)
            result = await self.mcp.call_tool(name, args)
        except Exception as exc:
            if on_tool_error:
                on_tool_error(name, (str(exc).strip() or type(exc).__name__)[:500])
            return f"Tool error: {exc}"

        # MCP results have a standard error flag. Skill contents may be arbitrary
        # text, so only inspect the result of an actual MCP call here.
        if on_tool_error:
            try:
                payload = json.loads(result)
            except (TypeError, ValueError):
                payload = None
            if isinstance(payload, dict) and payload.get("isError") is True:
                content = payload.get("content")
                error = ""
                if isinstance(content, list):
                    error = next((part["text"].strip() for part in content
                                  if isinstance(part, dict) and isinstance(part.get("text"), str)
                                  and part["text"].strip()), "")
                on_tool_error(name, (error or "MCP tool error")[:500])
        return result

    async def respond(self, text: str, on_tool: Callable[[str, str], None] = lambda _name, _arguments: None,
                      confirm_script=None, on_script_result=None, on_skill_result=None,
                      on_tool_error=None) -> str:
        listing = "\n".join(f"- {s.name}: {s.description}" for s in self.skills.values()) or "(none)"
        system = ("You are a helpful assistant. Use available tools when useful. "
                  "Skills are optional instructions; call load_skill before following one, and "
                  "read_skill_resource for referenced text files, and run_skill_script to run "
                  "Python scripts within a skill when needed. Available skills:\n" + listing)
        tools = skill_tools() + await self.mcp.list_tools()
        messages = [{"role": "system", "content": system}, *self.history, {"role": "user", "content": text}]
        for _ in range(12):
            response = await self.client.chat.completions.create(model=self.config.model, messages=messages, tools=tools)
            message = response.choices[0].message
            messages.append(message.model_dump(exclude_none=True))
            if not message.tool_calls:
                self.history = messages[1:]
                return message.content or "（模型沒有回傳文字。）"
            for call in message.tool_calls:
                name = call.function.name
                on_tool(name, call.function.arguments)
                error_reported = False

                def report_error(tool_name, error):
                    nonlocal error_reported
                    error_reported = True
                    on_tool_error(tool_name, error)

                result = await self._call_tool(name, call.function.arguments, confirm_script, on_script_result,
                                               report_error if on_tool_error else None)
                if name in ("load_skill", "read_skill_resource") and on_skill_result and not error_reported:
                    on_skill_result(name, result)
                messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
        self.history = messages[1:]
        return "已達本回合工具呼叫次數上限，請再輸入訊息繼續。"
