"""A minimal MCP server. Copy this directory and replace the example tools.

This server uses stdio: stdout belongs to the MCP protocol. Send diagnostic
messages to stderr (for example, via logging), not print().
"""

from mcp.server.fastmcp import FastMCP

# Change this name to identify your own MCP server.
server = FastMCP("example-server")


@server.tool()
def greet(name: str) -> str:
    """Return a greeting for the supplied name.

    Replace this example with your tool's implementation. The function name,
    typed parameters, return type, and docstring describe the tool to clients.
    """
    return f"Hello, {name}!"


# Add more tools by writing another function and decorating it with @server.tool().
# For example:
#
# @server.tool()
# def another_tool(value: str) -> str:
#     """Describe what this tool does and when to use it."""
#     # TODO: Replace this with your implementation.
#     return value


if __name__ == "__main__":
    server.run(transport="stdio")
