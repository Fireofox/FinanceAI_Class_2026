"""Verify discovery and a call to this server; add --live for a real search."""

import argparse
import asyncio
import json
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main(live: bool) -> None:
    server = Path(__file__).resolve().with_name("server.py")
    parameters = StdioServerParameters(command=sys.executable, args=[str(server)])
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            if not any(tool.name == "web_search" for tool in tools.tools):
                raise RuntimeError("The web_search tool was not discovered")
            arguments = {"query": "Python programming", "site": "python.org", "max_results": 1} if live else {"query": " "}
            result = await session.call_tool("web_search", arguments)
            if result.isError:
                raise RuntimeError("web_search returned a protocol-level tool error")
            payload = result.structuredContent
            if payload is None:
                text = next((item.text for item in result.content if item.type == "text"), None)
                if text is None:
                    raise RuntimeError("web_search returned no text result")
                payload = json.loads(text)
            expected = "ok" if live else "error"
            if payload.get("status") != expected:
                raise RuntimeError(f"Unexpected web_search result: {payload!r}")
            if live and not payload.get("results"):
                raise RuntimeError("Live search returned no results")
            print("MCP discovery and web_search call succeeded" + (" (live search)." if live else " (offline validation)."))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="perform a real DuckDuckGo search")
    asyncio.run(main(parser.parse_args().live))
