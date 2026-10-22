"""One OpenAI-compatible adapter for every endpoint in the lab.

Only status == "ok" results are eligible for scoring. Every other status
is an error and must never be mapped to a disposition.

complete() optionally takes OpenAI-style function tools. Tool calls the model
proposes are returned on Completion.tool_calls; a response that contains only
tool calls is "ok", not "empty". Each tool call keeps the provider's full
original object as "raw", including provider-specific fields such as Gemini's
thought signature, so an agent loop can send it back unchanged.

Transient provider failures (HTTP 5xx, 429, connection errors) are retried
with backoff inside complete(). Timeouts and other API errors are not
retried. Every retry is recorded on the Completion (api_retries,
api_retry_errors) so a retried call stays visible in the run data.

A 429 that names a daily quota, or a 429 that persists through every retry,
raises QuotaExhausted instead of returning an error. The runner stops on it,
so an exhausted quota never fills a run file with error rows.

EndpointConfig is written to run headers and compared on resume after a
JSON round trip, so every field must use JSON-native types (list, not tuple).
"""
from __future__ import annotations

import os
import time
from typing import Any, Callable, Literal

import openai
from pydantic import BaseModel

Status = Literal["ok", "length", "empty", "timeout", "api_error"]
ReasoningSource = Literal["field", "inline", "none"]

LOCAL_PLACEHOLDER_KEY = "ollama"

# APITimeoutError subclasses APIConnectionError, so timeouts are handled
# before this tuple is checked and are never retried.
RETRYABLE_ERRORS = (openai.InternalServerError, openai.RateLimitError, openai.APIConnectionError)


class QuotaExhausted(Exception):
    """Provider quota is spent. The run must stop rather than record errors."""


class EndpointConfig(BaseModel):
    name: str
    base_url: str
    model: str
    api_key_env: str | None = None  # None for local Ollama
    reasoning: bool
    max_tokens: int
    temperature: float | None = None
    top_p: float | None = None
    timeout_s: float = 180.0
    retry_backoff_s: list[float] = [2.0, 8.0, 30.0]  # one entry per retry


class Completion(BaseModel):
    endpoint: str
    model: str
    reasoning_enabled: bool
    status: Status
    content: str = ""
    reasoning: str = ""
    reasoning_source: ReasoningSource = "none"
    finish_reason: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    reasoning_tokens: int | None = None
    latency_s: float
    error: str | None = None
    api_retries: int = 0
    api_retry_errors: list[str] = []
    tool_calls: list[dict[str, Any]] = []


def split_reasoning(message) -> tuple[str, str, ReasoningSource]:
    """Return (content, reasoning, source) from a chat completion message."""
    content = message.content or ""
    field = getattr(message, "reasoning", None) or getattr(message, "reasoning_content", None)
    if field:
        return content.strip(), field.strip(), "field"
    if "</think>" in content:
        before, _, after = content.partition("</think>")
        reasoning = before.replace("<think>", "", 1).strip()
        return after.strip(), reasoning, "inline"
    return content.strip(), "", "none"


def _tool_calls(message) -> list[dict[str, Any]]:
    out = []
    for i, tc in enumerate(getattr(message, "tool_calls", None) or []):
        fn = getattr(tc, "function", None)
        if fn is None:
            continue
        call_id = getattr(tc, "id", None) or f"call_{i}"
        args = fn.arguments or "{}"
        if hasattr(tc, "model_dump"):
            raw = tc.model_dump(exclude_none=True)
        else:
            raw = {"type": "function", "function": {"name": fn.name, "arguments": args}}
        raw["id"] = call_id
        raw.setdefault("type", "function")
        out.append({"id": call_id, "name": fn.name, "arguments": args, "raw": raw})
    return out


def make_client(cfg: EndpointConfig) -> openai.OpenAI:
    if cfg.api_key_env is None:
        key = LOCAL_PLACEHOLDER_KEY
    else:
        key = os.environ.get(cfg.api_key_env)
        if not key:
            raise RuntimeError(f"Environment variable {cfg.api_key_env} is not set. Source ~/ai/env.sh first.")
    return openai.OpenAI(api_key=key, base_url=cfg.base_url, timeout=cfg.timeout_s, max_retries=0)


def _short(e: Exception) -> str:
    return f"{type(e).__name__}: {str(e)[:160]}"


def _is_daily_quota(e: Exception) -> bool:
    return "perday" in str(e).replace(" ", "").replace("_", "").lower()


def complete(
    client: openai.OpenAI,
    cfg: EndpointConfig,
    messages: list[dict],
    sleep: Callable[[float], None] = time.sleep,
    tools: list[dict] | None = None,
) -> Completion:
    kwargs: dict = {"model": cfg.model, "messages": messages, "max_tokens": cfg.max_tokens}
    if cfg.temperature is not None:
        kwargs["temperature"] = cfg.temperature
    if cfg.top_p is not None:
        kwargs["top_p"] = cfg.top_p
    if not cfg.reasoning:
        kwargs["reasoning_effort"] = "none"
    if tools:
        kwargs["tools"] = tools

    base = {"endpoint": cfg.name, "model": cfg.model, "reasoning_enabled": cfg.reasoning}
    retry_errors: list[str] = []

    def failed(status: Status, e: Exception, start: float) -> Completion:
        return Completion(
            **base,
            status=status,
            latency_s=time.perf_counter() - start,
            error=str(e)[:500],
            api_retries=len(retry_errors),
            api_retry_errors=retry_errors,
        )

    while True:
        start = time.perf_counter()
        try:
            r = client.chat.completions.create(**kwargs)
            break
        except openai.APITimeoutError as e:
            return failed("timeout", e, start)
        except RETRYABLE_ERRORS as e:
            rate_limited = isinstance(e, openai.RateLimitError)
            if rate_limited and _is_daily_quota(e):
                raise QuotaExhausted(f"daily quota: {_short(e)}") from e
            if len(retry_errors) >= len(cfg.retry_backoff_s):
                if rate_limited:
                    raise QuotaExhausted(f"429 persisted through {len(retry_errors)} retries: {_short(e)}") from e
                return failed("api_error", e, start)
            wait = cfg.retry_backoff_s[len(retry_errors)]
            retry_errors.append(_short(e))
            sleep(wait)
        except openai.APIError as e:
            return failed("api_error", e, start)
    latency = time.perf_counter() - start  # successful attempt only, excludes backoff

    choice = r.choices[0]
    content, reasoning, source = split_reasoning(choice.message)
    calls = _tool_calls(choice.message)
    if choice.finish_reason == "length":
        status: Status = "length"
    elif not content and not calls:
        status = "empty"
    else:
        status = "ok"

    return Completion(
        **base,
        status=status,
        content=content,
        reasoning=reasoning,
        reasoning_source=source,
        finish_reason=choice.finish_reason,
        prompt_tokens=r.usage.prompt_tokens if r.usage else None,
        completion_tokens=r.usage.completion_tokens if r.usage else None,
        total_tokens=r.usage.total_tokens if r.usage else None,
        reasoning_tokens=hidden_tokens(r.usage),
        latency_s=latency,
        api_retries=len(retry_errors),
        api_retry_errors=retry_errors,
        tool_calls=calls,
    )


def hidden_tokens(usage) -> int | None:
    """Billed tokens missing from prompt + completion.

    Gemini's OpenAI-compatible endpoint leaves thinking out of completion_tokens and
    reports it only in total_tokens. Returns 0 where the total is just the sum.
    """
    if usage is None:
        return None
    parts = (usage.total_tokens, usage.prompt_tokens, usage.completion_tokens)
    if any(x is None for x in parts):
        return None
    return max(0, parts[0] - parts[1] - parts[2])
