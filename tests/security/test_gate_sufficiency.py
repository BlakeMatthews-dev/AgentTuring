"""Tests for Gate execution modes with request sufficiency integration."""

import pytest

from stronghold.security.gate import Gate


class TestPersistentMode:
    """Persistent mode checks sufficiency and returns clarifying questions."""

    @pytest.mark.asyncio
    async def test_insufficient_code_request_returns_questions(self) -> None:
        """A vague code request in persistent mode gets clarifying questions."""
        gate = Gate()
        result = await gate.process_input(
            "fix the thing",
            execution_mode="persistent",
            task_type="code",
        )
        assert not result.blocked
        assert len(result.clarifying_questions) > 0

    @pytest.mark.asyncio
    async def test_sufficient_code_request_passes(self) -> None:
        """A detailed code request in persistent mode passes through."""
        gate = Gate()
        result = await gate.process_input(
            "Fix the authentication bug in auth.py — the JWT validation "
            "should return 401 when the token is expired",
            execution_mode="persistent",
            task_type="code",
        )
        assert not result.blocked
        assert len(result.clarifying_questions) == 0

    @pytest.mark.asyncio
    async def test_automation_short_command_passes(self) -> None:
        """Automation commands are sufficient with device + action."""
        gate = Gate()
        result = await gate.process_input(
            "turn on bedroom light",
            execution_mode="persistent",
            task_type="automation",
        )
        assert len(result.clarifying_questions) == 0

    @pytest.mark.asyncio
    async def test_automation_too_short_asks(self) -> None:
        """Very short automation command gets a question."""
        gate = Gate()
        result = await gate.process_input(
            "on",
            execution_mode="persistent",
            task_type="automation",
        )
        assert len(result.clarifying_questions) > 0

    @pytest.mark.asyncio
    async def test_search_almost_always_sufficient(self) -> None:
        gate = Gate()
        result = await gate.process_input(
            "python tutorials",
            execution_mode="persistent",
            task_type="search",
        )
        assert len(result.clarifying_questions) == 0

    @pytest.mark.asyncio
    async def test_chat_always_passes(self) -> None:
        gate = Gate()
        result = await gate.process_input(
            "hello",
            execution_mode="persistent",
            task_type="chat",
        )
        assert len(result.clarifying_questions) == 0


class TestSupervisedMode:
    """Supervised mode always returns questions, even for sufficient requests."""

    @pytest.mark.asyncio
    async def test_sufficient_request_still_asks(self) -> None:
        gate = Gate()
        result = await gate.process_input(
            "Fix the authentication bug in auth.py — return 401 on expired JWT",
            execution_mode="supervised",
            task_type="code",
        )
        assert len(result.clarifying_questions) > 0
        # Should include a "proceed?" confirmation
        q_texts = [q.question for q in result.clarifying_questions]
        assert any("proceed" in q.lower() or "should" in q.lower() for q in q_texts)

    @pytest.mark.asyncio
    async def test_insufficient_request_gets_detail_questions(self) -> None:
        gate = Gate()
        result = await gate.process_input(
            "fix it",
            execution_mode="supervised",
            task_type="code",
        )
        assert len(result.clarifying_questions) > 0


class TestConversationAwareSufficiency:
    """Prior context makes follow-up confirmations sufficient."""

    @pytest.mark.asyncio
    async def test_confirmation_after_proposal(self) -> None:
        """'yes do it' is sufficient if prior assistant message was a proposal."""
        gate = Gate()
        context = [
            {"role": "user", "content": "Fix the auth bug in auth.py"},
            {
                "role": "assistant",
                "content": (
                    "I'll fix the JWT validation in auth.py. The issue is that expired "
                    "tokens are not being rejected properly. I'll add a check for the "
                    "exp claim and return 401 when it's past the current time. "
                    "Shall I proceed with this approach?"
                ),
            },
        ]
        result = await gate.process_input(
            "yes do it",
            execution_mode="persistent",
            task_type="code",
            conversation_context=context,
        )
        assert len(result.clarifying_questions) == 0

    @pytest.mark.asyncio
    async def test_confirmation_after_non_proposal_insufficient(self) -> None:
        """'yes' after a long NON-proposal response should NOT be confirmed."""
        gate = Gate()
        context = [
            {"role": "user", "content": "Tell me about JWT security"},
            {
                "role": "assistant",
                "content": (
                    "JWT tokens use RSA or HMAC signatures to verify identity. "
                    "The payload contains claims like sub, exp, iat. "
                    "Always validate the signature, issuer, and expiration. "
                    "Never store JWTs in localStorage due to XSS risks."
                ),
            },
        ]
        result = await gate.process_input(
            "yes",
            execution_mode="persistent",
            task_type="code",
            conversation_context=context,
        )
        # Prior message was informational, not a proposal — should ask for clarity
        assert len(result.clarifying_questions) > 0

    @pytest.mark.asyncio
    async def test_confirmation_without_context_insufficient(self) -> None:
        """'yes do it' without prior context is NOT sufficient for code."""
        gate = Gate()
        result = await gate.process_input(
            "yes do it",
            execution_mode="persistent",
            task_type="code",
        )
        assert len(result.clarifying_questions) > 0


class TestBestEffortMode:
    """Best effort mode skips sufficiency checks entirely."""

    @pytest.mark.asyncio
    async def test_vague_request_passes_in_best_effort(self) -> None:
        gate = Gate()
        result = await gate.process_input(
            "fix it",
            execution_mode="best_effort",
            task_type="code",
        )
        assert not result.blocked
        assert len(result.clarifying_questions) == 0

    @pytest.mark.asyncio
    async def test_default_mode_is_best_effort(self) -> None:
        gate = Gate()
        result = await gate.process_input("fix it", task_type="code")
        assert len(result.clarifying_questions) == 0
