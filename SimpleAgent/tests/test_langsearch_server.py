import json
import sys

from simple_agent.mcp_client import MCPManager


async def test_stdio_discovery_and_missing_key_use_standard_mcp_error():
    config = {"langsearch": {"command": sys.executable, "args": ["-m", "simple_agent.langsearch_server"],
                             "env": {"LANGSEARCH_API_KEY": ""}}}
    async with MCPManager(config) as manager:
        tools = await manager.list_tools()
        assert len(tools) == 1
        function = tools[0]["function"]
        assert function["name"].startswith("langsearch__web_search_")
        fields = function["parameters"]["properties"]
        assert fields["max_results"]["maximum"] == 50
        assert fields["include_content"]["default"] is False
        assert fields["max_content_chars"]["maximum"] == 20000
        result = json.loads(await manager.call_tool(function["name"], {"query": "Python"}))
        assert result["isError"] is True
        assert "LANGSEARCH_API_KEY" in result["content"][0]["text"]


async def test_stdio_search_with_forwarded_key_and_mock_http(monkeypatch):
    code = '''
import json
import httpx
from simple_agent.langsearch_server import main
original_client = httpx.AsyncClient
def handle(request):
    assert request.headers["Authorization"] == "Bearer test-passed-key"
    body = json.loads(request.content)
    assert body["contents"] == {"text": {"maxCharacters": 100}}
    assert body["includeDomains"] == ["python.org"]
    assert body["freshness"] == "oneWeek"
    return httpx.Response(200, json={"data": {"webPages": {"value": [
        {"name": "Python", "url": "https://python.org", "text": "Source text"}
    ]}}, "usage": {"input_tokens": 1, "output_tokens": 2}})
def client(**kwargs):
    return original_client(transport=httpx.MockTransport(handle), **kwargs)
httpx.AsyncClient = client
main()
'''
    monkeypatch.setenv("LANGSEARCH_API_KEY", "test-passed-key")
    config = {"langsearch": {"command": sys.executable, "args": ["-c", code],
                             "envPassthrough": ["LANGSEARCH_API_KEY"]}}
    async with MCPManager(config) as manager:
        tools = await manager.list_tools()
        result = json.loads(await manager.call_tool(tools[0]["function"]["name"], {
            "query": "Python", "include_content": True, "max_content_chars": 100,
            "include_domains": ["python.org"], "freshness": "oneWeek",
        }))
    assert not result.get("isError", False)
    data = result.get("structuredContent") or json.loads(result["content"][0]["text"])
    assert data["status"] == "ok" and data["results"][0]["content"] == "Source text"
    assert data["results"][0]["url"] == "https://python.org"
    assert data["usage"] == {"input_tokens": 1, "output_tokens": 2}
