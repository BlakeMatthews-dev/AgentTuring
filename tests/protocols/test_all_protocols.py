"""Import and verify all Protocol classes for coverage.

Protocols are abstract — they can't be instantiated. But importing them
covers the class definitions, decorator lines, and type annotation lines.
"""

from __future__ import annotations

from stronghold.protocols.agents import AgentStore
from stronghold.protocols.auth import AuthProvider
from stronghold.protocols.classifier import IntentClassifier
from stronghold.protocols.data import DataStore
from stronghold.protocols.embeddings import EmbeddingClient
from stronghold.protocols.feedback import FeedbackExtractor, ViolationStore
from stronghold.protocols.memory import (
    AuditLog,
    EpisodicStore,
    LearningStore,
    OutcomeStore,
    SessionStore,
    SkillMutationStore,
)
from stronghold.protocols.prompts import PromptManager
from stronghold.protocols.quota import QuotaTracker
from stronghold.protocols.rate_limit import RateLimiter
from stronghold.protocols.router import ModelRouter
from stronghold.protocols.skills import SkillForge, SkillLoader, SkillMarketplace
from stronghold.protocols.tools import ToolExecutor, ToolPlugin, ToolRegistry
from stronghold.protocols.tracing import Span, Trace, TracingBackend

_ALL_PROTOCOLS = [
    AgentStore,
    AuthProvider,
    IntentClassifier,
    DataStore,
    EmbeddingClient,
    FeedbackExtractor,
    ViolationStore,
    AuditLog,
    EpisodicStore,
    LearningStore,
    OutcomeStore,
    SessionStore,
    SkillMutationStore,
    PromptManager,
    QuotaTracker,
    RateLimiter,
    ModelRouter,
    SkillForge,
    SkillLoader,
    SkillMarketplace,
    ToolExecutor,
    ToolPlugin,
    ToolRegistry,
    Span,
    Trace,
    TracingBackend,
]


class TestProtocolsAreRuntimeCheckable:
    def test_all_protocols_imported(self) -> None:
        assert len(_ALL_PROTOCOLS) >= 25

    def test_plain_object_is_not_any_protocol(self) -> None:
        obj = object()
        for proto in _ALL_PROTOCOLS:
            assert not isinstance(obj, proto), f"object() should not be {proto.__name__}"
