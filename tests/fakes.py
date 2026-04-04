"""Fake/noop implementations of all protocols for testing."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from stronghold.types.auth import SYSTEM_AUTH, AuthContext

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from types import TracebackType


class FakeLLMClient:
    """Fake LLM that returns predetermined responses."""

    def __init__(self) -> None:
        self.responses: list[dict[str, Any]] = []
        self.calls: list[dict[str, Any]] = []
        self._call_index = 0

    def set_responses(self, *responses: dict[str, Any]) -> None:
        """Set the sequence of responses to return."""
        self.responses = list(responses)
        self._call_index = 0

    def set_simple_response(self, content: str) -> None:
        """Set a single text response."""
        self.responses = [
            {
                "id": "chatcmpl-fake",
                "object": "chat.completion",
                "model": "fake-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            }
        ]
        self._call_index = 0

    async def complete(
        self,
        messages: list[dict[str, Any]],
        model: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Return the next predetermined response."""
        self.calls.append({"messages": messages, "model": model, **kwargs})
        if self._call_index < len(self.responses):
            resp = self.responses[self._call_index]
            self._call_index += 1
            return resp
        return {
            "id": "chatcmpl-fake-default",
            "object": "chat.completion",
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Default fake response"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }

    async def stream(
        self,
        messages: list[dict[str, Any]],
        model: str,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Yield a single SSE chunk."""
        yield 'data: {"choices":[{"delta":{"content":"fake stream"}}]}\n\n'
        yield "data: [DONE]\n\n"


class FakePromptManager:
    """Dict-backed prompt manager for testing."""

    def __init__(self) -> None:
        self.prompts: dict[str, tuple[str, dict[str, Any]]] = {}

    def seed(self, name: str, content: str, config: dict[str, Any] | None = None) -> None:
        """Pre-populate a prompt."""
        self.prompts[name] = (content, config or {})

    async def get(self, name: str, *, label: str = "production") -> str:
        """Return prompt content or empty string."""
        entry = self.prompts.get(name)
        return entry[0] if entry else ""

    async def get_with_config(
        self,
        name: str,
        *,
        label: str = "production",
    ) -> tuple[str, dict[str, Any]]:
        """Return prompt content + config."""
        return self.prompts.get(name, ("", {}))

    async def upsert(
        self,
        name: str,
        content: str,
        *,
        config: dict[str, Any] | None = None,
        label: str = "",
    ) -> None:
        """Store a prompt."""
        self.prompts[name] = (content, config or {})


class NoopSpan:
    """No-op span for testing."""

    def __enter__(self) -> NoopSpan:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        return None

    def set_input(self, data: Any) -> NoopSpan:
        return self

    def set_output(self, data: Any) -> NoopSpan:
        return self

    def set_usage(self, input_tokens: int = 0, output_tokens: int = 0, model: str = "") -> NoopSpan:
        return self


class NoopTrace:
    """No-op trace for testing."""

    @property
    def trace_id(self) -> str:
        return "noop-trace-id"

    def span(self, name: str) -> NoopSpan:
        return NoopSpan()

    def score(self, name: str, value: float, comment: str = "") -> None:
        pass

    def update(self, metadata: dict[str, Any]) -> None:
        pass

    def end(self) -> None:
        pass


class NoopTracingBackend:
    """No-op tracing backend for testing."""

    def create_trace(
        self,
        *,
        user_id: str = "",
        session_id: str = "",
        name: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> NoopTrace:
        return NoopTrace()


class FakeQuotaTracker:
    """Fake quota tracker with configurable usage percentages."""

    def __init__(self, usage_pct: float = 0.0) -> None:
        self._usage_pct = usage_pct
        self.recorded: list[dict[str, Any]] = []

    async def record_usage(
        self,
        provider: str,
        billing_cycle: str,
        input_tokens: int,
        output_tokens: int,
    ) -> dict[str, object]:
        self.recorded.append(
            {
                "provider": provider,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            }
        )
        return {"provider": provider, "total_tokens": input_tokens + output_tokens}

    async def get_usage_pct(
        self,
        provider: str,
        billing_cycle: str,
        free_tokens: int,
    ) -> float:
        return self._usage_pct

    async def get_all_usage(self) -> list[dict[str, object]]:
        return []


class FakeRateLimiter:
    """Fake rate limiter that always allows (or can be set to deny)."""

    def __init__(self, *, always_allow: bool = True) -> None:
        self._always_allow = always_allow
        self.calls: list[str] = []

    async def check(self, key: str) -> tuple[bool, dict[str, str]]:
        self.calls.append(key)
        headers = {"X-RateLimit-Limit": "60", "X-RateLimit-Remaining": "59", "X-RateLimit-Reset": "60"}
        return self._always_allow, headers

    async def record(self, key: str) -> None:
        pass


class FakeAuthProvider:
    """Fake auth provider that always returns system auth."""

    def __init__(self, auth_context: AuthContext | None = None) -> None:
        self.auth_context = auth_context or SYSTEM_AUTH

    async def authenticate(
        self,
        authorization: str | None,
        headers: dict[str, str] | None = None,
    ) -> AuthContext:
        if not authorization:
            msg = "Missing Authorization header"
            raise ValueError(msg)
        return self.auth_context


class FakeViolationStore:
    """Fake violation store for testing the RLHF feedback loop."""

    def __init__(self) -> None:
        self.findings: list[tuple[Any, str]] = []
        self.reviews: list[Any] = []

    def record_finding(self, finding: Any, *, agent_id: str) -> None:
        self.findings.append((finding, agent_id))

    def record_review(self, result: Any) -> None:
        self.reviews.append(result)

    def get_metrics(self, agent_id: str) -> Any:
        from stronghold.types.feedback import ViolationMetrics

        return ViolationMetrics(
            agent_id=agent_id,
            total_prs_reviewed=len(self.reviews),
            total_findings=len(self.findings),
        )

    def get_top_violations(
        self,
        agent_id: str,
        *,
        limit: int = 5,
    ) -> list[tuple[Any, int]]:
        return []


# ── Test container factory ───────────────────────────────────────────
# Use these instead of constructing Container manually.


def make_test_config(**overrides: Any) -> Any:
    """Minimal valid StrongholdConfig for tests."""
    from stronghold.types.config import StrongholdConfig, TaskTypeConfig

    defaults: dict[str, Any] = {
        "providers": {
            "test": {"status": "active", "billing_cycle": "monthly", "free_tokens": 1_000_000},
        },
        "models": {
            "test-model": {
                "provider": "test",
                "litellm_id": "test/model",
                "tier": "medium",
                "quality": 0.7,
                "speed": 500,
                "strengths": ["code", "chat"],
            },
        },
        "task_types": {
            "chat": TaskTypeConfig(keywords=["hello"], preferred_strengths=["chat"]),
        },
        "permissions": {"admin": ["*"]},
        "router_api_key": "sk-test",
    }
    defaults.update(overrides)
    return StrongholdConfig(**defaults)


def make_test_container(
    fake_llm: FakeLLMClient | None = None,
    **overrides: Any,
) -> Any:
    """Build a complete test Container with all required fields. No async needed.

    Usage:
        from tests.fakes import make_test_container, FakeLLMClient
        container = make_test_container()
        # or with custom LLM:
        container = make_test_container(fake_llm=FakeLLMClient())
    """
    from stronghold.agents.context_builder import ContextBuilder
    from stronghold.agents.intents import IntentRegistry
    from stronghold.classifier.engine import ClassifierEngine
    from stronghold.container import Container
    from stronghold.memory.learnings.extractor import ToolCorrectionExtractor
    from stronghold.memory.learnings.store import InMemoryLearningStore
    from stronghold.memory.outcomes import InMemoryOutcomeStore
    from stronghold.prompts.store import InMemoryPromptManager
    from stronghold.quota.tracker import InMemoryQuotaTracker
    from stronghold.router.selector import RouterEngine
    from stronghold.security.auth_static import StaticKeyAuthProvider
    from stronghold.security.gate import Gate
    from stronghold.security.sentinel.audit import InMemoryAuditLog
    from stronghold.security.sentinel.policy import Sentinel
    from stronghold.security.warden.detector import Warden
    from stronghold.sessions.store import InMemorySessionStore
    from stronghold.tools.executor import ToolDispatcher
    from stronghold.tools.registry import InMemoryToolRegistry
    from stronghold.tracing.noop import NoopTracingBackend
    from stronghold.types.auth import PermissionTable

    llm = fake_llm or FakeLLMClient()
    config = make_test_config()
    warden = Warden()
    audit_log = InMemoryAuditLog()

    fields: dict[str, Any] = {
        "config": config,
        "auth_provider": StaticKeyAuthProvider(api_key="sk-test"),
        "permission_table": PermissionTable.from_config({"admin": ["*"]}),
        "router": RouterEngine(InMemoryQuotaTracker()),
        "classifier": ClassifierEngine(),
        "quota_tracker": InMemoryQuotaTracker(),
        "prompt_manager": InMemoryPromptManager(),
        "learning_store": InMemoryLearningStore(),
        "learning_extractor": ToolCorrectionExtractor(),
        "outcome_store": InMemoryOutcomeStore(),
        "session_store": InMemorySessionStore(),
        "audit_log": audit_log,
        "warden": warden,
        "gate": Gate(warden=warden),
        "sentinel": Sentinel(
            warden=warden,
            permission_table=PermissionTable.from_config(config.permissions),
            audit_log=audit_log,
        ),
        "tracer": NoopTracingBackend(),
        "context_builder": ContextBuilder(),
        "intent_registry": IntentRegistry(),
        "llm": llm,
        "tool_registry": InMemoryToolRegistry(),
        "tool_dispatcher": ToolDispatcher(InMemoryToolRegistry()),
    }
    fields.update(overrides)
    return Container(**fields)
