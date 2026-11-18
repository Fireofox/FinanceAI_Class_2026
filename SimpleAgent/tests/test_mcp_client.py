import json
import os
import asyncio
import socket
import subprocess
import sys
import unittest
import warnings
from unittest.mock import patch

from simple_agent.mcp_client import MCPManager


SERVER = '''
from mcp.server.fastmcp import FastMCP
server = FastMCP("test")
@server.tool()
def greet(name: str) -> str:
    return "Hello " + name
if __name__ == "__main__":
    server.run(transport="stdio")
'''


class MCPClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_env_passthrough_is_explicit_and_config_env_wins(self):
        code = SERVER.replace('return "Hello " + name', 'import os\n    return os.environ.get(name, "<missing>")')
        variables = {"SIMPLE_AGENT_TEST_PASS": "parent", "SIMPLE_AGENT_TEST_PRIVATE": "private"}
        config = {"example": {"command": sys.executable, "args": ["-c", code],
                              "envPassthrough": ["SIMPLE_AGENT_TEST_PASS", "SIMPLE_AGENT_TEST_ABSENT"],
                              "env": {"SIMPLE_AGENT_TEST_PASS": "explicit"}}}
        with patch.dict(os.environ, variables):
            async with MCPManager(config) as manager:
                name = (await manager.list_tools())[0]["function"]["name"]
                for variable, expected in (("SIMPLE_AGENT_TEST_PASS", "explicit"),
                                           ("SIMPLE_AGENT_TEST_PRIVATE", "<missing>"),
                                           ("SIMPLE_AGENT_TEST_ABSENT", "<missing>")):
                    result = json.loads(await manager.call_tool(name, {"name": variable}))
                    self.assertEqual(result["content"][0]["text"], expected)

    async def test_invalid_env_passthrough_fails_before_launch(self):
        for value in ("LANGSEARCH_API_KEY", [""], [1], ["invalid=name"]):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "envPassthrough"):
                    async with MCPManager({"bad": {"command": "must-not-launch", "envPassthrough": value}}):
                        self.fail("Invalid configuration was accepted")

    async def test_stdio_discovery_invocation_and_shutdown(self):
        config = {"example": {"command": sys.executable, "args": ["-c", SERVER]}}
        async with MCPManager(config) as manager:
            tools = await manager.list_tools()
            self.assertEqual(len(tools), 1)
            function = tools[0]["function"]
            self.assertIn("name", function["parameters"]["properties"])
            result = json.loads(await manager.call_tool(function["name"], {"name": "world"}))
            self.assertFalse(result.get("isError", False))
            self.assertEqual(result["content"][0]["text"], "Hello world")
        with self.assertRaises(RuntimeError):
            await manager.list_tools()

    async def test_empty_configuration_and_unknown_tool(self):
        async with MCPManager() as manager:
            self.assertEqual(await manager.list_tools(), [])
            with self.assertRaises(ValueError):
                await manager.call_tool("missing", {})

    async def test_streamable_http_discovery_and_invocation(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        server_code = SERVER.replace(
            'FastMCP("test")', f'FastMCP("test", host="127.0.0.1", port={port})'
        ).replace(
            'server.run(transport="stdio")',
            '''
    import uvicorn
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import PlainTextResponse
    app = server.streamable_http_app()
    async def require_header(request, call_next):
        if request.headers.get("x-test-token") != "test-token":
            return PlainTextResponse("missing token", status_code=403)
        return await call_next(request)
    app.add_middleware(BaseHTTPMiddleware, dispatch=require_header)
    uvicorn.run(app, host="127.0.0.1", port=%s, log_level="error")
''' % port,
        )
        process = subprocess.Popen(
            [sys.executable, "-c", server_code], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        try:
            for _ in range(100):
                if process.poll() is not None:
                    self.fail("MCP HTTP server exited before starting")
                try:
                    reader, writer = await asyncio.wait_for(
                        asyncio.open_connection("127.0.0.1", port), timeout=0.5
                    )
                    writer.close()
                    await writer.wait_closed()
                    break
                except (OSError, TimeoutError):
                    await asyncio.sleep(0.1)
            else:
                self.fail("MCP HTTP server did not start")
            config = {"example": {"url": f"http://127.0.0.1:{port}/mcp", "headers": {"x-test-token": "test-token"}}}
            with warnings.catch_warnings():
                warnings.filterwarnings("error", message="Use `streamable_http_client` instead", category=DeprecationWarning)
                async with MCPManager(config) as manager:
                    tools = await manager.list_tools()
                    result = json.loads(await manager.call_tool(tools[0]["function"]["name"], {"name": "HTTP"}))
                    self.assertEqual(result["content"][0]["text"], "Hello HTTP")
        finally:
            process.terminate()
            process.wait(timeout=10)
