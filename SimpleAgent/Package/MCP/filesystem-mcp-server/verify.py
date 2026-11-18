"""Verify both file tools through MCP using a temporary working directory."""

import asyncio
import json
from pathlib import Path
import sys
import tempfile

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def unpack(result):
    if result.isError:
        raise RuntimeError("MCP tool call failed")
    if result.structuredContent is not None:
        return result.structuredContent
    text = next((item.text for item in result.content if item.type == "text"), None)
    if text is None:
        raise RuntimeError("MCP tool returned no text result")
    return json.loads(text)


async def main():
    script = Path(__file__).resolve().with_name("server.py")
    with tempfile.TemporaryDirectory(prefix="filesystem-mcp-verify-") as workdir:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=[str(script)],
            env={"FILE_MCP_ROOT": workdir, "FILE_MCP_MAX_BYTES": "1048576"},
        )
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                if not {"read_file", "write_file"}.issubset({tool.name for tool in tools.tools}):
                    raise RuntimeError("File tools were not discovered")
                created = unpack(await session.call_tool("write_file", {"path": "example.txt", "content": "Hello, 世界!"}))
                if created.get("status") != "ok":
                    raise RuntimeError(f"Write failed: {created!r}")
                readback = unpack(await session.call_tool("read_file", {"path": "example.txt"}))
                if readback.get("status") != "ok" or readback.get("content") != "Hello, 世界!":
                    raise RuntimeError(f"Read failed: {readback!r}")
                rejected = unpack(await session.call_tool("write_file", {"path": "example.txt", "content": "replacement"}))
                if rejected.get("status") != "error":
                    raise RuntimeError("Existing file was not protected against overwrite")
                print("MCP file tools verified: create, read and overwrite protection.")


if __name__ == "__main__":
    asyncio.run(main())
