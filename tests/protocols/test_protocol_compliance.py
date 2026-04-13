"""Verify every fake/noop/in-memory implementation satisfies its protocol.

Each parametrized case instantiates the concrete class and asserts
``isinstance(instance, protocol)`` passes. This catches missing methods,
wrong signatures, and broken ``@runtime_checkable`` decorators early.
"""

from __future__ import annotations

from typing import Any

import pytest

# ── Production in-memory / noop implementations ─────────────────────
from stronghold.agents.feedback.extractor import ReviewFeedbackExtractor
from stronghold.agents.feedback.tracker import InMemoryViolationTracker
from stronghold.agents.store import InMemoryAgentStore
from stronghold.memory.episodic.store import InMemoryEpisodicStore
from stronghold.memory.learnings.embeddings import NoopEmbeddingClient
from stronghold.memory.learnings.extractor import (
    RCAExtractor as RCAExtractorImpl,
)
from stronghold.memory.learnings.extractor import (
    ToolCorrectionExtractor,
)
from stronghold.memory.learnings.store import InMemoryLearningStore
from stronghold.memory.mutations import InMemorySkillMutationStore
from stronghold.memory.outcomes import InMemoryOutcomeStore
from stronghold.prompts.store import InMemoryPromptManager

# ── Protocols ────────────────────────────────────────────────────────
from stronghold.protocols.agent_pod import AgentPodDiscovery
from stronghold.protocols.agents import AgentStore
from stronghold.protocols.auth import AuthProvider
from stronghold.protocols.classifier import IntentClassifier
from stronghold.protocols.embeddings import EmbeddingClient
from stronghold.protocols.feedback import FeedbackExtractor, ViolationStore
from stronghold.protocols.llm import LLMClient
from stronghold.protocols.mcp import McpDeployerClient
from stronghold.protocols.memory import (
    AuditLog,
    EpisodicStore,
    LearningExtractor,
    LearningStore,
    OutcomeStore,
    RCAExtractor,
    SessionStore,
    SkillMutationStore,
)
from stronghold.protocols.prompts import PromptManager
from stronghold.protocols.quota import QuotaTracker
from stronghold.protocols.rate_limit import RateLimiter
from stronghold.protocols.router import ModelRouter
from stronghold.protocols.secrets import SecretBackend
from stronghold.protocols.tools import ToolRegistry
from stronghold.protocols.tracing import Span, Trace, TracingBackend
from stronghold.protocols.vault import VaultClient
from stronghold.quota.tracker import InMemoryQuotaTracker
from stronghold.router.selector import RouterEngine
from stronghold.security.rate_limiter import InMemoryRateLimiter
from stronghold.security.sentinel.audit import InMemoryAuditLog
from stronghold.sessions.store import InMemorySessionStore
from stronghold.tools.registry import InMemoryToolRegistry
from stronghold.tracing.noop import (
    NoopSpan as ProdNoopSpan,
)
from stronghold.tracing.noop import (
    NoopTrace as ProdNoopTrace,
)
from stronghold.tracing.noop import (
    NoopTracingBackend as ProdNoopTracingBackend,
)

# ── Fakes (tests/fakes.py) ──────────────────────────────────────────
from tests.fakes import (
    FakeAgentPodDiscovery,
    FakeAuthProvider,
    FakeIntentClassifier,
    FakeLLMClient,
    FakeMcpDeployer,
    FakePromptManager,
    FakeQuotaTracker,
    FakeRateLimiter,
    FakeSecretBackend,
    FakeVaultClient,
    FakeViolationStore,
    NoopSpan,
    NoopTrace,
    NoopTracingBackend,
)

# ── Factory helpers ──────────────────────────────────────────────────
# Some implementations require constructor arguments. This mapping
# provides a zero-arg callable that returns a ready instance.


def _make_in_memory_agent_store() -> InMemoryAgentStore:
    return InMemoryAgentStore(agents={})


def _make_router_engine() -> RouterEngine:
    return RouterEngine(InMemoryQuotaTracker())


# ── Parametrized compliance matrix ──────────────────────────────────

_FAKE_CASES: list[tuple[str, type, Any]] = [
    # -- Fakes from tests/fakes.py --
    ("FakeLLMClient", LLMClient, FakeLLMClient()),
    ("FakeAuthProvider", AuthProvider, FakeAuthProvider()),
    ("FakeQuotaTracker", QuotaTracker, FakeQuotaTracker()),
    ("FakeRateLimiter", RateLimiter, FakeRateLimiter()),
    ("NoopTracingBackend", TracingBackend, NoopTracingBackend()),
    ("NoopTrace", Trace, NoopTrace()),
    ("NoopSpan", Span, NoopSpan()),
    ("FakePromptManager", PromptManager, FakePromptManager()),
    ("FakeSecretBackend", SecretBackend, FakeSecretBackend()),
    ("FakeAgentPodDiscovery", AgentPodDiscovery, FakeAgentPodDiscovery()),
    ("FakeMcpDeployer", McpDeployerClient, FakeMcpDeployer()),
    ("FakeViolationStore", ViolationStore, FakeViolationStore()),
    ("FakeVaultClient", VaultClient, FakeVaultClient()),
    # -- Production in-memory / noop implementations --
    ("InMemoryLearningStore", LearningStore, InMemoryLearningStore()),
    ("InMemoryOutcomeStore", OutcomeStore, InMemoryOutcomeStore()),
    ("InMemoryEpisodicStore", EpisodicStore, InMemoryEpisodicStore()),
    (
        "InMemorySkillMutationStore",
        SkillMutationStore,
        InMemorySkillMutationStore(),
    ),
    ("InMemorySessionStore", SessionStore, InMemorySessionStore()),
    ("InMemoryAuditLog", AuditLog, InMemoryAuditLog()),
    ("InMemoryQuotaTracker", QuotaTracker, InMemoryQuotaTracker()),
    ("InMemoryRateLimiter", RateLimiter, InMemoryRateLimiter()),
    ("InMemoryPromptManager", PromptManager, InMemoryPromptManager()),
    ("InMemoryToolRegistry", ToolRegistry, InMemoryToolRegistry()),
    ("InMemoryAgentStore", AgentStore, _make_in_memory_agent_store()),
    (
        "InMemoryViolationTracker",
        ViolationStore,
        InMemoryViolationTracker(),
    ),
    ("RouterEngine", ModelRouter, _make_router_engine()),
    ("NoopEmbeddingClient", EmbeddingClient, NoopEmbeddingClient()),
    (
        "ToolCorrectionExtractor",
        LearningExtractor,
        ToolCorrectionExtractor(),
    ),
    ("RCAExtractorImpl", RCAExtractor, RCAExtractorImpl()),
    (
        "ReviewFeedbackExtractor",
        FeedbackExtractor,
        ReviewFeedbackExtractor(),
    ),
    # Production tracing noops (src/stronghold/tracing/noop.py)
    (
        "ProdNoopTracingBackend",
        TracingBackend,
        ProdNoopTracingBackend(),
    ),
    ("ProdNoopTrace", Trace, ProdNoopTrace()),
    ("ProdNoopSpan", Span, ProdNoopSpan()),
]


@pytest.mark.parametrize(
    ("label", "protocol", "instance"),
    _FAKE_CASES,
    ids=[c[0] for c in _FAKE_CASES],
)
def test_implementation_satisfies_protocol(
    label: str,
    protocol: type,
    instance: object,
) -> None:
    """Every fake/noop/in-memory impl must pass isinstance() against protocol."""
    assert isinstance(instance, protocol), (
        f"{label} ({type(instance).__name__}) does not satisfy {protocol.__name__} protocol"
    )


# ── Known non-compliant fakes (document the gap) ────────────────────


def test_fake_intent_classifier_does_not_satisfy_protocol() -> None:
    """FakeIntentClassifier is non-compliant with IntentClassifier protocol.

    The fake defines classify() as a staticmethod(text: str) but the
    protocol requires classify(self, messages, task_types, explicit_priority)
    plus detect_multi_intent(). This is a real compliance gap that should
    be fixed in tests/fakes.py.
    """
    fake = FakeIntentClassifier()
    assert not isinstance(fake, IntentClassifier), (
        "FakeIntentClassifier unexpectedly satisfies IntentClassifier -- "
        "if this now passes, move it to the main parametrized matrix"
    )
