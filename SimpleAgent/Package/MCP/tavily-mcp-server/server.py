"""Local Python MCP server exposing web_search through the Tavily REST API."""

from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from tavily_backend import SearchError, search


mcp = FastMCP("SimpleAgent Tavily Search")


@mcp.tool()
async def web_search(
    query: Annotated[str, Field(min_length=1, description="Search query")],
    max_results: Annotated[int, Field(ge=1, le=10)] = 5,
    timelimit: Literal["d", "w", "m", "y"] | None = None,
    site: str | None = None,
    include_content: bool = False,
    topic: Literal["general", "news"] = "general",
    search_depth: Literal["basic", "advanced"] = "basic",
) -> dict:
    """Search Tavily for sources. Optionally filter by domain/date and retrieve page content.

    The MCP server runs locally; queries are sent to the Tavily cloud API.
    Use basic search first. Advanced search and page content may use more credits.
    """
    try:
        return await search(query, max_results=max_results, timelimit=timelimit, site=site,
                            include_content=include_content, topic=topic, search_depth=search_depth)
    except SearchError as exc:
        result = {"status": "error", "source": "Tavily", "error": str(exc),
                  "error_code": exc.code, "retryable": exc.retryable, "results": []}
        if exc.http_status is not None:
            result["http_status"] = exc.http_status
        return result
    except ValueError as exc:
        return {"status": "error", "source": "Tavily", "error": str(exc),
                "error_code": "INVALID_ARGUMENT_OR_CONFIG", "retryable": False, "results": []}


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
