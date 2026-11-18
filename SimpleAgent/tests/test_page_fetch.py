import asyncio
import socket
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

from simple_agent.page_fetch import PageFetchError, _PublicNetworkBackend, _fetch_html, _validate_url, fetch_page


class Response:
    def __init__(self, status=200, headers=(), data=b"<html>text</html>"):
        self.status = status
        self.headers = headers
        self.data = data

    async def aiter_stream(self):
        yield self.data


class Pool:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.urls = []

    @asynccontextmanager
    async def stream(self, method, url, headers):
        self.urls.append(url)
        yield next(self.responses)


def test_restrict_url_to_http_and_site():
    _validate_url("https://news.example.com/a", "example.com")
    for url in ("file:///etc/passwd", "https://user:pass@example.com", "https://notexample.com"):
        with pytest.raises(PageFetchError):
            _validate_url(url, "example.com")


async def test_redirect_is_checked_before_request():
    pool = Pool([Response(302, [(b"location", b"http://127.0.0.1/secret")])])
    with pytest.raises(PageFetchError, match="outside"):
        await _fetch_html(pool, "https://example.com/start", "example.com", 1024)
    assert pool.urls == ["https://example.com/start"]


async def test_response_is_html_and_bounded():
    pool = Pool([Response(200, [(b"content-type", b"text/html; charset=utf-8")], b"hello")])
    assert await _fetch_html(pool, "https://example.com", None, 5) == (b"hello", "https://example.com")
    pool = Pool([Response(200, [(b"content-type", b"text/html")], b"123456")])
    with pytest.raises(PageFetchError, match="size"):
        await _fetch_html(pool, "https://example.com", None, 5)
    pool = Pool([Response(200, [(b"content-type", b"application/pdf")])])
    with pytest.raises(PageFetchError, match="not HTML"):
        await _fetch_html(pool, "https://example.com", None, 100)


async def test_dns_resolved_address_is_validated_and_pinned(monkeypatch):
    loop = asyncio.get_running_loop()
    getaddrinfo = AsyncMock(return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))])
    monkeypatch.setattr(loop, "getaddrinfo", getaddrinfo)
    backend = _PublicNetworkBackend()
    backend._backend.connect_tcp = AsyncMock(return_value="connected")
    assert await backend.connect_tcp("example.com", 443) == "connected"
    assert backend._backend.connect_tcp.await_args.args[:2] == ("93.184.216.34", 443)
    getaddrinfo.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]
    with pytest.raises(PageFetchError, match="not public"):
        await backend.connect_tcp("example.com", 443)
    assert backend._backend.connect_tcp.await_count == 1


async def test_extract_truncates_and_timeout_is_reported(monkeypatch):
    async def fake_fetch(*args):
        return b"<html>text</html>", "https://example.com"
    monkeypatch.setattr("simple_agent.page_fetch._fetch_html", fake_fetch)
    monkeypatch.setattr("simple_agent.page_fetch.trafilatura.extract", lambda *args, **kwargs: "a" * 20)
    assert await fetch_page("https://example.com", max_chars=10) == {"content": "a" * 10, "truncated": True}
    async def slow_fetch(*args):
        await asyncio.sleep(10)
    monkeypatch.setattr("simple_agent.page_fetch._fetch_html", slow_fetch)
    with pytest.raises(PageFetchError, match="timed out"):
        await fetch_page("https://example.com", timeout=0.01)
