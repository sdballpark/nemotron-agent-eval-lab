"""One OpenAI-compatible adapter for every endpoint in the lab.

Only status == "ok" results are eligible for scoring. Every other status
is an error and must never be mapped to a disposition.
"""
from __future__ import annotations

import os
import time
from typing import Literal

import openai
from pydantic import BaseModel

Status = Literal["ok", "length", "empty", "timeout", "api_error"]
ReasoningSource = Literal["field", "inline", "none"]

LOCAL_PLACEHOLDER_KEY = "ollama"


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
    latency_s: float
    error: str | None = None


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


def make_client(cfg: EndpointConfig) -> openai.OpenAI:
    if cfg.api_key_env is None:
        key = LOCAL_PLACEHOLDER_KEY
    else:
        key = os.environ.get(cfg.api_key_env)
        if not key:
            raise RuntimeError(f"Environment variable {cfg.api_key_env} is not set. Source ~/ai/env.sh first.")
    return openai.OpenAI(api_key=key, base_url=cfg.base_url, timeout=cfg.timeout_s, max_retries=0)


def complete(client: openai.OpenAI, cfg: EndpointConfig, messages: list[dict]) -> Completion:
    kwargs: dict = {"model": cfg.model, "messages": messages, "max_tokens": cfg.max_tokens}
    if cfg.temperature is not None:
        kwargs["temperature"] = cfg.temperature
    if cfg.top_p is not None:
        kwargs["top_p"] = cfg.top_p
    if not cfg.reasoning:
        kwargs["reasoning_effort"] = "none"

    base = {"endpoint": cfg.name, "model": cfg.model, "reasoning_enabled": cfg.reasoning}
    start = time.perf_counter()
    try:
        r = client.chat.completions.create(**kwargs)
    except openai.APITimeoutError as e:
        return Completion(**base, status="timeout", latency_s=time.perf_counter() - start, error=str(e)[:500])
    except openai.APIError as e:
        return Completion(**base, status="api_error", latency_s=time.perf_counter() - start, error=str(e)[:500])
    latency = time.perf_counter() - start

    choice = r.choices[0]
    content, reasoning, source = split_reasoning(choice.message)
    if choice.finish_reason == "length":
        status: Status = "length"
    elif not content:
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
        latency_s=latency,
    )
