"""Tests for LiteLLMClient with model fallback behavior.

Uses httpx mock to simulate LiteLLM proxy responses and failures.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from unittest.mock import AsyncMock, MagicMock, patch

from stronghold.api.litellm_client import LiteLLMClient


def _mock_response(status_code: int = 200, json_data: dict | None = None) -> httpx.Response:
    """Build a mock httpx.Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.request = MagicMock()
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            str(status_code),
            request=resp.request,
            response=resp,
        )
    return resp


def _success_response(content: str = "Hello!") -> dict:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "model": "test-model",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


class TestSuccessfulCompletion:
    @pytest.mark.asyncio
    async def test_returns_parsed_json(self) -> None:
        client = LiteLLMClient(base_url="http://fake:4000", api_key="sk-test")
        expected = _success_response("Hello!")

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = expected
            mock_client.post = AsyncMock(return_value=mock_resp)

            result = await client.complete(
                [{"role": "user", "content": "hello"}],
                "test-model",
            )
        assert result["choices"][0]["message"]["content"] == "Hello!"
        assert result["object"] == "chat.completion"

    @pytest.mark.asyncio
    async def test_passes_tools_to_body(self) -> None:
        client = LiteLLMClient(base_url="http://fake:4000", api_key="sk-test")
        tools = [{"type": "function", "function": {"name": "test_tool"}}]

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = _success_response()
            mock_client.post = AsyncMock(return_value=mock_resp)

            await client.complete(
                [{"role": "user", "content": "hello"}],
                "test-model",
                tools=tools,
            )
            call_args = mock_client.post.call_args
            body = call_args.kwargs.get("json", {})
            assert "tools" in body


class TestModelFallbackOn429:
    @pytest.mark.asyncio
    async def test_429_triggers_fallback(self) -> None:
        client = LiteLLMClient(base_url="http://fake:4000", api_key="sk-test")
        call_count = 0

        async def mock_post(url: str, **kwargs: object) -> MagicMock:
            nonlocal call_count
            call_count += 1
            resp = MagicMock()
            resp.request = MagicMock()
            if call_count == 1:
                resp.status_code = 429
            else:
                resp.status_code = 200
                resp.json.return_value = _success_response("fallback worked")
            return resp

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(side_effect=mock_post)

            result = await client.complete(
                [{"role": "user", "content": "hello"}],
                "primary-model",
                fallback_models=["fallback-model"],
            )
        assert result["choices"][0]["message"]["content"] == "fallback worked"
        assert call_count == 2


class TestModelFallbackOn500:
    @pytest.mark.asyncio
    async def test_500_triggers_fallback(self) -> None:
        client = LiteLLMClient(base_url="http://fake:4000", api_key="sk-test")
        call_count = 0

        async def mock_post(url: str, **kwargs: object) -> MagicMock:
            nonlocal call_count
            call_count += 1
            resp = MagicMock()
            resp.request = MagicMock()
            if call_count == 1:
                resp.status_code = 500
            else:
                resp.status_code = 200
                resp.json.return_value = _success_response("recovered")
            return resp

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(side_effect=mock_post)

            result = await client.complete(
                [{"role": "user", "content": "hello"}],
                "primary-model",
                fallback_models=["fallback-model"],
            )
        assert result["choices"][0]["message"]["content"] == "recovered"

    @pytest.mark.asyncio
    async def test_502_triggers_fallback(self) -> None:
        client = LiteLLMClient(base_url="http://fake:4000", api_key="sk-test")
        call_count = 0

        async def mock_post(url: str, **kwargs: object) -> MagicMock:
            nonlocal call_count
            call_count += 1
            resp = MagicMock()
            resp.request = MagicMock()
            if call_count == 1:
                resp.status_code = 502
            else:
                resp.status_code = 200
                resp.json.return_value = _success_response("ok")
            return resp

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(side_effect=mock_post)

            result = await client.complete(
                [{"role": "user", "content": "hello"}],
                "primary",
                fallback_models=["fallback"],
            )
        assert result["choices"][0]["message"]["content"] == "ok"

    @pytest.mark.asyncio
    async def test_503_triggers_fallback(self) -> None:
        client = LiteLLMClient(base_url="http://fake:4000", api_key="sk-test")
        call_count = 0

        async def mock_post(url: str, **kwargs: object) -> MagicMock:
            nonlocal call_count
            call_count += 1
            resp = MagicMock()
            resp.request = MagicMock()
            if call_count == 1:
                resp.status_code = 503
            else:
                resp.status_code = 200
                resp.json.return_value = _success_response("ok")
            return resp

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(side_effect=mock_post)

            result = await client.complete(
                [{"role": "user", "content": "hello"}],
                "primary",
                fallback_models=["fallback"],
            )
        assert result["choices"][0]["message"]["content"] == "ok"


class TestConnectionError:
    @pytest.mark.asyncio
    async def test_connect_error_triggers_fallback(self) -> None:
        client = LiteLLMClient(base_url="http://fake:4000", api_key="sk-test")
        call_count = 0

        async def mock_post(url: str, **kwargs: object) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise httpx.ConnectError("Connection refused")
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = _success_response("fallback ok")
            return resp

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(side_effect=mock_post)

            result = await client.complete(
                [{"role": "user", "content": "hello"}],
                "primary",
                fallback_models=["fallback"],
            )
        assert result["choices"][0]["message"]["content"] == "fallback ok"


class TestAllModelsFail:
    @pytest.mark.asyncio
    async def test_all_models_fail_raises_last_error(self) -> None:
        client = LiteLLMClient(base_url="http://fake:4000", api_key="sk-test")

        async def mock_post(url: str, **kwargs: object) -> MagicMock:
            resp = MagicMock()
            resp.status_code = 429
            resp.request = MagicMock()
            return resp

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(side_effect=mock_post)

            with pytest.raises(httpx.HTTPStatusError):
                await client.complete(
                    [{"role": "user", "content": "hello"}],
                    "model-a",
                    fallback_models=["model-b", "model-c"],
                )

    @pytest.mark.asyncio
    async def test_all_connect_errors_raises(self) -> None:
        client = LiteLLMClient(base_url="http://fake:4000", api_key="sk-test")

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))

            with pytest.raises(httpx.ConnectError):
                await client.complete(
                    [{"role": "user", "content": "hello"}],
                    "model-a",
                    fallback_models=["model-b"],
                )


class TestNonRetryableErrors:
    @respx.mock
    async def test_400_is_retryable(self) -> None:
        """400 is retryable because LiteLLM uses it for cooldown responses."""
        client = LiteLLMClient(base_url="http://fake:4000", api_key="sk-test")
        # Both models return 400 — should try both then raise
        route = respx.post("http://fake:4000/v1/chat/completions").mock(
            return_value=httpx.Response(400, json={"error": "cooldown"}),
        )
        # Also mock /v1/models to return empty (no further fallbacks)
        respx.get("http://fake:4000/v1/models").mock(
            return_value=httpx.Response(200, json={"data": []}),
        )
        with pytest.raises(httpx.HTTPStatusError):
            await client.complete(
                [{"role": "user", "content": "hello"}],
                "model-a",
                fallback_models=["model-b"],
            )
        # Should have tried both models (400 is retryable)
        assert route.call_count == 2

    @pytest.mark.asyncio
    async def test_401_raises_immediately(self) -> None:
        client = LiteLLMClient(base_url="http://fake:4000", api_key="sk-test")

        async def mock_post(url: str, **kwargs: object) -> MagicMock:
            resp = MagicMock()
            resp.status_code = 401
            resp.request = MagicMock()
            resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                "401",
                request=resp.request,
                response=resp,
            )
            return resp

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(side_effect=mock_post)

            with pytest.raises(httpx.HTTPStatusError):
                await client.complete(
                    [{"role": "user", "content": "hello"}],
                    "model-a",
                    fallback_models=["model-b"],
                )
            assert mock_client.post.call_count == 1


class TestDynamicFallbackModels:
    @pytest.mark.asyncio
    async def test_uses_fallback_models_attribute(self) -> None:
        """Container sets _fallback_models dynamically; client should use them."""
        client = LiteLLMClient(base_url="http://fake:4000", api_key="sk-test")
        client._fallback_models = ["dynamic-fallback"]  # type: ignore[attr-defined]
        call_count = 0

        async def mock_post(url: str, **kwargs: object) -> MagicMock:
            nonlocal call_count
            call_count += 1
            resp = MagicMock()
            resp.request = MagicMock()
            if call_count == 1:
                resp.status_code = 429
            else:
                resp.status_code = 200
                resp.json.return_value = _success_response("dynamic ok")
            return resp

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(side_effect=mock_post)

            result = await client.complete(
                [{"role": "user", "content": "hello"}],
                "primary",
            )
        assert result["choices"][0]["message"]["content"] == "dynamic ok"
        assert call_count == 2
