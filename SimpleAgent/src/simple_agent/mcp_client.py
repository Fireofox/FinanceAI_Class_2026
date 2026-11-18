"""Connect to MCP tool servers over stdio or Streamable HTTP.

Keep the manager and its calls in the same asyncio task: the MCP SDK's
transport contexts must be closed by the task which entered them.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from contextlib import AsyncExitStack
from typing import Any

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client


def _function_name(server: str, tool: str) -> str:
    """Return a valid, collision-resistant function name (max 64 characters)."""
    original = f"{server}\0{tool}"
    digest = hashlib.sha256(original.encode("utf-8")).hexdigest()[:12]
    prefix = re.sub(r"[^a-zA-Z0-9_-]", "_", f"{server}__{tool}")[:51]
    return f"{prefix}_{digest}"


def _stdio_env(config: dict[str, Any]) -> dict[str, str] | None:
    """Forward only explicitly selected parent variables; explicit env wins."""
    names = config.get("envPassthrough", [])
    if not isinstance(names, list) or any(not isinstance(name, str) or not name.strip() or "=" in name or "\0" in name for name in names):
        raise ValueError("envPassthrough must be a list of non-empty environment variable names")
    explicit = config.get("env")
    if explicit is not None and (not isinstance(explicit, dict) or any(not isinstance(key, str) or not isinstance(value, str) for key, value in explicit.items())):
        raise ValueError("MCP env must be an object of string values")
    if not names and explicit is None:
        return None
    env = {name: os.environ[name] for name in names if name in os.environ}
    env.update(explicit or {})
    return env


class MCPManager:
    """Manage server sessions and adapt their tools to function-calling APIs."""

    def __init__(self, servers: dict[str, dict[str, Any]] | None = None) -> None:
        self.servers = servers or {}
        self._stack = AsyncExitStack()
        self._sessions: dict[str, ClientSession] = {}
        self._tool_routes: dict[str, tuple[ClientSession, str]] = {}
        self._connected = False

    async def __aenter__(self) -> MCPManager:
        await self.connect()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    async def connect(self) -> None:
        if self._connected:
            raise RuntimeError("MCP manager is already connected")
        try:
            for name, config in self.servers.items():
                transport = config.get("type", "stdio" if "command" in config else "http")
                if transport == "stdio":
                    params = StdioServerParameters(
                        command=config["command"],
                        args=config.get("args", []),
                        env=_stdio_env(config),
                        cwd=config.get("cwd"),
                    )
                    streams = await self._stack.enter_async_context(stdio_client(params))
                elif transport in ("http", "streamable-http", "streamable_http"):
                    http_client = await self._stack.enter_async_context(
                        httpx.AsyncClient(
                            headers=config.get("headers"),
                            timeout=httpx.Timeout(30.0, read=300.0),
                            follow_redirects=True,
                        )
                    )
                    streams = await self._stack.enter_async_context(
                        streamable_http_client(config["url"], http_client=http_client)
                    )
                else:
                    raise ValueError(f"Unsupported MCP transport {transport!r} for {name!r}")
                session = await self._stack.enter_async_context(ClientSession(*streams[:2]))
                await session.initialize()
                self._sessions[name] = session
            self._connected = True
        except BaseException:
            await self.aclose()
            raise

    async def list_tools(self) -> list[dict[str, Any]]:
        if not self._connected:
            raise RuntimeError("MCP manager is not connected")
        routes: dict[str, tuple[ClientSession, str]] = {}
        definitions: list[dict[str, Any]] = []
        for server_name, session in self._sessions.items():
            cursor = None
            seen_cursors: set[str] = set()
            while True:
                page = await session.list_tools(cursor=cursor)
                for tool in page.tools:
                    name = _function_name(server_name, tool.name)
                    if name in routes:
                        raise ValueError(f"Duplicate MCP tool: {server_name}/{tool.name}")
                    routes[name] = (session, tool.name)
                    definitions.append({
                        "type": "function",
                        "function": {
                            "name": name,
                            "description": f"[{server_name}] {tool.description or tool.name}",
                            "parameters": tool.inputSchema,
                        },
                    })
                cursor = page.nextCursor
                if not cursor:
                    break
                if cursor in seen_cursors:
                    raise ValueError(f"MCP server {server_name!r} repeated a pagination cursor")
                seen_cursors.add(cursor)
        self._tool_routes = routes
        return definitions

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        if name not in self._tool_routes:
            raise ValueError(f"Unknown MCP tool: {name}")
        session, original_name = self._tool_routes[name]
        result = await session.call_tool(original_name, arguments)
        return json.dumps(result.model_dump(mode="json", by_alias=True, exclude_none=True), ensure_ascii=False)

    async def aclose(self) -> None:
        try:
            await self._stack.aclose()
        finally:
            self._sessions.clear()
            self._tool_routes.clear()
            self._connected = False
