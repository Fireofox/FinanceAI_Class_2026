import json
import shutil
import sys
from pathlib import Path

from simple_agent.mcp_client import MCPManager


async def test_copied_duckduckgo_server_over_stdio(tmp_path):
    """A copied example must expose its search tool without the project folder."""
    template = Path(__file__).resolve().parents[1] / "examples" / "MCP" / "duckduckgo-mcp-server"
    copied = tmp_path / "duckduckgo-server"
    shutil.copytree(template, copied, ignore=shutil.ignore_patterns(".venv", "__pycache__", "uv.lock"))
    assert (copied / "pyproject.toml").is_file()
    config = {"duckduckgo": {"command": sys.executable, "args": ["server.py"], "cwd": str(copied)}}

    async with MCPManager(config) as manager:
        tools = await manager.list_tools()
        assert len(tools) == 1
        function = tools[0]["function"]
        assert function["name"].startswith("duckduckgo__web_search_")
        properties = function["parameters"]["properties"]
        assert {"query", "site", "include_content", "max_results"} <= properties.keys()
        result = json.loads(await manager.call_tool(function["name"], {"query": " "}))
        assert not result.get("isError", False)
        output = result.get("structuredContent") or json.loads(result["content"][0]["text"])
        assert output["status"] == "error"
        assert "query" in output["error"].lower()


async def test_copied_duckduckgo_server_returns_requested_content(tmp_path):
    template = Path(__file__).resolve().parents[1] / "examples" / "MCP" / "duckduckgo-mcp-server"
    copied = tmp_path / "duckduckgo-server"
    shutil.copytree(template, copied, ignore=shutil.ignore_patterns(".venv", "__pycache__", "uv.lock"))
    (copied / "harness.py").write_text(
        'import server\n'
        'async def fake_search(query, **kwargs):\n'
        '    assert query == "python" and kwargs["site"] == "python.org"\n'
        '    return [{"title": "Python", "url": "https://python.org/", "body": "snippet"}]\n'
        'async def fake_fetch(url, **kwargs):\n'
        '    assert kwargs["allowed_domain"] == "python.org"\n'
        '    return {"content": "page content", "truncated": False}\n'
        'server.search = fake_search\n'
        'server.fetch_page = fake_fetch\n'
        'server.main()\n',
        encoding="utf-8",
    )
    config = {"duckduckgo": {"command": sys.executable, "args": ["harness.py"], "cwd": str(copied)}}
    async with MCPManager(config) as manager:
        tools = await manager.list_tools()
        result = json.loads(await manager.call_tool(
            tools[0]["function"]["name"], {"query": "python", "site": "python.org", "include_content": True}
        ))
        assert not result.get("isError", False)
        output = result.get("structuredContent") or json.loads(result["content"][0]["text"])
        assert output["status"] == "ok"
        assert output["results"][0]["content"] == "page content"
        assert output["results"][0]["content_truncated"] is False
