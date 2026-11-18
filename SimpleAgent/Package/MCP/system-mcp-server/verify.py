"""Start the system server over stdio and verify its clock tool."""

import asyncio
import json
from datetime import datetime, timedelta, timezone
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
            if not any(tool.name == "get_system_datetime" for tool in tools.tools):
                raise RuntimeError("The get_system_datetime tool was not discovered")
            before = datetime.now(timezone.utc)
            result = await session.call_tool("get_system_datetime", {})
            after = datetime.now(timezone.utc)
            if result.isError:
                raise RuntimeError("The system datetime tool failed")
            data = result.structuredContent or json.loads(result.content[0].text)
            local = datetime.fromisoformat(data["local_datetime"])
            utc = datetime.fromisoformat(data["utc_datetime"])
            if utc.utcoffset() != timedelta(0) or local.astimezone(timezone.utc) != utc:
                raise RuntimeError("Local and UTC timestamps do not describe the same instant")
            if not before - timedelta(seconds=1) <= utc <= after:
                raise RuntimeError("System datetime is outside the invocation interval")
            print("Server discovery and get_system_datetime succeeded")


if __name__ == "__main__":
    asyncio.run(main())
