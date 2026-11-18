"""LangSearch HTTP integration, validation, retries, and result normalization."""

import asyncio
import random
import re
from contextlib import AsyncExitStack
from datetime import date

import httpx


SEARCH_URL = "https://api.langsearch.com/v1/web-search"
REQUEST_TIMEOUT = 15
TOTAL_TIMEOUT = 60
MAX_ATTEMPTS = 3
MAX_CONTENT_CHARS = 20_000
TOTAL_CONTENT_CHARS = 60_000
RETRY_STATUSES = {500, 502, 503, 504}
FRESHNESS_PRESETS = {"noLimit", "oneDay", "oneWeek", "oneMonth", "oneYear"}


class LangSearchError(ValueError):
    """A search failed with a message suitable for the MCP caller."""


def _freshness(value: str) -> str:
    if not isinstance(value, str):
        raise LangSearchError("freshness must be a preset, YYYY-MM-DD, or YYYY-MM-DD..YYYY-MM-DD")
    if value in FRESHNESS_PRESETS:
        return value
    dates = value.split("..")
    try:
        if len(dates) not in (1, 2) or any(not re.fullmatch(r"\d{4}-\d{2}-\d{2}", part) for part in dates):
            raise ValueError
        parsed = [date.fromisoformat(part) for part in dates]
        if parsed[0] > parsed[-1]:
            raise ValueError
    except ValueError:
        raise LangSearchError("freshness must be a valid UTC date/range (start <= end) or a supported preset") from None
    return value


def _domains(name: str, values: list[str] | None) -> list[str] | None:
    if values is None:
        return None
    if not isinstance(values, list) or any(not isinstance(item, str) or not item.strip() for item in values):
        raise LangSearchError(f"{name} must be a list of non-empty domain strings")
    return [item.strip() for item in values]


def _http_error(response: httpx.Response, api_key: str) -> LangSearchError:
    hints = {
        400: "Invalid search request",
        401: "Check LANGSEARCH_API_KEY",
        403: "Check API key and account access",
        429: "Rate limit or account allowance exceeded; check LangSearch account usage",
    }
    message = f"LangSearch HTTP {response.status_code}: {hints.get(response.status_code, 'Search service unavailable')}"
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        detail = payload.get("message") or payload.get("msg")
        if isinstance(detail, str) and detail.strip():
            message += ": " + detail.strip().replace(api_key, "[REDACTED]")[:500]
        log_id = payload.get("log_id")
        if isinstance(log_id, str) and log_id:
            message += f" (log_id: {log_id.replace(api_key, '[REDACTED]')[:200]})"
    return LangSearchError(message.replace(api_key, "[REDACTED]"))


def _normalize(payload: dict, *, max_results: int, include_content: bool, max_content_chars: int) -> dict:
    try:
        sources = payload["data"]["webPages"]["value"]
        if not isinstance(sources, list):
            raise TypeError
        results = []
        remaining = TOTAL_CONTENT_CHARS
        for source in sources[:max_results]:
            if not isinstance(source, dict) or not isinstance(source.get("url"), str) or not source["url"].strip():
                raise TypeError
            result = {
                "title": source.get("name") if isinstance(source.get("name"), str) else "",
                "url": source["url"],
                "body": source.get("snippet") if isinstance(source.get("snippet"), str) else "",
            }
            if isinstance(source.get("datePublished"), str) and source["datePublished"]:
                result["date_published"] = source["datePublished"]
            if include_content:
                text = source.get("text")
                text = text if isinstance(text, str) and text else result["body"]
                limit = min(max_content_chars, remaining)
                result["content"] = text[:limit]
                result["content_truncated"] = len(text) > limit
                remaining -= len(result["content"])
            results.append(result)
    except (KeyError, TypeError):
        raise LangSearchError("LangSearch returned an invalid search result structure") from None
    usage = payload.get("usage")
    result = {"status": "ok" if results else "empty", "results": results,
              "usage": usage if isinstance(usage, dict) else {}}
    if isinstance(payload.get("log_id"), str):
        result["log_id"] = payload["log_id"]
    return result


async def _request(client: httpx.AsyncClient, body: dict, api_key: str) -> dict:
    for attempt in range(MAX_ATTEMPTS):
        try:
            response = await asyncio.wait_for(
                client.post(SEARCH_URL, json=body,
                            headers={"Authorization": f"Bearer {api_key}"}, timeout=REQUEST_TIMEOUT),
                timeout=REQUEST_TIMEOUT,
            )
        except (httpx.TransportError, TimeoutError) as exc:
            message = "LangSearch request timed out" if isinstance(exc, (httpx.TimeoutException, TimeoutError)) else "LangSearch connection failed"
            error = LangSearchError(message)
        else:
            if response.is_success:
                try:
                    payload = response.json()
                    if not isinstance(payload, dict):
                        raise ValueError
                except ValueError:
                    raise LangSearchError("LangSearch returned invalid JSON") from None
                return payload
            error = _http_error(response, api_key)
            if response.status_code not in RETRY_STATUSES:
                raise error
        if attempt == MAX_ATTEMPTS - 1:
            raise error
        await asyncio.sleep(0.5 * 2 ** attempt + random.uniform(0, 0.25))
    raise AssertionError("unreachable")


async def search(
    query: str, *, api_key: str, max_results: int = 5, include_content: bool = False,
    max_content_chars: int = 5000, freshness: str = "noLimit",
    include_domains: list[str] | None = None, exclude_domains: list[str] | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict:
    """Search with at most three attempts and one total time budget.

    An optional client permits embedding and testing without changing the API endpoint.
    The caller retains ownership of an injected client.
    """
    if not isinstance(query, str) or not query.strip():
        raise LangSearchError("Search query must not be empty")
    if isinstance(max_results, bool) or not isinstance(max_results, int) or not 1 <= max_results <= 50:
        raise LangSearchError("max_results must be between 1 and 50")
    if not isinstance(include_content, bool):
        raise LangSearchError("include_content must be true or false")
    if isinstance(max_content_chars, bool) or not isinstance(max_content_chars, int) or not 1 <= max_content_chars <= MAX_CONTENT_CHARS:
        raise LangSearchError("max_content_chars must be between 1 and 20000")
    body = {"query": query.strip(), "count": max_results, "freshness": _freshness(freshness)}
    for name, domains in (("includeDomains", include_domains), ("excludeDomains", exclude_domains)):
        values = _domains(name, domains)
        if values is not None:
            body[name] = values
    if include_content:
        body["contents"] = {"text": {"maxCharacters": max_content_chars}}
    if not isinstance(api_key, str) or not api_key.strip():
        raise LangSearchError("Set LANGSEARCH_API_KEY in the server environment, using mcpServers.langsearch.env or envPassthrough")
    api_key = api_key.strip()
    if any(ord(char) < 32 or ord(char) > 126 for char in api_key):
        raise LangSearchError("LANGSEARCH_API_KEY contains invalid header characters")
    try:
        async with asyncio.timeout(TOTAL_TIMEOUT):
            async with AsyncExitStack() as stack:
                if client is None:
                    client = await stack.enter_async_context(httpx.AsyncClient(follow_redirects=False))
                payload = await _request(client, body, api_key)
                try:
                    return _normalize(payload, max_results=max_results, include_content=include_content,
                                      max_content_chars=max_content_chars)
                except LangSearchError as exc:
                    log_id = payload.get("log_id")
                    suffix = f" (log_id: {log_id.replace(api_key, '[REDACTED]')[:200]})" if isinstance(log_id, str) and log_id else ""
                    raise LangSearchError((str(exc) + suffix).replace(api_key, "[REDACTED]")) from None
    except TimeoutError:
        raise LangSearchError("LangSearch total time limit exceeded (60 seconds)") from None
