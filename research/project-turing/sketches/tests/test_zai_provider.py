"""Tests for runtime/providers/zai.py with httpx mocked via respx."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from turing.runtime.providers.base import (
    ProviderUnavailable,
    RateLimited,
)
from turing.runtime.providers.zai import DEFAULT_BASE_URL, ZaiProvider


def _url() -> str:
    return f"{DEFAULT_BASE_URL}/chat/completions"


def _reply(text: str) -> dict:
    return {
        "choices": [
            {"message": {"role": "assistant", "content": text}},
        ]
    }


@respx.mock
def test_complete_happy_path() -> None:
    respx.post(_url()).mock(
        return_value=httpx.Response(200, json=_reply("hello from z.ai"))
    )
    provider = ZaiProvider(api_key="sk-example-xxx")
    assert provider.complete("prompt") == "hello from z.ai"


@respx.mock
def test_429_raises_rate_limited() -> None:
    respx.post(_url()).mock(return_value=httpx.Response(429))
    provider = ZaiProvider(api_key="sk-example-xxx")
    with pytest.raises(RateLimited):
        provider.complete("prompt")


@respx.mock
def test_authorization_header_and_body_shape() -> None:
    route = respx.post(_url()).mock(
        return_value=httpx.Response(200, json=_reply("ok"))
    )
    provider = ZaiProvider(api_key="sk-example-xxx")
    provider.complete("question?", max_tokens=64)

    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer sk-example-xxx"
    body = json.loads(request.content.decode())
    assert body["messages"][0]["content"] == "question?"
    assert body["max_tokens"] == 64


def test_api_key_required() -> None:
    with pytest.raises(ValueError, match="api_key"):
        ZaiProvider(api_key="")


@respx.mock
def test_quota_window_rolling_hours() -> None:
    respx.post(_url()).mock(
        return_value=httpx.Response(200, json=_reply("x"))
    )
    provider = ZaiProvider(api_key="sk-example-xxx")
    window = provider.quota_window()
    assert window is not None
    assert window.window_kind == "rolling_hours"
    assert window.tokens_used == 0

    provider.complete("some prompt")
    window2 = provider.quota_window()
    assert window2.tokens_used > 0
