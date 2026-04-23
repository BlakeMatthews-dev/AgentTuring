"""Targeted coverage tests for agent-layer uncovered lines.

Covers:
1. base.py lines 436-472: outcome recording + trace finalization with tool history
2. tool_http.py lines 54-57: list_tools non-200 and empty paths
3. artificer/strategy.py lines 188-191: status callbacks for error/failed tool results
4. store.py lines 233-240: import_gitagent with invalid manifest + missing name
5. context_builder.py lines 49-56: promoted learnings injection
"""

from __future__ import annotations

import io
import json
import zipfile
from typing import Any

import pytest
import yaml

from stronghold.agents.base import Agent, _build_tool_schema
from stronghold.agents.context_builder import ContextBuilder
from stronghold.agents.store import InMemoryAgentStore
from stronghold.agents.strategies.direct import DirectStrategy
from stronghold.agents.strategies.react import ReactStrategy
from stronghold.agents.artificer.strategy import ArtificerStrategy
from stronghold.memory.learnings.extractor import RCAExtractor, ToolCorrectionExtractor
from stronghold.memory.learnings.promoter import LearningPromoter
from stronghold.memory.learnings.store import InMemoryLearningStore
from stronghold.memory.outcomes import InMemoryOutcomeStore
from stronghold.prompts.store import InMemoryPromptManager
from stronghold.security.warden.detector import Warden
from stronghold.sessions.store import InMemorySessionStore
from stronghold.types.agent import AgentIdentity, ReasoningResult
from stronghold.types.memory import Learning, MemoryScope
from tests.factories import build_auth_context
from tests.fakes import FakeLLMClient, NoopTracingBackend


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool_call_response(
    tool_name: str,
    arguments: dict[str, Any],
    tool_call_id: str = "tc-1",
    content: str = "",
) -> dict[str, Any]:
    """Build an LLM response that contains a tool_call."""
    return {
        "id": "chatcmpl-fake",
        "object": "chat.completion",
        "model": "fake-model",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": [
                        {
                            "id": tool_call_id,
                            "type": "function",
                            "function": {
                                "name": tool_name,
                                "arguments": json.dumps(arguments),
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    }


def _make_text_response(content: str) -> dict[str, Any]:
    """Build a simple text LLM response (no tool calls)."""
    return {
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


class FakeReactStrategy:
    """Strategy that returns a predetermined result with tool_history."""

    def __init__(self, result: ReasoningResult) -> None:
        self._result = result

    async def reason(self, messages: Any, model: Any, llm: Any, **kwargs: Any) -> ReasoningResult:
        return self._result


async def _make_agent(
    *,
    llm: FakeLLMClient | None = None,
    strategy: Any = None,
    soul: str = "You are a test assistant.",
    name: str = "test-agent",
    tools: tuple[str, ...] = (),
    tracer: NoopTracingBackend | None = None,
    session_store: InMemorySessionStore | None = None,
    learning_store: InMemoryLearningStore | None = None,
    learning_extractor: ToolCorrectionExtractor | None = None,
    rca_extractor: RCAExtractor | None = None,
    learning_promoter: LearningPromoter | None = None,
    outcome_store: InMemoryOutcomeStore | None = None,
    memory_config: dict[str, Any] | None = None,
) -> Agent:
    llm = llm or FakeLLMClient()
    prompts = InMemoryPromptManager()
    await prompts.upsert(f"agent.{name}.soul", soul, label="production")
    return Agent(
        identity=AgentIdentity(
            name=name,
            soul_prompt_name=f"agent.{name}.soul",
            model="test-model",
            tools=tools,
            memory_config=memory_config or {"learnings": True},
        ),
        strategy=strategy or DirectStrategy(),
        llm=llm,
        context_builder=ContextBuilder(),
        prompt_manager=prompts,
        warden=Warden(),
        learning_store=learning_store or InMemoryLearningStore(),
        learning_extractor=learning_extractor,
        rca_extractor=rca_extractor,
        learning_promoter=learning_promoter,
        session_store=session_store or InMemorySessionStore(),
        outcome_store=outcome_store,
        tracer=tracer,
    )


# ===========================================================================
# 1. base.py: outcome recording (lines 436-459) and trace finalization (462-472)
# ===========================================================================


class TestOutcomeRecording:
    """Tests for outcome store recording in Agent.handle() (lines 436-459)."""

    async def test_outcome_recorded_on_successful_response(self) -> None:
        """Outcome store is called after a successful response with no tools."""
        llm = FakeLLMClient()
        llm.set_simple_response("All good")
        outcome_store = InMemoryOutcomeStore()
        agent = await _make_agent(llm=llm, outcome_store=outcome_store)

        await agent.handle(
            [{"role": "user", "content": "hello"}],
            build_auth_context(),
            session_id="sess-outcome-1",
        )

        outcomes = await outcome_store.list_outcomes()
        assert len(outcomes) == 1
        assert outcomes[0].success is True
        assert outcomes[0].error_type == ""
        assert outcomes[0].agent_id == "test-agent"
        assert outcomes[0].model_used == "test-model"

    async def test_outcome_records_tool_failures(self) -> None:
        """Outcome records tool_calls and marks failure when tool errors exist."""
        tool_history = [
            {"tool_name": "run_pytest", "arguments": {}, "result": "Error: tests failed", "round": 0},
            {"tool_name": "write_file", "arguments": {}, "result": '{"status": "ok"}', "round": 1},
        ]
        result = ReasoningResult(
            response="Done with errors",
            done=True,
            tool_history=tool_history,
        )
        llm = FakeLLMClient()
        llm.set_simple_response("ignored")
        outcome_store = InMemoryOutcomeStore()
        agent = await _make_agent(
            llm=llm,
            strategy=FakeReactStrategy(result),
            outcome_store=outcome_store,
        )

        await agent.handle(
            [{"role": "user", "content": "run tests"}],
            build_auth_context(),
        )

        outcomes = await outcome_store.list_outcomes()
        assert len(outcomes) == 1
        outcome = outcomes[0]
        assert outcome.success is False
        assert outcome.error_type == "tool_error"
        # tool_calls list should have 2 entries
        assert len(outcome.tool_calls) == 2
        assert outcome.tool_calls[0]["name"] == "run_pytest"
        assert outcome.tool_calls[0]["success"] is False  # starts with "Error"
        assert outcome.tool_calls[1]["name"] == "write_file"
        assert outcome.tool_calls[1]["success"] is True

    async def test_outcome_records_user_and_org_ids(self) -> None:
        """Outcome captures org_id, team_id, user_id from auth context."""
        llm = FakeLLMClient()
        llm.set_simple_response("ok")
        outcome_store = InMemoryOutcomeStore()
        agent = await _make_agent(llm=llm, outcome_store=outcome_store)

        auth = build_auth_context(org_id="acme", team_id="eng", user_id="alice")
        await agent.handle(
            [{"role": "user", "content": "hello"}],
            auth,
        )

        outcomes = await outcome_store.list_outcomes(org_id="acme")
        assert len(outcomes) == 1
        assert outcomes[0].org_id == "acme"
        assert outcomes[0].team_id == "eng"
        assert outcomes[0].user_id == "alice"

    async def test_no_outcome_without_store(self) -> None:
        """When outcome_store is None, no error is raised."""
        llm = FakeLLMClient()
        llm.set_simple_response("ok")
        agent = await _make_agent(llm=llm, outcome_store=None)

        result = await agent.handle(
            [{"role": "user", "content": "hello"}],
            build_auth_context(),
        )
        assert result.content == "ok"


class _CapturingTrace:
    """Trace double that records metadata updates and span calls.

    Unlike NoopTrace, this lets us assert what the agent actually stored on the
    trace: tools_used, success/fail counts, tool_result strings, etc.
    """

    def __init__(self) -> None:
        self.metadata: dict[str, Any] = {}
        self.scores: list[tuple[str, float, str]] = []
        self.ended = False

    @property
    def trace_id(self) -> str:
        return "capture-trace-id"

    def span(self, name: str) -> Any:
        from tests.fakes import NoopSpan

        return NoopSpan()

    def score(self, name: str, value: float, comment: str = "") -> None:
        self.scores.append((name, value, comment))

    def update(self, metadata: dict[str, Any]) -> None:
        self.metadata.update(metadata)

    def end(self) -> None:
        self.ended = True


class _CapturingTracer:
    """Tracing backend that hands out a single CapturingTrace we can inspect."""

    def __init__(self) -> None:
        self.last_trace: _CapturingTrace | None = None

    def create_trace(
        self,
        *,
        user_id: str = "",
        session_id: str = "",
        name: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> _CapturingTrace:
        trace = _CapturingTrace()
        self.last_trace = trace
        return trace


class TestTraceFinalizationWithToolHistory:
    """Agent.handle updates the trace with accurate tool_history derived metadata.

    Rather than simply asserting ``response.content`` (the old tests' only real
    check), these tests use a capturing trace so we can verify the side-effect
    we actually care about: the agent records the right tools + success/fail
    counts on the trace, and the trace is closed.
    """

    @pytest.mark.parametrize(
        ("tool_history", "expected_success", "expected_fail", "expected_tools"),
        [
            pytest.param(
                [
                    {"tool_name": "run_pytest", "arguments": {}, "result": "Error: failed", "round": 0},
                    {"tool_name": "write_file", "arguments": {}, "result": '{"status": "ok"}', "round": 1},
                    {"tool_name": "run_pytest", "arguments": {}, "result": '"passed": true', "round": 2},
                ],
                2, 1, {"run_pytest", "write_file"},
                id="mixed-success-fail-dedup",
            ),
            pytest.param(
                [
                    {"tool_name": "read_file", "arguments": {}, "result": "file content with error in the middle", "round": 0},
                ],
                0, 1, {"read_file"},
                id="error-substring-detected",
            ),
            pytest.param(
                [
                    {"tool_name": "run_pytest", "arguments": {}, "result": "ok", "round": 0},
                    {"tool_name": "run_pytest", "arguments": {}, "result": "ok", "round": 1},
                    {"tool_name": "run_ruff_check", "arguments": {}, "result": "ok", "round": 2},
                ],
                3, 0, {"run_pytest", "run_ruff_check"},
                id="tools-used-deduped",
            ),
            pytest.param(
                [],
                0, 0, set(),
                id="empty-history",
            ),
        ],
    )
    async def test_trace_metadata_reflects_tool_history(
        self,
        tool_history: list[dict[str, Any]],
        expected_success: int,
        expected_fail: int,
        expected_tools: set[str],
    ) -> None:
        result = ReasoningResult(response="done", done=True, tool_history=tool_history)
        tracer = _CapturingTracer()
        agent = await _make_agent(
            llm=FakeLLMClient(),
            strategy=FakeReactStrategy(result),
            tracer=tracer,
        )

        response = await agent.handle(
            [{"role": "user", "content": "run tests"}],
            build_auth_context(),
        )

        # The response still comes through.
        assert response.content == "done"

        # The trace was created, populated with metadata derived from the
        # tool history, and closed.
        assert tracer.last_trace is not None
        meta = tracer.last_trace.metadata
        assert meta.get("agent") == "test-agent"
        assert meta.get("model") == "test-model"
        if tool_history:
            # Counts are stored as strings (langfuse-style metadata).
            assert int(meta["tool_calls_total"]) == len(tool_history)
            assert int(meta["tool_calls_success"]) == expected_success
            assert int(meta["tool_calls_failed"]) == expected_fail
            # tools_used is a comma-joined deduped set, in insertion order.
            tools = {t for t in meta["tools_used"].split(",") if t}
            assert tools == expected_tools
        else:
            # Empty history may either omit these fields or store zeros; both
            # are acceptable, but there must be no invented tool names.
            assert meta.get("tools_used", "") in ("", None)
        assert tracer.last_trace.ended is True

    async def test_outcome_and_trace_both_fire_with_tool_history(self) -> None:
        """Both outcome recording and trace finalization work together.

        Asserts the concrete side-effects: one outcome stored with success=False
        (because tool_history contains an Error), and the trace finalized.
        """
        tool_history = [
            {"tool_name": "run_pytest", "arguments": {}, "result": "Error: boom", "round": 0},
            {"tool_name": "write_file", "arguments": {}, "result": "ok", "round": 1},
        ]
        result = ReasoningResult(response="Partial success", done=True, tool_history=tool_history)
        tracer = _CapturingTracer()
        outcome_store = InMemoryOutcomeStore()
        agent = await _make_agent(
            llm=FakeLLMClient(),
            strategy=FakeReactStrategy(result),
            tracer=tracer,
            outcome_store=outcome_store,
        )

        response = await agent.handle(
            [{"role": "user", "content": "run tests and fix"}],
            build_auth_context(),
            session_id="sess-both",
        )
        assert response.content == "Partial success"

        outcomes = await outcome_store.list_outcomes()
        assert len(outcomes) == 1
        assert outcomes[0].success is False
        assert outcomes[0].error_type == "tool_error"
        assert len(outcomes[0].tool_calls) == 2

        assert tracer.last_trace is not None
        assert tracer.last_trace.ended is True


# ===========================================================================
# 2. tool_http.py list_tools edge cases -- REMOVED
# ===========================================================================
# The previous class defined a local InjectableExecutor subclass that
# re-implemented list_tools and then asserted the reimplementation's behavior.
# That is a tautology -- it does not exercise src/.../tool_http.py.
# Real coverage for HTTPToolExecutor.list_tools lives in
# tests/agents/test_tool_http_extended.py (real class + httpx MockTransport)
# and tests/agents/test_tool_http.py (unreachable-server path).


# ===========================================================================
# 3. artificer/strategy.py: status callbacks for error tool results (lines 188-191)
# ===========================================================================


class TestArtificerErrorStatusCallbacks:
    """Tests for ArtificerStrategy status callback on error/failed tool results."""

    async def test_status_callback_on_passed_false(self) -> None:
        """Status callback fires 'FAILED -- fixing...' for passed=false results."""
        llm = FakeLLMClient()
        llm.set_responses(
            _make_text_response("## Plan\n1. Run tests"),
            _make_tool_call_response("run_pytest", {"path": "."}),
            _make_text_response("Fixed the issues."),
        )
        statuses: list[str] = []

        async def track_status(msg: str) -> None:
            statuses.append(msg)

        async def fake_tool_executor(name: str, args: dict[str, Any]) -> str:
            return '"passed": false, "summary": "2 failed"\nFAILED test_a.py'

        strategy = ArtificerStrategy(max_phases=3)
        result = await strategy.reason(
            [{"role": "user", "content": "Fix tests"}],
            "test-model",
            llm,
            tool_executor=fake_tool_executor,
            status_callback=track_status,
        )

        assert result.done is True
        assert any("FAILED" in s and "fixing" in s for s in statuses)

    async def test_status_callback_on_error_status_failed(self) -> None:
        """Status callback fires 'error -- retrying...' for status=failed errors."""
        llm = FakeLLMClient()
        llm.set_responses(
            _make_text_response("## Plan\n1. Read file"),
            _make_tool_call_response("read_file", {"path": "/missing.txt"}),
            _make_text_response("File not found, using alternative."),
        )
        statuses: list[str] = []

        async def track_status(msg: str) -> None:
            statuses.append(msg)

        async def fake_tool_executor(name: str, args: dict[str, Any]) -> str:
            return '"error": "File not found", "status": "failed"'

        strategy = ArtificerStrategy(max_phases=3)
        result = await strategy.reason(
            [{"role": "user", "content": "Read missing file"}],
            "test-model",
            llm,
            tool_executor=fake_tool_executor,
            status_callback=track_status,
        )

        assert result.done is True
        assert any("error" in s and "retrying" in s for s in statuses)

    async def test_status_callback_on_passed_true(self) -> None:
        """Status callback fires 'OK' for passed=true results."""
        llm = FakeLLMClient()
        llm.set_responses(
            _make_text_response("## Plan\n1. Run tests"),
            _make_tool_call_response("run_pytest", {"path": "."}),
            _make_text_response("All tests pass."),
        )
        statuses: list[str] = []

        async def track_status(msg: str) -> None:
            statuses.append(msg)

        async def fake_tool_executor(name: str, args: dict[str, Any]) -> str:
            return '"passed": true, "summary": "10 tests passed"'

        strategy = ArtificerStrategy(max_phases=3)
        await strategy.reason(
            [{"role": "user", "content": "Run tests"}],
            "test-model",
            llm,
            tool_executor=fake_tool_executor,
            status_callback=track_status,
        )

        assert any("OK" in s for s in statuses)

    async def test_status_callback_on_status_ok(self) -> None:
        """Status callback fires 'OK' for status=ok results."""
        llm = FakeLLMClient()
        llm.set_responses(
            _make_text_response("## Plan\n1. Write file"),
            _make_tool_call_response("write_file", {"path": "x.py", "content": "x = 1"}),
            _make_text_response("File written."),
        )
        statuses: list[str] = []

        async def track_status(msg: str) -> None:
            statuses.append(msg)

        async def fake_tool_executor(name: str, args: dict[str, Any]) -> str:
            return '"status": "ok", "path": "x.py"'

        strategy = ArtificerStrategy(max_phases=3)
        await strategy.reason(
            [{"role": "user", "content": "Write a file"}],
            "test-model",
            llm,
            tool_executor=fake_tool_executor,
            status_callback=track_status,
        )

        assert any("OK" in s for s in statuses)

    async def test_no_tool_executor_returns_not_available(self) -> None:
        """When tool_executor is None, tool results say 'not available'."""
        llm = FakeLLMClient()
        llm.set_responses(
            _make_text_response("## Plan\n1. Try tool"),
            _make_tool_call_response("read_file", {"path": "x.py"}),
            _make_text_response("No tool available."),
        )
        strategy = ArtificerStrategy(max_phases=3)
        result = await strategy.reason(
            [{"role": "user", "content": "Read file"}],
            "test-model",
            llm,
            tool_executor=None,
        )

        assert result.done is True
        assert len(result.tool_history) == 1
        assert "not available" in result.tool_history[0]["result"]


# ===========================================================================
# 4. store.py: import_gitagent edge cases (lines 233-240)
# ===========================================================================


@pytest.fixture
def agent_store_for_import() -> InMemoryAgentStore:
    """Create an InMemoryAgentStore with one pre-existing agent for import tests."""
    fake_llm = FakeLLMClient()
    fake_llm.set_simple_response("ok")
    prompts = InMemoryPromptManager()
    warden = Warden()
    context_builder = ContextBuilder()

    default_agent = Agent(
        identity=AgentIdentity(
            name="arbiter",
            soul_prompt_name="agent.arbiter.soul",
            model="test/model",
            memory_config={"learnings": True},
        ),
        strategy=DirectStrategy(),
        llm=fake_llm,
        context_builder=context_builder,
        prompt_manager=prompts,
        warden=warden,
    )

    agents: dict[str, Agent] = {"arbiter": default_agent}
    return InMemoryAgentStore(agents, prompts)


class TestImportGitagentEdgeCases:
    """Tests for import_gitagent edge cases (lines 233-240)."""

    async def test_invalid_manifest_format_raises(
        self, agent_store_for_import: InMemoryAgentStore
    ) -> None:
        """import_gitagent raises when agent.yaml is not a dict (e.g. a string)."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            # Write agent.yaml with a plain string instead of a dict
            zf.writestr("my-agent/agent.yaml", "just a string, not yaml dict")
        with pytest.raises(ValueError, match="Invalid agent.yaml format"):
            await agent_store_for_import.import_gitagent(buf.getvalue())

    async def test_missing_name_field_raises(
        self, agent_store_for_import: InMemoryAgentStore
    ) -> None:
        """import_gitagent raises when agent.yaml has no 'name' field."""
        buf = io.BytesIO()
        manifest = {
            "spec_version": "0.1.0",
            "version": "1.0.0",
            "description": "Agent with no name",
            # "name" is intentionally missing
        }
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(
                "unnamed/agent.yaml",
                yaml.dump(manifest, default_flow_style=False),
            )
        with pytest.raises(ValueError, match="missing 'name' field"):
            await agent_store_for_import.import_gitagent(buf.getvalue())

    async def test_empty_name_raises(
        self, agent_store_for_import: InMemoryAgentStore
    ) -> None:
        """import_gitagent raises when name is an empty string."""
        buf = io.BytesIO()
        manifest = {
            "spec_version": "0.1.0",
            "name": "",
            "version": "1.0.0",
        }
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(
                "empty-name/agent.yaml",
                yaml.dump(manifest, default_flow_style=False),
            )
        with pytest.raises(ValueError, match="missing 'name' field"):
            await agent_store_for_import.import_gitagent(buf.getvalue())

    async def test_manifest_is_yaml_list_raises(
        self, agent_store_for_import: InMemoryAgentStore
    ) -> None:
        """import_gitagent raises when agent.yaml parses as a list."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("bad-agent/agent.yaml", "- item1\n- item2\n")
        with pytest.raises(ValueError, match="Invalid agent.yaml format"):
            await agent_store_for_import.import_gitagent(buf.getvalue())

    async def test_import_without_rules_md(
        self, agent_store_for_import: InMemoryAgentStore
    ) -> None:
        """import_gitagent works when zip has no RULES.md."""
        buf = io.BytesIO()
        manifest = {
            "spec_version": "0.1.0",
            "name": "no-rules-agent",
            "version": "1.0.0",
            "description": "Agent without rules",
            "reasoning": {"strategy": "direct", "max_rounds": 3},
            "model": "test/model",
            "tools": [],
            "trust_tier": "t2",
        }
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(
                "no-rules-agent/agent.yaml",
                yaml.dump(manifest, default_flow_style=False),
            )
            zf.writestr("no-rules-agent/SOUL.md", "A helpful agent.")
            # No RULES.md included

        name = await agent_store_for_import.import_gitagent(buf.getvalue())
        assert name == "no-rules-agent"
        detail = await agent_store_for_import.get("no-rules-agent")
        assert detail is not None
        assert detail["rules_preview"] == ""

    async def test_import_without_soul_md(
        self, agent_store_for_import: InMemoryAgentStore
    ) -> None:
        """import_gitagent works when zip has no SOUL.md."""
        buf = io.BytesIO()
        manifest = {
            "spec_version": "0.1.0",
            "name": "no-soul-agent",
            "version": "1.0.0",
            "reasoning": {"strategy": "direct"},
            "model": "test/model",
            "tools": [],
            "trust_tier": "t2",
        }
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(
                "no-soul-agent/agent.yaml",
                yaml.dump(manifest, default_flow_style=False),
            )
            # No SOUL.md

        name = await agent_store_for_import.import_gitagent(buf.getvalue())
        assert name == "no-soul-agent"


# ===========================================================================
# 5. context_builder.py: promoted learnings injection (lines 49-56)
# ===========================================================================


class TestContextBuilderPromotedLearnings:
    """Tests for promoted learnings injection in ContextBuilder.build (lines 49-56)."""

    async def test_promoted_learnings_injected_into_system_prompt(self) -> None:
        """Promoted learnings are included in the system prompt when available."""
        prompts = InMemoryPromptManager()
        await prompts.upsert("agent.test.soul", "You are a helpful assistant.")
        learning_store = InMemoryLearningStore()

        # Store a learning and promote it
        learning = Learning(
            category="tool_correction",
            trigger_keys=["fan", "bedroom"],
            learning="entity_id for bedroom fan is fan.bedroom_lamp",
            tool_name="ha_control",
            agent_id="test",
            scope=MemoryScope.AGENT,
            hit_count=10,
            status="promoted",
        )
        await learning_store.store(learning)

        identity = AgentIdentity(
            name="test",
            soul_prompt_name="agent.test.soul",
            memory_config={"learnings": True},
        )
        builder = ContextBuilder()
        messages = [{"role": "user", "content": "turn on the fan"}]
        result, _ = await builder.build(
            messages,
            identity,
            prompt_manager=prompts,
            learning_store=learning_store,
            agent_id="test",
            org_id="",
        )

        # System message should contain promoted learnings
        system_msg = result[0]
        assert system_msg["role"] == "system"
        assert "promoted" in system_msg["content"]
        assert "fan.bedroom_lamp" in system_msg["content"]

    async def test_no_promoted_learnings_when_none_exist(self) -> None:
        """No promoted section in system prompt when no promoted learnings exist."""
        prompts = InMemoryPromptManager()
        await prompts.upsert("agent.test.soul", "You are a helper.")
        learning_store = InMemoryLearningStore()

        identity = AgentIdentity(
            name="test",
            soul_prompt_name="agent.test.soul",
            memory_config={"learnings": True},
        )
        builder = ContextBuilder()
        messages = [{"role": "user", "content": "hello"}]
        result, _ = await builder.build(
            messages,
            identity,
            prompt_manager=prompts,
            learning_store=learning_store,
            agent_id="test",
            org_id="",
        )

        system_msg = result[0]
        assert "promoted" not in system_msg["content"]

    async def test_promoted_learnings_not_injected_without_memory_config(self) -> None:
        """Promoted learnings skipped when identity.memory_config lacks 'learnings'."""
        prompts = InMemoryPromptManager()
        await prompts.upsert("agent.test.soul", "You are a helper.")
        learning_store = InMemoryLearningStore()

        learning = Learning(
            category="tool_correction",
            trigger_keys=["fan"],
            learning="fan correction",
            tool_name="ha_control",
            status="promoted",
        )
        await learning_store.store(learning)

        identity = AgentIdentity(
            name="test",
            soul_prompt_name="agent.test.soul",
            memory_config={},  # No "learnings" key
        )
        builder = ContextBuilder()
        messages = [{"role": "user", "content": "turn on the fan"}]
        result, _ = await builder.build(
            messages,
            identity,
            prompt_manager=prompts,
            learning_store=learning_store,
            agent_id="test",
            org_id="",
        )

        system_msg = result[0]
        assert "promoted" not in system_msg["content"]

    async def test_multiple_promoted_learnings_all_injected(self) -> None:
        """Multiple promoted learnings are all present in the system prompt."""
        prompts = InMemoryPromptManager()
        await prompts.upsert("agent.test.soul", "You are a helper.")
        learning_store = InMemoryLearningStore()

        for i in range(3):
            learning = Learning(
                category="tool_correction",
                trigger_keys=[f"key{i}"],
                learning=f"correction number {i}",
                tool_name=f"tool_{i}",
                status="promoted",
            )
            await learning_store.store(learning)

        identity = AgentIdentity(
            name="test",
            soul_prompt_name="agent.test.soul",
            memory_config={"learnings": True},
        )
        builder = ContextBuilder()
        result, _ = await builder.build(
            [{"role": "user", "content": "hello"}],
            identity,
            prompt_manager=prompts,
            learning_store=learning_store,
            agent_id="test",
            org_id="",
        )

        system_msg = result[0]
        assert "correction number 0" in system_msg["content"]
        assert "correction number 1" in system_msg["content"]
        assert "correction number 2" in system_msg["content"]

    async def test_promoted_learnings_without_learning_store(self) -> None:
        """No crash when learning_store is None."""
        prompts = InMemoryPromptManager()
        await prompts.upsert("agent.test.soul", "You are a helper.")

        identity = AgentIdentity(
            name="test",
            soul_prompt_name="agent.test.soul",
            memory_config={"learnings": True},
        )
        builder = ContextBuilder()
        result, _ = await builder.build(
            [{"role": "user", "content": "hello"}],
            identity,
            prompt_manager=prompts,
            learning_store=None,
            agent_id="test",
        )

        assert result[0]["role"] == "system"
        assert "promoted" not in result[0]["content"]


# ===========================================================================
# Additional base.py coverage: RCA extraction + learning extraction with tracer
# ===========================================================================


class TestRCAExtractionInPipeline:
    """Tests for RCA extraction path in Agent.handle() (lines 360-387)."""

    async def test_rca_extraction_triggered_on_tool_failure(self) -> None:
        """RCA extractor is called when tool_history contains failures."""
        tool_history = [
            {"tool_name": "run_pytest", "arguments": {}, "result": "Error: test failed", "round": 0},
        ]
        result = ReasoningResult(
            response="Tests failed",
            done=True,
            tool_history=tool_history,
        )
        llm = FakeLLMClient()
        llm.set_simple_response("ROOT CAUSE: missing fixture\nPREVENTION: add conftest")
        learning_store = InMemoryLearningStore()
        rca_extractor = RCAExtractor(llm_client=llm, rca_model="test-model")

        agent = await _make_agent(
            llm=llm,
            strategy=FakeReactStrategy(result),
            learning_store=learning_store,
            rca_extractor=rca_extractor,
        )

        await agent.handle(
            [{"role": "user", "content": "run the test suite"}],
            build_auth_context(),
        )

        # The RCA learning should have been stored
        all_learnings = await learning_store.find_relevant("test suite")
        assert any("ROOT CAUSE" in lr.learning or "fixture" in lr.learning for lr in all_learnings)

    async def test_rca_not_triggered_without_failures(self) -> None:
        """RCA extractor is not called when tool_history has no failures."""
        tool_history = [
            {"tool_name": "run_pytest", "arguments": {}, "result": '"passed": true', "round": 0},
        ]
        result = ReasoningResult(
            response="All good",
            done=True,
            tool_history=tool_history,
        )
        llm = FakeLLMClient()
        learning_store = InMemoryLearningStore()
        rca_extractor = RCAExtractor(llm_client=llm, rca_model="test-model")

        agent = await _make_agent(
            llm=llm,
            strategy=FakeReactStrategy(result),
            learning_store=learning_store,
            rca_extractor=rca_extractor,
        )

        await agent.handle(
            [{"role": "user", "content": "run tests"}],
            build_auth_context(),
        )

        # No RCA should be stored (no LLM calls for RCA)
        all_learnings = await learning_store.find_relevant("run tests")
        rca_learnings = [lr for lr in all_learnings if lr.category == "rca"]
        assert len(rca_learnings) == 0


class TestLearningExtractionWithTracer:
    """Tests for learning extraction with tracing (lines 391-422)."""

    async def test_learning_extraction_with_tracer_active(self) -> None:
        """Learning extraction works correctly when tracing is active."""
        tool_history = [
            {
                "tool_name": "ha_control",
                "arguments": {"entity_id": "wrong.id"},
                "result": "Error: entity not found",
                "round": 0,
            },
            {
                "tool_name": "ha_control",
                "arguments": {"entity_id": "correct.id"},
                "result": '{"status": "ok"}',
                "round": 1,
            },
        ]
        result = ReasoningResult(
            response="Fixed it",
            done=True,
            tool_history=tool_history,
        )
        llm = FakeLLMClient()
        tracer = NoopTracingBackend()
        learning_store = InMemoryLearningStore()
        extractor = ToolCorrectionExtractor()

        agent = await _make_agent(
            llm=llm,
            strategy=FakeReactStrategy(result),
            tracer=tracer,
            learning_store=learning_store,
            learning_extractor=extractor,
        )

        await agent.handle(
            [{"role": "user", "content": "turn on the bedroom fan"}],
            build_auth_context(),
        )

        # Learnings should have been extracted and stored
        learnings = await learning_store.find_relevant("bedroom fan")
        assert len(learnings) > 0

    async def test_learning_extraction_without_tracer(self) -> None:
        """Learning extraction works without tracing (else branch, lines 413-422)."""
        tool_history = [
            {
                "tool_name": "ha_control",
                "arguments": {"entity_id": "wrong.id"},
                "result": "Error: entity not found",
                "round": 0,
            },
            {
                "tool_name": "ha_control",
                "arguments": {"entity_id": "correct.id"},
                "result": '{"status": "ok"}',
                "round": 1,
            },
        ]
        result = ReasoningResult(
            response="Fixed it",
            done=True,
            tool_history=tool_history,
        )
        llm = FakeLLMClient()
        learning_store = InMemoryLearningStore()
        extractor = ToolCorrectionExtractor()

        agent = await _make_agent(
            llm=llm,
            strategy=FakeReactStrategy(result),
            tracer=None,
            learning_store=learning_store,
            learning_extractor=extractor,
        )

        await agent.handle(
            [{"role": "user", "content": "turn on the bedroom fan"}],
            build_auth_context(),
        )

        learnings = await learning_store.find_relevant("bedroom fan")
        assert len(learnings) > 0
