"""Tests for LLM classification fallback."""

from __future__ import annotations

from typing import Any

from stronghold.classifier.llm_fallback import llm_classify
from tests.fakes import FakeLLMClient


class TestLLMClassify:
    async def test_returns_valid_category(self) -> None:
        llm = FakeLLMClient()
        llm.set_simple_response("code")
        result = await llm_classify("write a function", llm)
        assert result == "code"

    async def test_strips_and_lowercases(self) -> None:
        llm = FakeLLMClient()
        llm.set_simple_response("  Chat  ")
        result = await llm_classify("hello", llm)
        assert result == "chat"

    async def test_extracts_first_word(self) -> None:
        llm = FakeLLMClient()
        llm.set_simple_response("automation - this is about devices")
        result = await llm_classify("turn on the light", llm)
        assert result == "automation"

    async def test_searches_full_text_for_category(self) -> None:
        llm = FakeLLMClient()
        llm.set_simple_response("I think this is creative writing")
        result = await llm_classify("write a poem", llm)
        assert result == "creative"

    async def test_returns_none_for_invalid_category(self) -> None:
        llm = FakeLLMClient()
        llm.set_simple_response("banana")
        result = await llm_classify("do something", llm)
        assert result is None

    async def test_returns_none_on_empty_response(self) -> None:
        llm = FakeLLMClient()
        llm.set_responses(
            {
                "id": "x",
                "choices": [{"message": {"role": "assistant", "content": ""}}],
                "usage": {},
            }
        )
        result = await llm_classify("text", llm)
        assert result is None

    async def test_returns_none_on_llm_error(self) -> None:
        class BrokenLLM:
            async def complete(self, *a: object, **kw: object) -> dict[str, Any]:
                raise RuntimeError("fail")

        result = await llm_classify("text", BrokenLLM())
        assert result is None

    async def test_truncates_user_text(self) -> None:
        llm = FakeLLMClient()
        llm.set_simple_response("chat")
        await llm_classify("x" * 500, llm)
        prompt_content = llm.calls[0]["messages"][0]["content"]
        # user_text[:200] is used in the prompt, so 500 chars should be truncated
        assert "x" * 201 not in prompt_content

    async def test_max_tokens_and_temperature(self) -> None:
        llm = FakeLLMClient()
        llm.set_simple_response("code")
        await llm_classify("test", llm)
        assert llm.calls[0].get("max_tokens") == 10
        assert llm.calls[0].get("temperature") == 0.0

    async def test_all_valid_categories(self) -> None:
        """Each valid category is accepted."""
        for cat in [
            "chat",
            "code",
            "automation",
            "trading",
            "creative",
            "reasoning",
            "image_gen",
            "search",
            "summarize",
            "embedding",
        ]:
            llm = FakeLLMClient()
            llm.set_simple_response(cat)
            result = await llm_classify("test", llm)
            assert result == cat, f"Category {cat} should be accepted"

    async def test_default_model_is_auto(self) -> None:
        llm = FakeLLMClient()
        llm.set_simple_response("chat")
        await llm_classify("test", llm)
        assert llm.calls[0]["model"] == "auto"
