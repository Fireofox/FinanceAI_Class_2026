"""Fetch public HTML pages and extract their main text.

DNS is resolved once at the socket boundary and the validated address is used
for the connection, while httpcore retains the original hostname for TLS.
"""

import asyncio
import ipaddress
import socket
import ssl
from urllib.parse import urljoin, urlsplit

import httpcore
import trafilatura


class PageFetchError(ValueError):
    """A page could not be retrieved or parsed."""


def _validate_url(url: str, allowed_domain: str | None = None) -> None:
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise PageFetchError("Invalid page URL") from exc
    if parsed.scheme not in ("http", "https") or not host or parsed.username is not None or parsed.password is not None:
        raise PageFetchError("Only public HTTP(S) page URLs are supported")
    if port is not None and not 1 <= port <= 65535:
        raise PageFetchError("Invalid page URL port")
    if allowed_domain:
        hostname = host.rstrip(".").lower()
        domain = allowed_domain.rstrip(".").lower()
        if hostname != domain and not hostname.endswith("." + domain):
            raise PageFetchError("Page URL is outside the requested site")


class _PublicNetworkBackend(httpcore.AsyncNetworkBackend):
    """Resolve at connection time and connect only to validated public IPs."""

    def __init__(self):
        self._backend = httpcore.AnyIOBackend()

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        try:
            records = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
            addresses = list(dict.fromkeys(record[4][0] for record in records))
            if not addresses:
                raise PageFetchError("Page hostname has no addresses")
            for address in addresses:
                ip = ipaddress.ip_address(address)
                if not ip.is_global or ip.is_multicast:
                    raise PageFetchError("Page address is not public")
            last_error = None
            for address in addresses:
                try:
                    return await self._backend.connect_tcp(
                        address, port, timeout=timeout, local_address=local_address, socket_options=socket_options
                    )
                except (OSError, httpcore.NetworkError) as exc:
                    last_error = exc
            raise PageFetchError("Unable to connect to page") from last_error
        except (socket.gaierror, ValueError) as exc:
            if isinstance(exc, PageFetchError):
                raise
            raise PageFetchError("Unable to resolve page hostname") from exc

    async def connect_unix_socket(self, path, timeout=None, socket_options=None):
        raise PageFetchError("Unix sockets are not supported")

    async def sleep(self, seconds):
        await self._backend.sleep(seconds)


async def _fetch_html(pool, url: str, allowed_domain: str | None, max_bytes: int) -> tuple[bytes, str]:
    for _ in range(6):
        _validate_url(url, allowed_domain)
        async with pool.stream("GET", url, headers={"User-Agent": "SimpleAgent/0.1", "Accept": "text/html,application/xhtml+xml"}) as response:
            headers = {key.lower(): value for key, value in response.headers}
            if response.status in (301, 302, 303, 307, 308):
                location = headers.get(b"location")
                if not location:
                    raise PageFetchError("Page redirect has no location")
                url = urljoin(url, location.decode("latin-1"))
                continue
            if not 200 <= response.status < 300:
                raise PageFetchError(f"Page returned HTTP {response.status}")
            content_type = headers.get(b"content-type", b"").decode("latin-1").split(";", 1)[0].strip().lower()
            if content_type not in ("text/html", "application/xhtml+xml"):
                raise PageFetchError("Page is not HTML")
            chunks = []
            total = 0
            async for chunk in response.aiter_stream():
                total += len(chunk)
                if total > max_bytes:
                    raise PageFetchError("Page exceeds the download size limit")
                chunks.append(chunk)
            return b"".join(chunks), url
    raise PageFetchError("Too many page redirects")


async def fetch_page(url: str, *, timeout: float = 10, max_chars: int = 20000, allowed_domain: str | None = None) -> dict:
    """Fetch and extract a public HTML page, or raise PageFetchError."""
    if timeout <= 0 or max_chars <= 0:
        raise ValueError("Page timeout and character limit must be positive")
    try:
        async with asyncio.timeout(timeout):
            async with httpcore.AsyncConnectionPool(
                ssl_context=ssl.create_default_context(), network_backend=_PublicNetworkBackend(), max_connections=1
            ) as pool:
                html, final_url = await _fetch_html(pool, url, allowed_domain, 2 * 1024 * 1024)
            content = await asyncio.to_thread(
                trafilatura.extract, html, url=final_url, include_comments=False, output_format="txt"
            )
            if not content:
                raise PageFetchError("No readable page content found")
            return {"content": content[:max_chars], "truncated": len(content) > max_chars}
    except TimeoutError as exc:
        raise PageFetchError("Page request timed out") from exc
    except (httpcore.HTTPError, OSError) as exc:
        raise PageFetchError("Page request failed") from exc
