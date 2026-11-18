"""DuckDuckGo HTML search; no alternate search engine is queried."""

import asyncio
import ipaddress
import re
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx
from lxml import html


class SearchError(RuntimeError):
    """DuckDuckGo could not provide a usable search response."""


SEARCH_URL = "https://html.duckduckgo.com/html/"
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
_CLASSES = "contains(concat(' ', normalize-space(@class), ' '), ' %s ')"


def normalize_site(site: str | None) -> str | None:
    """Validate and normalize a single domain name, excluding IP addresses."""
    if site is None:
        return None
    if not isinstance(site, str) or not site or site != site.strip():
        raise ValueError("site must be a domain name")
    try:
        domain = site.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise ValueError("site must be a domain name") from exc
    if len(domain) > 253 or "." not in domain:
        raise ValueError("site must be a domain name")
    labels = domain.split(".")
    if any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels):
        raise ValueError("site must be a domain name")
    try:
        ipaddress.ip_address(domain)
    except ValueError:
        return domain
    raise ValueError("site must be a domain name, not an IP address")


def _result_url(raw: str) -> str | None:
    url = urljoin(SEARCH_URL, raw)
    parsed = urlsplit(url)
    if parsed.hostname in {"duckduckgo.com", "www.duckduckgo.com", "html.duckduckgo.com"} and parsed.path.startswith("/l/"):
        url = parse_qs(parsed.query).get("uddg", [""])[0]
        parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        return None
    return url


def _parse_results(document: str, site: str | None, max_results: int) -> list[dict[str, str]]:
    try:
        tree = html.fromstring(document)
    except (ValueError, TypeError) as exc:
        raise SearchError("DuckDuckGo returned an invalid response") from exc
    results = []
    seen = set()
    for entry in tree.xpath("//div[" + (_CLASSES % "result") + "]"):
        links = entry.xpath(".//a[" + (_CLASSES % "result__a") + "]")
        if not links:
            continue
        link = links[0]
        try:
            url = _result_url(link.get("href", ""))
            host = urlsplit(url).hostname.rstrip(".").encode("idna").decode("ascii").lower() if url else ""
        except (ValueError, UnicodeError):
            continue
        if not url or url in seen or (site and host != site and not host.endswith("." + site)):
            continue
        title = " ".join(link.text_content().split())
        if not title:
            continue
        snippets = entry.xpath(".//*[" + (_CLASSES % "result__snippet") + "]")
        snippet = " ".join(snippets[0].text_content().split()) if snippets else ""
        results.append({"title": title, "url": url, "body": snippet})
        seen.add(url)
        if len(results) >= max_results:
            break
    return results


async def search(query: str, max_results: int = 5, region: str = "tw-tzh",
                 safesearch: str = "moderate", timelimit: str | None = None,
                 site: str | None = None, timeout: float = 15) -> list[dict[str, str]]:
    """Search DuckDuckGo and return title, URL and snippet for each result."""
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")
    if isinstance(max_results, bool) or not isinstance(max_results, int) or not 1 <= max_results <= 10:
        raise ValueError("max_results must be between 1 and 10")
    if not isinstance(region, str) or not re.fullmatch(r"[a-zA-Z]{2,3}-[a-zA-Z]{2,3}", region):
        raise ValueError("region must be a region code, for example tw-tzh")
    levels = {"strict": "1", "moderate": "-1", "off": "-2"}
    if safesearch not in levels:
        raise ValueError("safesearch must be strict, moderate, or off")
    if timelimit not in (None, "d", "w", "m", "y"):
        raise ValueError("timelimit must be d, w, m, y, or null")
    domain = normalize_site(site)
    params = {"q": query.strip() + (f" site:{domain}" if domain else ""),
              "kl": region, "kp": levels[safesearch]}
    if timelimit:
        params["df"] = timelimit
    try:
        async with asyncio.timeout(timeout):
            async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, follow_redirects=False, timeout=timeout) as client:
                async with client.stream("GET", SEARCH_URL, params=params) as response:
                    if response.status_code == 202:
                        raise SearchError("DuckDuckGo requested verification or rate-limited this search")
                    response.raise_for_status()
                    chunks, size = [], 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > 2_000_000:
                            raise SearchError("DuckDuckGo response exceeded the size limit")
                        chunks.append(chunk)
                    document = b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")
    except TimeoutError as exc:
        raise SearchError("DuckDuckGo search timed out") from exc
    except httpx.HTTPError as exc:
        raise SearchError(f"DuckDuckGo search failed: {type(exc).__name__}") from exc
    # A successful HTTP response can still contain a CAPTCHA or altered page.
    lowered = document.lower()
    if "anomaly-modal" in lowered or "anomaly.js" in lowered:
        raise SearchError("DuckDuckGo requested verification or rate-limited this search")
    results = _parse_results(document, domain, max_results)
    if not results and not ("result__a" in document or "no results found" in lowered or "result--no-result" in lowered):
        raise SearchError("DuckDuckGo returned an unrecognized search response")
    return results
