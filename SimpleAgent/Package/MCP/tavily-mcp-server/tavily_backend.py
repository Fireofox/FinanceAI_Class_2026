"""Call the Tavily Search REST API; no remote MCP server is involved."""

import asyncio
import ipaddress
import json
import math
import os
import re
from urllib.parse import urlsplit

import httpx


SEARCH_URL = "https://api.tavily.com/search"
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
TIME_RANGES = {"d": "day", "w": "week", "m": "month", "y": "year"}


class SearchError(RuntimeError):
    def __init__(self, message, code="INVALID_RESPONSE", *, retryable=False, http_status=None):
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.http_status = http_status


def positive_setting(name, default, *, integer=False):
    raw = os.getenv(name, str(default))
    try:
        value = int(raw) if integer else float(raw)
        if not math.isfinite(value) or value <= 0:
            raise ValueError
        return value
    except (ValueError, OverflowError):
        raise ValueError(f"{name} must be a positive {'integer' if integer else 'number'}") from None


def authentication():
    """Return headers and the selected mode, never including the key in errors."""
    mode = os.getenv("TAVILY_AUTH_MODE", "auto").strip().lower()
    if mode not in {"auto", "key", "keyless"}:
        raise ValueError("TAVILY_AUTH_MODE must be auto, key, or keyless")
    key = os.getenv("TAVILY_API_KEY", "").strip()
    if mode == "auto":
        mode = "key" if key else "keyless"
    if mode == "key":
        if not key:
            raise ValueError("TAVILY_API_KEY is required when TAVILY_AUTH_MODE=key")
        return {"Authorization": f"Bearer {key}"}, mode
    return {"X-Tavily-Access-Mode": "keyless"}, mode


def normalize_site(site):
    if site is None:
        return None
    if not isinstance(site, str) or not site or site != site.strip():
        raise ValueError("site must be a domain name, without a scheme, port, or path")
    try:
        domain = site.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError:
        raise ValueError("site must be a valid domain name") from None
    if len(domain) > 253 or "." not in domain or any(
        not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
        for label in domain.split(".")
    ):
        raise ValueError("site must be a valid domain name")
    try:
        ipaddress.ip_address(domain)
    except ValueError:
        return domain
    raise ValueError("site must be a domain name, not an IP address")


def _http_error(status):
    if status in (401, 403):
        return SearchError("Tavily rejected authentication or access; check the selected auth mode and API key.",
                           "AUTHENTICATION_ERROR", http_status=status)
    if status == 429:
        return SearchError("Tavily rate limit reached; wait before retrying or use an API key with available quota.",
                           "RATE_LIMITED", retryable=True, http_status=status)
    return SearchError(f"Tavily API returned HTTP {status}.", "HTTP_ERROR",
                       retryable=status >= 500, http_status=status)


def _normalize_results(data, *, site, max_results, include_content, page_limit, total_limit):
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise SearchError("Tavily returned an unexpected response schema.")
    results, seen = [], set()
    remaining, partial = total_limit, False
    for item in data["results"]:
        if not isinstance(item, dict):
            raise SearchError("Tavily returned an invalid search result.")
        url, title = item.get("url"), item.get("title")
        if not isinstance(url, str) or not isinstance(title, str) or not title.strip():
            raise SearchError("Tavily returned a result without a valid title or URL.")
        try:
            parsed = urlsplit(url)
            host = (parsed.hostname or "").rstrip(".").encode("idna").decode("ascii").lower()
        except (ValueError, UnicodeError):
            continue
        if parsed.scheme not in {"http", "https"} or not host or parsed.username is not None or parsed.password is not None:
            continue
        if url in seen or (site and host != site and not host.endswith("." + site)):
            continue
        seen.add(url)
        result = {"title": title.strip(), "url": url,
                  "body": item.get("content") if isinstance(item.get("content"), str) else ""}
        score = item.get("score")
        if isinstance(score, (int, float)) and not isinstance(score, bool) and math.isfinite(score):
            result["score"] = score
        if isinstance(item.get("published_date"), str):
            result["published_date"] = item["published_date"]
        if include_content:
            raw = item.get("raw_content")
            if isinstance(raw, str) and raw.strip():
                limit = min(page_limit, remaining)
                result["content"] = raw[:limit]
                result["content_truncated"] = len(raw) > limit
                remaining -= len(result["content"])
            else:
                result["content_error"] = "Tavily did not return page content; the search snippet is still available."
                partial = True
        results.append(result)
        if len(results) >= max_results:
            break
    return results, partial


async def search(query, *, max_results=5, timelimit=None, site=None, include_content=False,
                 topic="general", search_depth="basic"):
    if not isinstance(query, str) or not query.strip():
        raise ValueError("Search query must not be empty")
    if isinstance(max_results, bool) or not isinstance(max_results, int) or not 1 <= max_results <= 10:
        raise ValueError("max_results must be between 1 and 10")
    if timelimit is not None and timelimit not in TIME_RANGES:
        raise ValueError("timelimit must be d, w, m, y, or null")
    if topic not in {"general", "news"} or search_depth not in {"basic", "advanced"}:
        raise ValueError("Unsupported topic or search_depth")
    if not isinstance(include_content, bool):
        raise ValueError("include_content must be true or false")
    site = normalize_site(site)
    timeout = positive_setting("TAVILY_TIMEOUT", 30)
    page_limit = positive_setting("TAVILY_PAGE_CHAR_LIMIT", 20000, integer=True)
    total_limit = positive_setting("TAVILY_TOTAL_CHAR_LIMIT", 60000, integer=True)
    headers, mode = authentication()
    body = {"query": query.strip(), "max_results": max_results, "topic": topic,
            "search_depth": search_depth, "include_answer": False,
            "include_raw_content": include_content, "include_published_date": True}
    if site:
        body["include_domains"] = [site]
    if timelimit:
        body["time_range"] = TIME_RANGES[timelimit]
    try:
        async with asyncio.timeout(timeout):
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
                async with client.stream("POST", SEARCH_URL, headers=headers, json=body) as response:
                    if response.status_code != 200:
                        raise _http_error(response.status_code)
                    chunks, size = [], 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > MAX_RESPONSE_BYTES:
                            raise SearchError("Tavily response exceeded the size limit.", "RESPONSE_TOO_LARGE")
                        chunks.append(chunk)
                    try:
                        data = json.loads(b"".join(chunks))
                    except (ValueError, UnicodeError):
                        raise SearchError("Tavily returned invalid JSON.") from None
    except (TimeoutError, httpx.TimeoutException):
        raise SearchError("Tavily search timed out.", "TIMEOUT", retryable=True) from None
    except httpx.HTTPError:
        raise SearchError("Could not connect to the Tavily API.", "NETWORK_ERROR", retryable=True) from None
    results, partial = _normalize_results(data, site=site, max_results=max_results,
                                         include_content=include_content, page_limit=page_limit,
                                         total_limit=total_limit)
    output = {"status": ("partial" if partial else "ok") if results else "empty",
              "source": "Tavily", "auth_mode": mode, "query": query.strip(), "results": results}
    if isinstance(data.get("request_id"), str):
        output["request_id"] = data["request_id"]
    return output
