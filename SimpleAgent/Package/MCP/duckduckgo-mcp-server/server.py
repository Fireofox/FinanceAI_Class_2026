"""Standalone stdio MCP server for DuckDuckGo web search."""

import asyncio
import math
import os
from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from page_fetch import PageFetchError, fetch_page
from search_backend import SearchError, normalize_site, search

mcp = FastMCP("SimpleAgent Web Search")


def _limit(name: str, default: float, integer: bool = False):
    value = os.environ.get(name)
    if value is None:
        return int(default) if integer else default
    try:
        result = int(value) if integer else float(value)
        if not math.isfinite(result) or result <= 0:
            raise ValueError
        return result
    except (ValueError, OverflowError):
        raise ValueError(f"{name} must be a positive {'integer' if integer else 'number'}") from None


@mcp.tool()
async def web_search(
    query: Annotated[str, Field(min_length=1, description="Search query")],
    max_results: Annotated[int, Field(ge=1, le=10, description="Number of results, from 1 to 10")] = 5,
    region: str = "tw-tzh",
    safesearch: Literal["strict", "moderate", "off"] = "moderate",
    timelimit: Literal["d", "w", "m", "y"] | None = None,
    site: str | None = None,
    include_content: bool = False,
) -> dict:
    """Search DuckDuckGo. Optionally restrict to a domain and retrieve HTML page text."""
    search_timeout = _limit("SIMPLE_AGENT_SEARCH_TIMEOUT", 15)
    page_timeout = _limit("SIMPLE_AGENT_PAGE_TIMEOUT", 10)
    total_timeout = _limit("SIMPLE_AGENT_TOTAL_TIMEOUT", 60)
    page_limit = _limit("SIMPLE_AGENT_PAGE_CHAR_LIMIT", 20000, True)
    total_limit = _limit("SIMPLE_AGENT_TOTAL_CHAR_LIMIT", 60000, True)
    if not isinstance(query, str) or not query.strip():
        return {"status": "error", "error": "Search query must not be empty", "results": []}
    if not isinstance(max_results, int) or isinstance(max_results, bool) or not 1 <= max_results <= 10:
        return {"status": "error", "error": "max_results must be between 1 and 10", "results": []}

    loop = asyncio.get_running_loop()
    deadline = loop.time() + total_timeout
    try:
        site = normalize_site(site)
        results = await asyncio.wait_for(
            search(query, max_results=max_results, region=region, safesearch=safesearch,
                   timelimit=timelimit, site=site, timeout=min(search_timeout, total_timeout)),
            timeout=min(search_timeout, total_timeout),
        )
    except (SearchError, ValueError, TimeoutError) as exc:
        return {"status": "error", "error": str(exc) or "Search timed out", "results": []}
    if not results:
        return {"status": "empty", "results": []}
    if not include_content:
        return {"status": "ok", "results": results}

    async def fetch(result):
        try:
            return await fetch_page(result["url"], timeout=page_timeout, max_chars=page_limit, allowed_domain=site)
        except (PageFetchError, TimeoutError) as exc:
            return {"error": str(exc) or "Page fetch timed out"}

    tasks = [asyncio.create_task(fetch(result)) for result in results]
    try:
        done, pending = await asyncio.wait(tasks, timeout=max(0, deadline - loop.time()))
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        remaining = total_limit
        partial = False
        for result, task in zip(results, tasks):
            if task not in done:
                result["content_error"] = "Total search time limit exceeded"
                partial = True
                continue
            page = task.result()
            if "error" in page:
                result["content_error"] = page["error"]
                partial = True
                continue
            content = page["content"]
            result["content"] = content[:remaining]
            result["content_truncated"] = page["truncated"] or len(content) > remaining
            remaining -= len(result["content"])
        return {"status": "partial" if partial else "ok", "results": results}
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
