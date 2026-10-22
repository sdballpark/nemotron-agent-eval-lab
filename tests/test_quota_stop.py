"""A spent quota must stop the run, never become an error row."""
from types import SimpleNamespace

import httpx
import openai
import pytest

from evallab.adapter import EndpointConfig, QuotaExhausted, complete

REQ = httpx.Request("POST", "https://example.invalid/v1/chat/completions")
CFG = EndpointConfig(name="t", base_url="https://example.invalid/v1", model="m", reasoning=True, max_tokens=10)


def rate_error(text="Error code: 429 - You exceeded your current quota"):
    return openai.RateLimitError(text, response=httpx.Response(429, request=REQ), body=None)


def ok_response():
    msg = SimpleNamespace(content="{}", reasoning=None, reasoning_content=None)
    return SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=msg)], usage=None)


def run(outcomes):
    calls, waits = [], []

    def create(**kwargs):
        calls.append(kwargs)
        o = outcomes[len(calls) - 1]
        if isinstance(o, Exception):
            raise o
        return o

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    return lambda: complete(client, CFG, [{"role": "user", "content": "x"}], sleep=waits.append), calls, waits


def test_daily_quota_raises_immediately_without_retry():
    call, calls, waits = run([rate_error("429 quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier"), ok_response()])
    with pytest.raises(QuotaExhausted):
        call()
    assert len(calls) == 1 and waits == []


def test_persistent_429_raises_after_all_retries():
    call, calls, waits = run([rate_error()] * 4)
    with pytest.raises(QuotaExhausted):
        call()
    assert len(calls) == 4 and waits == [2.0, 8.0, 30.0]


def test_transient_429_still_recovers():
    call, calls, _ = run([rate_error(), ok_response()])
    c = call()
    assert c.status == "ok" and c.api_retries == 1 and len(calls) == 2


def test_persistent_502_still_returns_api_error_not_quota():
    err = openai.InternalServerError("Error code: 502", response=httpx.Response(502, request=REQ), body=None)
    call, calls, _ = run([err] * 4)
    c = call()
    assert c.status == "api_error" and c.api_retries == 3
