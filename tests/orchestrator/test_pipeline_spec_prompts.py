"""Tests for spec-enriched pipeline prompts.

Spec: specs/spec-enriched-prompts.yaml
Invariants tested:
  - spec_summary_contains_invariants: all invariant names appear in summary
  - spec_summary_contains_criteria: all acceptance criteria appear in summary
  - no_spec_no_error: pipeline completes normally without a spec
  - summary_bounded: spec_summary never exceeds 2000 chars
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from hypothesis import given, settings
from hypothesis import strategies as st

from stronghold.orchestrator.pipeline import BuilderPipeline, build_spec_summary
from stronghold.types.spec import Invariant, InvariantKind, Spec


# ── Hypothesis strategies ──────────────────────────────────────────

_name = st.text(min_size=1, max_size=30, alphabet=st.characters(categories=("L", "N")))
_description = st.text(min_size=1, max_size=100, alphabet=st.characters(categories=("L", "N", "Z")))
_criterion = st.text(min_size=1, max_size=100, alphabet=st.characters(categories=("L", "N", "Z")))
_kind = st.sampled_from(list(InvariantKind))


@st.composite
def _invariant(draw: st.DrawFn) -> Invariant:
    return Invariant(
        name=draw(_name),
        description=draw(_description),
        kind=draw(_kind),
        expression="True",
    )


@st.composite
def _spec(draw: st.DrawFn) -> Spec:
    invariants = draw(st.tuples(*[_invariant() for _ in range(draw(st.integers(0, 5)))]))
    criteria = draw(st.tuples(*[_criterion for _ in range(draw(st.integers(0, 5)))]))
    protocols = draw(st.tuples(*[_name for _ in range(draw(st.integers(0, 3)))]))
    return Spec(
        issue_number=draw(st.integers(1, 10000)),
        title=draw(_description),
        invariants=invariants,
        acceptance_criteria=criteria,
        protocols_touched=protocols,
    )


# ── Property tests (spec invariants) ──────────────────────────────


class TestSpecSummaryProperties:
    @given(spec=_spec())
    @settings(max_examples=50)
    def test_summary_bounded(self, spec: Spec) -> None:
        """Invariant: summary_bounded — never exceeds 2000 chars."""
        summary = build_spec_summary(spec)
        assert len(summary) <= 2000

    @given(spec=_spec())
    @settings(max_examples=50)
    def test_contains_invariant_names(self, spec: Spec) -> None:
        """Invariant: spec_summary_contains_invariants."""
        summary = build_spec_summary(spec)
        if len(summary) < 2000:
            for inv in spec.invariants:
                assert inv.name in summary

    @given(spec=_spec())
    @settings(max_examples=50)
    def test_contains_acceptance_criteria(self, spec: Spec) -> None:
        """Invariant: spec_summary_contains_criteria."""
        summary = build_spec_summary(spec)
        if len(summary) < 2000:
            for criterion in spec.acceptance_criteria:
                assert criterion in summary


# ── Example-based tests ───────────────────────────────────────────


class TestBuildSpecSummary:
    def test_empty_spec_returns_minimal_summary(self) -> None:
        spec = Spec(issue_number=1, title="trivial")
        summary = build_spec_summary(spec)
        assert "trivial" in summary
        assert len(summary) <= 2000

    def test_includes_protocols(self) -> None:
        spec = Spec(
            issue_number=1,
            title="test",
            protocols_touched=("LLMClient", "LearningStore"),
        )
        summary = build_spec_summary(spec)
        assert "LLMClient" in summary
        assert "LearningStore" in summary

    def test_truncates_long_content(self) -> None:
        long_criteria = tuple(f"criterion_{i}" * 50 for i in range(50))
        spec = Spec(
            issue_number=1,
            title="test",
            acceptance_criteria=long_criteria,
        )
        summary = build_spec_summary(spec)
        assert len(summary) <= 2000


# ── Pipeline integration with spec summary ────────────────────────


class _FakeWorkItem:
    def __init__(self, content: str = "ok") -> None:
        from stronghold.orchestrator.engine import WorkStatus

        self.status = WorkStatus.COMPLETED
        self.result: dict[str, Any] = {
            "choices": [{"message": {"content": content}}],
        }
        self.error = ""


class _FakeContainer:
    def __init__(self) -> None:
        self.agents = {
            "quartermaster": object(),
            "archie": object(),
            "mason": object(),
            "auditor": object(),
            "gatekeeper": object(),
        }


class _FakeEngine:
    def __init__(self) -> None:
        self._container = _FakeContainer()
        self.dispatched: list[dict[str, Any]] = []
        self.has_agent = lambda name: name in self._container.agents

    def dispatch(self, **kwargs: Any) -> None:
        self.dispatched.append(kwargs)

    def get(self, work_id: str) -> _FakeWorkItem:
        return _FakeWorkItem()

    def cancel(self, work_id: str) -> bool:
        return True


class TestPipelineSpecPrompts:
    async def test_spec_summary_in_dispatch_prompt(self) -> None:
        """When a spec exists, the dispatched prompt contains spec summary."""
        from tests.fakes import FakeSpecStore, FakeSpecVerifier

        spec = Spec(
            issue_number=42,
            title="Add caching",
            protocols_touched=("LLMClient",),
            invariants=(
                Invariant(
                    name="cache_hit",
                    description="Cache returns stored value",
                    kind=InvariantKind.POSTCONDITION,
                    expression="True",
                ),
            ),
            acceptance_criteria=("Cache hit returns stored response",),
        )
        store = FakeSpecStore()
        await store.save(spec)

        engine = _FakeEngine()
        pipeline = BuilderPipeline(engine, spec_store=store, spec_verifier=FakeSpecVerifier())

        with patch("asyncio.sleep", return_value=None):
            await pipeline.execute(issue_number=42, title="Add caching", skip_decompose=True)

        first_prompt = engine.dispatched[0]["messages"][0]["content"]
        assert "cache_hit" in first_prompt
        assert "Cache hit returns stored response" in first_prompt

    async def test_no_spec_no_keyerror(self) -> None:
        """Invariant: no_spec_no_error — no KeyError on {spec_summary}."""
        engine = _FakeEngine()
        pipeline = BuilderPipeline(engine)

        with patch("asyncio.sleep", return_value=None):
            run = await pipeline.execute(issue_number=99, title="No spec", skip_decompose=True)

        assert run.status == "completed"
