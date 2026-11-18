import asyncio
import json

import httpx
import pytest

from simple_agent import langsearch_backend as backend


def envelope(sources):
    return {"code": 200, "log_id": "request-123", "data": {"webPages": {"value": sources}},
            "usage": {"input_tokens": 3, "output_tokens": 20}}


async def test_snippets_authentication_filters_and_optional_metadata():
    def handle(request):
        assert request.method == "POST"
        assert str(request.url) == backend.SEARCH_URL
        assert request.headers["Authorization"] == "Bearer test-key"
        assert request.headers["content-type"] == "application/json"
        assert json.loads(request.content) == {
            "query": "Python MCP", "count": 2, "freshness": "2026-09-01..2026-09-13",
            "includeDomains": ["python.org"], "excludeDomains": ["example.com"],
        }
        return httpx.Response(200, json=envelope([
            {"name": "Python", "url": "https://python.org", "snippet": "Language", "datePublished": "2026-09-02"},
            {"name": None, "url": "https://python.org/doc", "snippet": None, "datePublished": None},
        ]))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        result = await backend.search("  Python MCP  ", api_key="test-key", max_results=2,
                                      freshness="2026-09-01..2026-09-13", include_domains=[" python.org "],
                                      exclude_domains=["example.com"], client=client)
        assert not client.is_closed
    assert result["status"] == "ok"
    assert result["results"] == [
        {"title": "Python", "url": "https://python.org", "body": "Language", "date_published": "2026-09-02"},
        {"title": "", "url": "https://python.org/doc", "body": ""},
    ]
    assert result["usage"] == {"input_tokens": 3, "output_tokens": 20}
    assert result["log_id"] == "request-123"


async def test_full_text_applies_per_result_and_total_unicode_limits():
    def handle(request):
        assert json.loads(request.content)["contents"] == {"text": {"maxCharacters": 20000}}
        return httpx.Response(200, json=envelope([
            {"url": f"https://example.com/{i}", "text": "文" * 20001} for i in range(4)
        ]))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        result = await backend.search("test", api_key="test-key", include_content=True,
                                      max_content_chars=20000, client=client)
    assert [len(item["content"]) for item in result["results"]] == [20000, 20000, 20000, 0]
    assert all(item["content_truncated"] for item in result["results"])
    assert result["results"][0]["content"] == "文" * 20000


async def test_missing_text_falls_back_to_snippet_and_empty_results_are_valid():
    calls = []

    def handle(request):
        body = json.loads(request.content)
        calls.append(body)
        sources = [{"url": "https://example.com", "text": None, "snippet": "fallback"}] if len(calls) == 1 else []
        return httpx.Response(200, json=envelope(sources))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        result = await backend.search("test", api_key="test-key", include_content=True, client=client)
        empty = await backend.search("test", api_key="test-key", client=client)
    assert calls[0]["contents"] == {"text": {"maxCharacters": 5000}}
    assert result["results"][0]["content"] == "fallback"
    assert result["results"][0]["content_truncated"] is False
    assert empty["status"] == "empty" and empty["results"] == []
    assert empty["usage"]["input_tokens"] == 3
    assert len(calls) == 2


@pytest.mark.parametrize("freshness", ["noLimit", "oneDay", "oneWeek", "oneMonth", "oneYear", "2024-02-29", "2026-01-01..2026-01-01"])
async def test_supported_date_filters(freshness):
    def handle(request):
        assert json.loads(request.content)["freshness"] == freshness
        return httpx.Response(200, json=envelope([]))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        await backend.search("test", api_key="test-key", freshness=freshness, client=client)


@pytest.mark.parametrize("options", [
    {"query": " "}, {"max_results": 0}, {"max_results": 51}, {"max_results": True},
    {"max_content_chars": 0}, {"max_content_chars": 20001}, {"include_content": "yes"},
    {"freshness": "2026-02-29"}, {"freshness": "2026-09-13..2026-09-01"}, {"freshness": "20260901"},
    {"include_domains": [""]}, {"exclude_domains": "example.com"},
    {"api_key": ""}, {"api_key": "key\nheader"},
])
async def test_invalid_input_does_not_contact_api(options):
    def handle(request):
        pytest.fail("Invalid input must not issue a request")

    args = {"query": "test", "api_key": "test-key", **options}
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(backend.LangSearchError):
            await backend.search(**args, client=client)


@pytest.mark.parametrize("status", [400, 401, 403, 429])
async def test_permanent_errors_are_not_retried_and_preserve_diagnostics(status):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(status, json={"code": str(status), "message": "Rejected test-key", "log_id": "failure-123"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(backend.LangSearchError) as caught:
            await backend.search("test", api_key="test-key", client=client)
    message = str(caught.value)
    assert str(status) in message and "failure-123" in message
    assert "test-key" not in message and "[REDACTED]" in message
    assert len(calls) == 1


@pytest.mark.parametrize("failure", [500, 502, 503, 504, "connection", "timeout"])
async def test_transient_failure_retries_then_succeeds(monkeypatch, failure):
    calls, delays = [], []

    async def sleep(delay):
        delays.append(delay)

    monkeypatch.setattr(backend.asyncio, "sleep", sleep)

    def handle(request):
        calls.append(request)
        if len(calls) < 3:
            if failure == "connection":
                raise httpx.ConnectError("connection failed", request=request)
            if failure == "timeout":
                raise httpx.ReadTimeout("timed out", request=request)
            return httpx.Response(failure, json={"msg": "try again"})
        return httpx.Response(200, json=envelope([]))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        result = await backend.search("test", api_key="test-key", client=client)
    assert result["status"] == "empty"
    assert len(calls) == 3 and len(delays) == 2
    assert 0.5 <= delays[0] <= 0.75 and 1 <= delays[1] <= 1.25


async def test_retry_exhaustion_preserves_final_log_id(monkeypatch):
    calls = []

    async def sleep(delay):
        pass

    monkeypatch.setattr(backend.asyncio, "sleep", sleep)

    def handle(request):
        calls.append(request)
        return httpx.Response(503, json={"msg": "temporarily unavailable", "log_id": f"attempt-{len(calls)}"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(backend.LangSearchError, match="HTTP 503.*attempt-3"):
            await backend.search("test", api_key="test-key", client=client)
    assert len(calls) == 3


async def test_request_timeout_is_bounded_and_retries(monkeypatch):
    calls, cancelled = [], []

    async def handle(request):
        calls.append(request)
        try:
            await asyncio.sleep(1)
        finally:
            cancelled.append(True)

    monkeypatch.setattr(backend, "REQUEST_TIMEOUT", 0.01)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(backend.LangSearchError, match="request timed out"):
            await backend.search("test", api_key="test-key", client=client)
    assert len(calls) == len(cancelled) == 3


async def test_api_key_is_redacted_before_truncating_error_text():
    api_key = "REDACTABLE-LANGSEARCH-KEY"
    payload = {"msg": "x" * 490 + api_key, "log_id": "y" * 190 + api_key}
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(401, json=payload))) as client:
        with pytest.raises(backend.LangSearchError) as caught:
            await backend.search("test", api_key=api_key, client=client)
    assert "REDACTABLE" not in str(caught.value)


@pytest.mark.parametrize("status,message", [(200, "invalid JSON"), (403, "HTTP 403")])
async def test_non_json_success_and_error_are_reported_without_body_leaks(status, message):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(status, text="test-key"))) as client:
        with pytest.raises(backend.LangSearchError, match=message) as caught:
            await backend.search("test", api_key="test-key", client=client)
        assert "test-key" not in str(caught.value)


async def test_total_deadline_cancels_pending_request(monkeypatch):
    cancelled = []

    async def handle(request):
        try:
            await asyncio.sleep(1)
        finally:
            cancelled.append(True)

    monkeypatch.setattr(backend, "TOTAL_TIMEOUT", 0.02)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(backend.LangSearchError, match="total time limit"):
            await backend.search("test", api_key="test-key", client=client)
    assert cancelled == [True]


@pytest.mark.parametrize("payload", [[], {"data": None}, {"data": {"webPages": {"value": "invalid"}}},
                                     envelope([{"name": "missing URL"}])])
async def test_malformed_success_is_an_error(payload):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))) as client:
        with pytest.raises(backend.LangSearchError, match="invalid"):
            await backend.search("test", api_key="test-key", client=client)
