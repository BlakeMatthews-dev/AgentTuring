"""Tests for agents/factory.py type annotations.

Covers:
- C13: create_agents() dep parameters typed with proper protocols, not Any.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

from stronghold.agents.factory import create_agents


class TestCreateAgentsSignatureTypes:
    """C13: create_agents() parameters must not be typed as Any (except sa_engine)."""

    def test_no_any_in_public_params(self) -> None:
        """Verify that typed deps in create_agents use protocol types, not Any.

        sa_engine is exempt because SQLAlchemy engine has no Stronghold protocol.
        With `from __future__ import annotations`, annotations are stored as
        strings, so we check for the string 'Any'.
        """
        sig = inspect.signature(create_agents)
        # Parameters that are allowed to remain Any
        allowed_any = {"sa_engine"}

        any_params = []
        for name, param in sig.parameters.items():
            annotation = param.annotation
            if annotation is inspect.Parameter.empty:
                continue
            # With PEP 563 (from __future__ import annotations), annotations
            # are strings. Check both forms.
            is_any = annotation is Any or annotation == "Any"
            if is_any and name not in allowed_any:
                any_params.append(name)

        assert not any_params, (
            f"create_agents() still has Any-typed params: {any_params}. "
            "Use proper protocol types from src/stronghold/protocols/."
        )

    def test_create_agents_accepts_protocol_compliant_fakes(self) -> None:
        """Verify that test fakes satisfy the typed parameters (smoke test)."""
        # This should not raise TypeError -- all types match
        # We just call with a nonexistent directory so it returns empty
        import asyncio

        from stronghold.agents.context_builder import ContextBuilder
        from stronghold.memory.learnings.extractor import ToolCorrectionExtractor
        from stronghold.memory.learnings.store import InMemoryLearningStore
        from stronghold.memory.outcomes import InMemoryOutcomeStore
        from stronghold.prompts.store import InMemoryPromptManager
        from stronghold.security.warden.detector import Warden
        from stronghold.sessions.store import InMemorySessionStore
        from tests.fakes import FakeLLMClient, FakeQuotaTracker, NoopTracingBackend

        result = asyncio.get_event_loop().run_until_complete(
            create_agents(
                agents_dir=Path("/nonexistent"),
                prompt_manager=InMemoryPromptManager(),
                llm=FakeLLMClient(),
                context_builder=ContextBuilder(),
                warden=Warden(),
                sentinel=None,
                learning_store=InMemoryLearningStore(),
                learning_extractor=ToolCorrectionExtractor(),
                outcome_store=InMemoryOutcomeStore(),
                session_store=InMemorySessionStore(),
                quota_tracker=FakeQuotaTracker(),
                tracer=NoopTracingBackend(),
            )
        )
        assert result == {}


class TestAgentInitSignatureTypes:
    """C12: Agent.__init__ parameters must not use bare Any for protocol deps."""

    def test_no_any_for_protocol_deps(self) -> None:
        """Verify that Agent.__init__ typed deps use protocol types, not Any.

        With PEP 563 (from __future__ import annotations), annotations are
        strings. We check for both the string 'Any' and the typing.Any object.
        """
        from stronghold.agents.base import Agent

        sig = inspect.signature(Agent.__init__)
        # No parameters should remain bare Any
        allowed_any: set[str] = set()

        any_params = []
        for name, param in sig.parameters.items():
            if name in ("self",):
                continue
            annotation = param.annotation
            if annotation is inspect.Parameter.empty:
                continue
            # With PEP 563, annotations are strings
            is_any = annotation is Any or annotation == "Any"
            if is_any and name not in allowed_any:
                any_params.append(name)

        assert not any_params, (
            f"Agent.__init__() still has Any-typed params: {any_params}. Use proper protocol types."
        )
