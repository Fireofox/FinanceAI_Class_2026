import asyncio
import json
import sys

from simple_agent import search_server
from simple_agent.mcp_client import MCPManager
from simple_agent.page_fetch import PageFetchError
from simple_agent.search_backend import SearchError


async def test_search_returns_results_and_passes_options(monkeypatch):
    async def fake_search(query, **kwargs):
        assert query == "python"
        assert kwargs["site"] == "python.org"
        assert kwargs["max_results"] == 2
        assert kwargs["region"] == "tw-tzh"
        assert kwargs["safesearch"] == "moderate"
        return [{"title": "Python", "url": "https://python.org/", "body": "Language"}]
    monkeypatch.setattr(search_server, "search", fake_search)
    response = await search_server.web_search("python", max_results=2, site="python.org")
    assert response["status"] == "ok"
    assert response["results"][0]["body"] == "Language"


async def test_page_errors_and_total_content_limit(monkeypatch):
    async def fake_search(query, **kwargs):
        return [{"title": str(i), "url": f"https://example.com/{i}", "body": "snippet"} for i in range(3)]
    async def fake_fetch(url, **kwargs):
        assert kwargs["allowed_domain"] == "example.com"
        if url.endswith("/1"):
            raise PageFetchError("Page returned HTTP 403")
        return {"content": "abcdef", "truncated": False}
    monkeypatch.setattr(search_server, "search", fake_search)
    monkeypatch.setattr(search_server, "fetch_page", fake_fetch)
    monkeypatch.setenv("SIMPLE_AGENT_TOTAL_CHAR_LIMIT", "8")
    response = await search_server.web_search("test", site="example.com", include_content=True)
    assert response["status"] == "partial"
    assert response["results"][0]["content"] == "abcdef"
    assert response["results"][1]["content_error"] == "Page returned HTTP 403"
    assert response["results"][2]["content"] == "ab"
    assert response["results"][2]["content_truncated"] is True


async def test_empty_search_error_and_total_timeout(monkeypatch):
    async def empty(query, **kwargs):
        return []
    monkeypatch.setattr(search_server, "search", empty)
    assert (await search_server.web_search("test"))["status"] == "empty"
    async def fail(query, **kwargs):
        raise SearchError("unavailable")
    monkeypatch.setattr(search_server, "search", fail)
    assert (await search_server.web_search("test"))["error"] == "unavailable"
    async def slow(query, **kwargs):
        await asyncio.sleep(1)
    monkeypatch.setattr(search_server, "search", slow)
    monkeypatch.setenv("SIMPLE_AGENT_TOTAL_TIMEOUT", "0.05")
    response = await search_server.web_search("test")
    assert response["status"] == "error" and "timed out" in response["error"]


async def test_total_timeout_preserves_completed_pages(monkeypatch):
    async def fake_search(query, **kwargs):
        return [{"title": str(i), "url": f"https://example.com/{i}", "body": "snippet"} for i in range(2)]
    async def fake_fetch(url, **kwargs):
        if url.endswith("/1"):
            await asyncio.sleep(1)
        return {"content": "finished", "truncated": False}
    monkeypatch.setattr(search_server, "search", fake_search)
    monkeypatch.setattr(search_server, "fetch_page", fake_fetch)
    monkeypatch.setenv("SIMPLE_AGENT_TOTAL_TIMEOUT", "0.05")
    response = await search_server.web_search("test", include_content=True)
    assert response["status"] == "partial"
    assert response["results"][0]["content"] == "finished"
    assert "time limit" in response["results"][1]["content_error"]


async def test_stdio_mcp_discovers_search_tool():
    config = {"search": {"command": sys.executable, "args": ["-m", "simple_agent.search_server"]}}
    async with MCPManager(config) as manager:
        tools = await manager.list_tools()
        assert len(tools) == 1
        assert tools[0]["function"]["name"].startswith("search__web_search_")
        result = json.loads(await manager.call_tool(tools[0]["function"]["name"], {"query": " "}))
        assert json.loads(result["content"][0]["text"])["status"] == "error"
