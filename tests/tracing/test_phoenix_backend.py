"""Tests for Phoenix tracing backend.

Verifies trace creation, span nesting, attribute setting, and lifecycle.
Uses a single shared backend to avoid creating multiple BatchSpanProcessor
background threads that crash on shutdown when phoenix:6006 is unreachable.
"""

from __future__ import annotations

import pytest

from stronghold.tracing.phoenix_backend import PhoenixSpan, PhoenixTrace, PhoenixTracingBackend


@pytest.fixture(scope="module")
def backend() -> PhoenixTracingBackend:
    b = PhoenixTracingBackend(endpoint="http://localhost:6006")
    yield b
    b.shutdown()


class TestPhoenixTracingBackend:
    def test_create_trace_returns_trace_with_usable_id(
        self, backend: PhoenixTracingBackend
    ) -> None:
        """create_trace returns a trace whose trace_id is a usable string.

        Merges two trivial checks (hasattr + isinstance(str)) into one
        behavioral test: the trace_id must be a non-empty string so it
        can be used for log correlation.
        """
        trace = backend.create_trace(user_id="user-1", name="test-trace")
        assert trace is not None
        assert type(trace.trace_id) is str
        assert len(trace.trace_id) > 0
        trace.end()

    def test_trace_id_not_noop(self, backend: PhoenixTracingBackend) -> None:
        trace = backend.create_trace(name="test")
        assert trace.trace_id != "noop-trace"
        assert trace.trace_id != "noop-trace-id"
        trace.end()

    def test_create_trace_accepts_metadata_and_empty_args(
        self, backend: PhoenixTracingBackend
    ) -> None:
        """create_trace must accept both rich metadata and zero args and
        return a usable trace_id in both cases. Consolidated from two
        single-assert tests."""
        rich = backend.create_trace(
            user_id="user-1",
            session_id="sess-1",
            name="test-trace",
            metadata={"agent": "artificer", "task_type": "code"},
        )
        bare = backend.create_trace()
        assert rich.trace_id
        assert bare.trace_id
        assert rich.trace_id != bare.trace_id
        rich.end()
        bare.end()


class TestPhoenixTraceSpans:
    def test_span_context_manager(self, backend: PhoenixTracingBackend) -> None:
        trace = backend.create_trace(name="test")

        with trace.span("test-span") as span:
            assert span is not None

        trace.end()


class TestSpanAttributes:
    def test_set_methods_return_self_for_chaining(self, backend: PhoenixTracingBackend) -> None:
        """set_input, set_output and set_usage all return the span itself so
        callers can write span.set_input(...).set_output(...).set_usage(...).
        This one test covers the fluent-API contract; previously there were
        three tests that each re-created a backend just to assert
        result is span."""
        trace = backend.create_trace(name="test")

        with trace.span("llm-call") as span:
            chained = (
                span.set_input({"query": "hello"})
                .set_output({"response": "world"})
                .set_usage(input_tokens=100, output_tokens=50, model="m")
            )
            assert chained is span

        trace.end()
