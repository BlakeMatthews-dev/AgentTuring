"""Tests for LiteLLMClient with model fallback behavior.

Uses respx to mock LiteLLM proxy HTTP responses. HTTP is an external boundary
so mocking httpx is appropriate — but assertions focus on *behavioral* outcomes
(which model answered, what error surfaced, what body was sent), not on
`mock.call_count` tautologies. The local `call_count` / `tried` counters
capture the sequence of attempts so we can verify that fallback actually
cascaded through the model list.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from stronghold.api.litellm_client import LiteLLMClient


# ── Helpers ──────────────────────────────────────────────────────────


def _success_response(content: str = "Hello!", model: str = "test-model") -> dict[str, Any]:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


def _make_client() -> LiteLLMClient:
    return LiteLLMClient(base_url="http://fake:4000", api_key="sk-test")


def _extract_request_model(call: Any) -> str:
    """Parse the `model` field out of a respx recorded request body."""
    return json.loads(call.request.content)["model"]


# ── Successful completion ───────────────────────────────────────────


class TestSuccessfulCompletion:
    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_parsed_json_and_sends_message_body(self) -> None:
        client = _make_client()
        route = respx.post("http://fake:4000/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=_success_response("Hello!")),
        )

        result = await client.complete(
            [{"role": "user", "content": "hello"}],
            "test-model",
        )

        assert result["choices"][0]["message"]["content"] == "Hello!"
        assert result["object"] == "chat.completion"
        # Body was serialized with the expected shape
        body = json.loads(route.calls[0].request.content)
        assert body["model"] == "test-model"
        assert body["messages"] == [{"role": "user", "content": "hello"}]

    @pytest.mark.asyncio
    @respx.mock
    async def test_tools_are_forwarded_in_body(self) -> None:
        client = _make_client()
        tools = [{"type": "function", "function": {"name": "test_tool"}}]
        route = respx.post("http://fake:4000/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=_success_response()),
        )

        await client.complete(
            [{"role": "user", "content": "hello"}],
            "test-model",
            tools=tools,
        )

        body = json.loads(route.calls[0].request.content)
        assert body["tools"] == tools


# ── Fallback on retryable errors ────────────────────────────────────


class TestFallbackOnRetryableErrors:
    """Retryable: 400 (cooldown), 422 (tools unsupported), 429, 500, 502, 503."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [429, 500, 502, 503, 422])
    @respx.mock
    async def test_status_triggers_fallback_to_next_model(self, status: int) -> None:
        client = _make_client()
        tried: list[str] = []

        def side_effect(request: httpx.Request) -> httpx.Response:
            model = json.loads(request.content)["model"]
            tried.append(model)
            if model == "primary":
                return httpx.Response(status, json={"error": f"status {status}"})
            return httpx.Response(200, json=_success_response("fallback ok", model=model))

        respx.post("http://fake:4000/v1/chat/completions").mock(side_effect=side_effect)

        result = await client.complete(
            [{"role": "user", "content": "hello"}],
            "primary",
            fallback_models=["fallback"],
        )

        # Both primary and fallback were attempted, in order
        assert tried == ["primary", "fallback"]
        # And the response came from the fallback model
        assert result["choices"][0]["message"]["content"] == "fallback ok"
        assert result["model"] == "fallback"


class TestFallbackOnConnectError:
    @pytest.mark.asyncio
    @respx.mock
    async def test_connect_error_triggers_fallback(self) -> None:
        client = _make_client()
        tried: list[str] = []

        def side_effect(request: httpx.Request) -> httpx.Response:
            model = json.loads(request.content)["model"]
            tried.append(model)
            if model == "primary":
                raise httpx.ConnectError("Connection refused")
            return httpx.Response(200, json=_success_response("fallback ok", model=model))

        respx.post("http://fake:4000/v1/chat/completions").mock(side_effect=side_effect)

        result = await client.complete(
            [{"role": "user", "content": "hello"}],
            "primary",
            fallback_models=["fallback"],
        )

        assert tried == ["primary", "fallback"]
        assert result["choices"][0]["message"]["content"] == "fallback ok"


# ── All models exhausted ────────────────────────────────────────────


class TestAllModelsFail:
    @pytest.mark.asyncio
    @respx.mock
    async def test_429_on_every_model_raises_final_http_error(self) -> None:
        client = _make_client()
        tried: list[str] = []

        def side_effect(request: httpx.Request) -> httpx.Response:
            tried.append(json.loads(request.content)["model"])
            return httpx.Response(429, json={"error": "rate limited"})

        respx.post("http://fake:4000/v1/chat/completions").mock(side_effect=side_effect)
        # No phase-2 fallbacks available
        respx.get("http://fake:4000/v1/models").mock(
            return_value=httpx.Response(200, json={"data": []}),
        )

        with pytest.raises(httpx.HTTPStatusError) as excinfo:
            await client.complete(
                [{"role": "user", "content": "hello"}],
                "model-a",
                fallback_models=["model-b", "model-c"],
            )

        # All three explicit models were attempted
        assert tried == ["model-a", "model-b", "model-c"]
        assert excinfo.value.response.status_code == 429

    @pytest.mark.asyncio
    @respx.mock
    async def test_connect_error_on_every_model_raises_connect_error(self) -> None:
        client = _make_client()
        tried: list[str] = []

        def side_effect(request: httpx.Request) -> httpx.Response:
            tried.append(json.loads(request.content)["model"])
            raise httpx.ConnectError("refused")

        respx.post("http://fake:4000/v1/chat/completions").mock(side_effect=side_effect)
        respx.get("http://fake:4000/v1/models").mock(
            return_value=httpx.Response(200, json={"data": []}),
        )

        with pytest.raises(httpx.ConnectError):
            await client.complete(
                [{"role": "user", "content": "hello"}],
                "model-a",
                fallback_models=["model-b"],
            )
        assert tried == ["model-a", "model-b"]


# ── Non-retryable status codes ──────────────────────────────────────


class TestNonRetryableErrors:
    """401 (auth) must raise immediately without trying any fallbacks."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_401_raises_immediately_and_skips_fallbacks(self) -> None:
        client = _make_client()
        tried: list[str] = []

        def side_effect(request: httpx.Request) -> httpx.Response:
            tried.append(json.loads(request.content)["model"])
            return httpx.Response(401, json={"error": "unauthorized"})

        respx.post("http://fake:4000/v1/chat/completions").mock(side_effect=side_effect)

        with pytest.raises(httpx.HTTPStatusError) as excinfo:
            await client.complete(
                [{"role": "user", "content": "hello"}],
                "model-a",
                fallback_models=["model-b"],
            )
        # Only the primary was tried; fallback was NOT attempted
        assert tried == ["model-a"]
        assert excinfo.value.response.status_code == 401

    @pytest.mark.asyncio
    @respx.mock
    async def test_400_is_retryable_and_does_cascade_through_fallbacks(self) -> None:
        """400 is retryable because LiteLLM uses it for cooldown responses."""
        client = _make_client()
        tried: list[str] = []

        def side_effect(request: httpx.Request) -> httpx.Response:
            tried.append(json.loads(request.content)["model"])
            return httpx.Response(400, json={"error": "cooldown"})

        respx.post("http://fake:4000/v1/chat/completions").mock(side_effect=side_effect)
        respx.get("http://fake:4000/v1/models").mock(
            return_value=httpx.Response(200, json={"data": []}),
        )

        with pytest.raises(httpx.HTTPStatusError):
            await client.complete(
                [{"role": "user", "content": "hello"}],
                "model-a",
                fallback_models=["model-b"],
            )
        # Both primary and fallback were attempted (400 retryable)
        assert tried == ["model-a", "model-b"]


# ── Dynamic fallback models ──────────────────────────────────────────


class TestDynamicFallbackModels:
    """Container can set `_fallback_models` post-construction; client uses them."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_fallback_attribute_is_consulted_when_no_arg_passed(self) -> None:
        client = _make_client()
        client._fallback_models = ["dynamic-fallback"]  # type: ignore[attr-defined]
        tried: list[str] = []

        def side_effect(request: httpx.Request) -> httpx.Response:
            model = json.loads(request.content)["model"]
            tried.append(model)
            if model == "primary":
                return httpx.Response(429, json={"error": "rate limited"})
            return httpx.Response(200, json=_success_response("dynamic ok", model=model))

        respx.post("http://fake:4000/v1/chat/completions").mock(side_effect=side_effect)

        result = await client.complete(
            [{"role": "user", "content": "hello"}],
            "primary",
        )

        assert tried == ["primary", "dynamic-fallback"]
        assert result["choices"][0]["message"]["content"] == "dynamic ok"


# ── Phase-2 fallback (fetch /v1/models) ─────────────────────────────


class TestPhase2FallbackFromModelList:
    """After explicit fallbacks fail, client fetches /v1/models and tries each."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_rescue_model_from_v1_models_is_attempted(self) -> None:
        client = _make_client()
        tried: list[str] = []

        def side_effect(request: httpx.Request) -> httpx.Response:
            model = json.loads(request.content)["model"]
            tried.append(model)
            # primary + explicit fallback fail; rescue model succeeds
            if model in ("primary", "fallback-1"):
                return httpx.Response(429, json={"error": "rate limited"})
            return httpx.Response(200, json=_success_response("phase2 ok", model=model))

        respx.post("http://fake:4000/v1/chat/completions").mock(side_effect=side_effect)
        respx.get("http://fake:4000/v1/models").mock(
            return_value=httpx.Response(200, json={
                "data": [
                    {"id": "primary"},
                    {"id": "fallback-1"},
                    {"id": "rescue-model"},
                ],
            }),
        )

        result = await client.complete(
            [{"role": "user", "content": "hello"}],
            "primary",
            fallback_models=["fallback-1"],
        )

        # Cascade order: primary, explicit fallback, then rescue from /v1/models
        assert tried == ["primary", "fallback-1", "rescue-model"]
        assert result["choices"][0]["message"]["content"] == "phase2 ok"

    @pytest.mark.asyncio
    @respx.mock
    async def test_already_tried_models_are_not_retried_in_phase_2(self) -> None:
        client = _make_client()
        tried: list[str] = []

        def side_effect(request: httpx.Request) -> httpx.Response:
            tried.append(json.loads(request.content)["model"])
            return httpx.Response(429, json={"error": "rate limited"})

        respx.post("http://fake:4000/v1/chat/completions").mock(side_effect=side_effect)
        # /v1/models only returns the same model already attempted
        respx.get("http://fake:4000/v1/models").mock(
            return_value=httpx.Response(200, json={"data": [{"id": "primary"}]}),
        )

        with pytest.raises(httpx.HTTPStatusError):
            await client.complete(
                [{"role": "user", "content": "hello"}],
                "primary",
            )

        # Only tried primary once, not twice (dedupe in phase 2)
        assert tried == ["primary"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_v1_models_failure_still_surfaces_original_error(self) -> None:
        client = _make_client()

        respx.post("http://fake:4000/v1/chat/completions").mock(
            return_value=httpx.Response(429, json={"error": "rate limited"}),
        )
        respx.get("http://fake:4000/v1/models").mock(
            return_value=httpx.Response(500, json={"error": "internal"}),
        )

        with pytest.raises(httpx.HTTPStatusError) as excinfo:
            await client.complete(
                [{"role": "user", "content": "hello"}],
                "primary",
            )
        # Raises the chat-completion 429, not the /v1/models 500
        assert excinfo.value.response.status_code == 429


# ── Streaming ───────────────────────────────────────────────────────


class TestStreamMethod:
    @pytest.mark.asyncio
    @respx.mock
    async def test_stream_yields_sse_chunks_containing_content_and_done(self) -> None:
        client = _make_client()
        sse_data = 'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\ndata: [DONE]\n\n'

        respx.post("http://fake:4000/v1/chat/completions").mock(
            return_value=httpx.Response(200, text=sse_data),
        )

        chunks: list[str] = []
        async for chunk in client.stream(
            [{"role": "user", "content": "hi"}],
            "test-model",
        ):
            chunks.append(chunk)

        combined = "".join(chunks)
        assert "Hello" in combined
        assert "[DONE]" in combined


# ── Optional params forwarded to body ──────────────────────────────


class TestCompleteOptionalParams:
    @pytest.mark.asyncio
    @respx.mock
    async def test_max_tokens_temperature_metadata_tool_choice_in_body(self) -> None:
        client = _make_client()
        route = respx.post("http://fake:4000/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=_success_response("ok")),
        )

        await client.complete(
            [{"role": "user", "content": "hello"}],
            "test-model",
            max_tokens=500,
            temperature=0.7,
            metadata={"user": "test"},
            tool_choice="auto",
        )

        body = json.loads(route.calls[0].request.content)
        assert body["max_tokens"] == 500
        assert body["temperature"] == 0.7
        assert body["metadata"] == {"user": "test"}
        assert body["tool_choice"] == "auto"


# ── No models available ─────────────────────────────────────────────


class TestNoModelsAvailable:
    @pytest.mark.asyncio
    @respx.mock
    async def test_connect_error_with_empty_model_list_raises_connect_error(self) -> None:
        client = _make_client()

        respx.post("http://fake:4000/v1/chat/completions").mock(
            side_effect=httpx.ConnectError("refused"),
        )
        respx.get("http://fake:4000/v1/models").mock(
            return_value=httpx.Response(200, json={"data": []}),
        )

        with pytest.raises(httpx.ConnectError):
            await client.complete(
                [{"role": "user", "content": "hello"}],
                "only-model",
            )
