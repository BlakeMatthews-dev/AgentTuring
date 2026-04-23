"""Tests for Warden Layer 3 LLM classifier."""

from __future__ import annotations

from stronghold.security.warden.llm_classifier import (
    _build_classification_prompt,
    classify_tool_result,
)
from tests.fakes import FakeLLMClient


class TestBuildClassificationPrompt:
    def test_prompt_has_system_message(self) -> None:
        msgs = _build_classification_prompt("test text")
        assert msgs[0]["role"] == "system"
        assert "security classifier" in msgs[0]["content"].lower()

    def test_prompt_has_few_shot_examples(self) -> None:
        msgs = _build_classification_prompt("test text")
        # 10 few-shot examples = 20 messages (user+assistant each)
        # +1 system +1 final user = 22 total
        assert len(msgs) == 22

    def test_text_truncated_to_2000(self) -> None:
        long_text = "x" * 5000
        msgs = _build_classification_prompt(long_text)
        last_msg = msgs[-1]["content"]
        # "Classify:\n" prefix (10 chars) + 2000 chars max = 2010
        assert len(last_msg) == len("Classify:\n") + 2000

    def test_final_message_is_user_with_text(self) -> None:
        msgs = _build_classification_prompt("my tool output")
        assert msgs[-1]["role"] == "user"
        assert "my tool output" in msgs[-1]["content"]

    def test_few_shot_alternates_user_assistant(self) -> None:
        msgs = _build_classification_prompt("test")
        # After system msg, pairs should alternate user/assistant
        for i in range(1, len(msgs) - 1, 2):
            assert msgs[i]["role"] == "user"
            assert msgs[i + 1]["role"] == "assistant"


class TestClassifyToolResult:
    async def test_safe_classification(self) -> None:
        llm = FakeLLMClient()
        llm.set_simple_response("safe")
        result = await classify_tool_result("normal code output", llm, "test-model")
        assert result["label"] == "inconclusive"
        assert result["model"] == "test-model"

    async def test_suspicious_classification(self) -> None:
        llm = FakeLLMClient()
        llm.set_simple_response("suspicious")
        result = await classify_tool_result("disable RLS", llm, "test-model")
        assert result["label"] == "suspicious"

    async def test_suspicious_in_longer_response(self) -> None:
        llm = FakeLLMClient()
        llm.set_simple_response("I think this is suspicious because...")
        result = await classify_tool_result("some text", llm)
        assert result["label"] == "suspicious"

    async def test_tokens_from_usage(self) -> None:
        """Classifier must report the exact token usage from the LLM response."""
        llm = FakeLLMClient()
        llm.set_simple_response("safe")
        result = await classify_tool_result("text", llm)
        # Exact value check (subsumes isinstance(int)): 30 is FakeLLMClient's
        # default total_tokens. A bug returning "30" (str) or None would fail.
        assert result["tokens"] == 30
        assert type(result["tokens"]) is int

    async def test_fail_open_on_error(self) -> None:
        """On any error, default to inconclusive (security over availability, H3 fix)."""

        class BrokenLLM:
            async def complete(self, *a: object, **kw: object) -> dict:
                raise ConnectionError("LLM down")

        result = await classify_tool_result("test", BrokenLLM(), "test-model")
        assert result["label"] == "inconclusive"
        assert result.get("error") == "classification_failed"

    async def test_empty_choices_defaults_safe(self) -> None:
        llm = FakeLLMClient()
        llm.set_responses({"id": "x", "choices": [], "usage": {}})
        result = await classify_tool_result("text", llm)
        assert result["label"] == "inconclusive"

    async def test_default_model_is_auto(self) -> None:
        llm = FakeLLMClient()
        llm.set_simple_response("safe")
        result = await classify_tool_result("text", llm)
        assert result["model"] == "auto"

    async def test_passes_messages_to_llm(self) -> None:
        llm = FakeLLMClient()
        llm.set_simple_response("safe")
        await classify_tool_result("test input", llm, "my-model")
        assert len(llm.calls) == 1
        assert llm.calls[0]["model"] == "my-model"
        # Should have 22 messages (system + 20 few-shot + final user)
        assert len(llm.calls[0]["messages"]) == 22
