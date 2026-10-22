"""Retry behavior of adapter.complete() for transient provider failures."""
from types import SimpleNamespace

import httpx
import openai

from evallab.adapter import EndpointConfig, complete

REQ = httpx.Request("POST", "https://example.invalid/v1/chat/completions")


def status_error(cls, code):
    return cls(f"Error code: {code}", response=httpx.Response(code, request=REQ), body=None)


def ok_response(text="{}"):
    msg = SimpleNamespace(content=text, reasoning=None, reasoning_content=None)
    return SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=msg)], usage=None)


def fake_client(outcomes):
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        o = outcomes[len(calls) - 1]
        if isinstance(o, Exception):
            raise o
        return o

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    return client, calls


CFG = EndpointConfig(name="t", base_url="https://example.invalid/v1", model="m", reasoning=True, max_tokens=10)


def run(outcomes):
    client, calls = fake_client(outcomes)
    waits = []
    c = complete(client, CFG, [{"role": "user", "content": "x"}], sleep=waits.append)
    return c, calls, waits


def test_502_then_success_is_ok_and_recorded():
    c, calls, waits = run([status_error(openai.InternalServerError, 502), ok_response()])
    assert c.status == "ok"
    assert c.api_retries == 1 and len(calls) == 2 and waits == [2.0]
    assert c.api_retry_errors[0].startswith("InternalServerError")


def test_persistent_502_gives_api_error_after_all_retries():
    c, calls, waits = run([status_error(openai.InternalServerError, 502)] * 4)
    assert c.status == "api_error"
    assert c.api_retries == 3 and len(calls) == 4 and waits == [2.0, 8.0, 30.0]


def test_429_is_retried():
    c, calls, _ = run([status_error(openai.RateLimitError, 429), ok_response()])
    assert c.status == "ok" and c.api_retries == 1 and len(calls) == 2


def test_connection_error_is_retried():
    c, calls, _ = run([openai.APIConnectionError(request=REQ), ok_response()])
    assert c.status == "ok" and c.api_retries == 1 and len(calls) == 2


def test_timeout_is_not_retried():
    c, calls, waits = run([openai.APITimeoutError(request=REQ), ok_response()])
    assert c.status == "timeout" and c.api_retries == 0 and len(calls) == 1 and waits == []


def test_400_is_not_retried():
    c, calls, waits = run([status_error(openai.BadRequestError, 400), ok_response()])
    assert c.status == "api_error" and c.api_retries == 0 and len(calls) == 1 and waits == []


def test_clean_call_records_zero_retries():
    c, calls, waits = run([ok_response()])
    assert c.status == "ok" and c.api_retries == 0 and c.api_retry_errors == [] and waits == []
