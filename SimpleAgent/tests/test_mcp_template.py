import json
import shutil
import sys
from pathlib import Path

from simple_agent.mcp_client import MCPManager


async def test_copied_template_discovers_and_calls_greet_over_stdio(tmp_path):
    template = Path(__file__).resolve().parents[1] / "examples" / "mcp-server-template"
    copied = tmp_path / "my-mcp-server"
    shutil.copytree(template, copied, ignore=shutil.ignore_patterns(".venv", "__pycache__", "uv.lock"))
    assert (copied / "pyproject.toml").is_file()
    config = {"example": {"command": sys.executable, "args": ["server.py"], "cwd": str(copied)}}

    async with MCPManager(config) as manager:
        tools = await manager.list_tools()
        assert len(tools) == 1
        function = tools[0]["function"]
        assert function["name"].startswith("example__greet_")
        assert "name" in function["parameters"]["properties"]
        result = json.loads(await manager.call_tool(function["name"], {"name": "世界"}))
        assert not result.get("isError", False)
        assert result["content"][0]["text"] == "Hello, 世界!"
        invalid = json.loads(await manager.call_tool(function["name"], {}))
        assert invalid["isError"] is True
