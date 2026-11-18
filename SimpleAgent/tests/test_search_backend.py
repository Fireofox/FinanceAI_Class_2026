import asyncio

import httpx
import pytest

from simple_agent import search_backend


HTML = '''<html><body>
<div class="result results_links"><a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fdocs.python.org%2F3%2F">Python docs</a><a class="result__snippet">Official <b>documentation</b></a></div>
<div class="result results_links"><a class="result__a" href="https://evilpython.org/">Other site</a><span class="result__snippet">Other</span></div>
<div class="result results_links"><a class="result__a" href="https://sub.python.org/page">Subdomain</a><span class="result__snippet">More</span></div>
</body></html>'''


@pytest.mark.asyncio
async def test_search_uses_duckduckgo_and_filters_site(monkeypatch):
    requests = []
    async def respond(request):
        requests.append(request)
        return httpx.Response(200, text=HTML)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(search_backend.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(respond), **kw))
    results = await search_backend.search("python", max_results=5, site="Python.ORG", timelimit="w")
    assert results == [
        {"title": "Python docs", "url": "https://docs.python.org/3/", "body": "Official documentation"},
        {"title": "Subdomain", "url": "https://sub.python.org/page", "body": "More"},
    ]
    assert requests[0].url.host == "html.duckduckgo.com"
    assert requests[0].url.params["q"] == "python site:python.org"
    assert requests[0].url.params["kp"] == "-1"
    assert requests[0].url.params["kl"] == "tw-tzh"
    assert requests[0].url.params["df"] == "w"


@pytest.mark.asyncio
async def test_search_empty_results_are_distinct_from_challenge(monkeypatch):
    responses = [httpx.Response(200, text='<div class="result--no-result">No results found</div>'),
                 httpx.Response(202, text="verification")]
    real_client = httpx.AsyncClient
    monkeypatch.setattr(search_backend.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(lambda _: responses.pop(0)), **kw))
    assert await search_backend.search("no matches") == []
    with pytest.raises(search_backend.SearchError, match="verification"):
        await search_backend.search("blocked")


@pytest.mark.parametrize("site", ["https://example.com", "example.com/path", "127.0.0.1", "evil.com site:other.com", "example.com:443", "-bad.com"])
def test_invalid_site_rejected(site):
    with pytest.raises(ValueError):
        search_backend.normalize_site(site)


@pytest.mark.asyncio
async def test_timeout_cancels_search(monkeypatch):
    async def slow(_request):
        await asyncio.sleep(2)
        return httpx.Response(200, text=HTML)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(search_backend.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(slow), **kw))
    with pytest.raises(search_backend.SearchError, match="timed out"):
        await search_backend.search("test", timeout=0.05)
