"""Start this server over stdio and verify its example tool."""

import asyncio
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> None:
    script = Path(__file__).resolve().with_name("server.py")
    parameters = StdioServerParameters(command=sys.executable, args=[str(script)])
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            if not any(tool.name == "greet" for tool in tools.tools):
                raise RuntimeError("The example greet tool was not discovered")
            result = await session.call_tool("greet", {"name": "World"})
            output = [item.text for item in result.content if item.type == "text"]
            if result.isError or "Hello, World!" not in output:
                raise RuntimeError(f"Unexpected greet result: {output!r}")
            print("Server discovery and greet tool succeeded: Hello, World!")


if __name__ == "__main__":
    asyncio.run(main())
