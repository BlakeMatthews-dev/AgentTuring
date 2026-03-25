"""Tests for Phoenix tracing backend.

Verifies trace creation, span nesting, attribute setting, and lifecycle.
"""

from __future__ import annotations

from stronghold.tracing.phoenix_backend import PhoenixSpan, PhoenixTrace, PhoenixTracingBackend


class TestPhoenixTracingBackend:
    def test_create_trace_returns_trace(self) -> None:
        backend = PhoenixTracingBackend(endpoint="http://localhost:6006")
        trace = backend.create_trace(user_id="user-1", name="test-trace")
        assert trace is not None
        assert hasattr(trace, "trace_id")
        trace.end()

    def test_trace_id_is_string(self) -> None:
        backend = PhoenixTracingBackend(endpoint="http://localhost:6006")
        trace = backend.create_trace(name="test")
        assert isinstance(trace.trace_id, str)
        assert len(trace.trace_id) > 0
        trace.end()

    def test_trace_id_not_noop(self) -> None:
        backend = PhoenixTracingBackend(endpoint="http://localhost:6006")
        trace = backend.create_trace(name="test")
        assert trace.trace_id != "noop-trace"
        assert trace.trace_id != "noop-trace-id"
        trace.end()

    def test_create_trace_with_metadata(self) -> None:
        backend = PhoenixTracingBackend(endpoint="http://localhost:6006")
        trace = backend.create_trace(
            user_id="user-1",
            session_id="sess-1",
            name="test-trace",
            metadata={"agent": "artificer", "task_type": "code"},
        )
        assert trace.trace_id
        trace.end()

    def test_create_trace_with_empty_args(self) -> None:
        backend = PhoenixTracingBackend(endpoint="http://localhost:6006")
        trace = backend.create_trace()
        assert trace.trace_id
        trace.end()


class TestPhoenixTraceSpans:
    def test_span_context_manager(self) -> None:
        backend = PhoenixTracingBackend(endpoint="http://localhost:6006")
        trace = backend.create_trace(name="test")

        with trace.span("test-span") as span:
            assert span is not None

        trace.end()

    def test_child_spans_created_under_parent(self) -> None:
        backend = PhoenixTracingBackend(endpoint="http://localhost:6006")
        trace = backend.create_trace(name="parent-trace")

        with trace.span("child-1") as s1:
            s1.set_input({"data": "first"})

        with trace.span("child-2") as s2:
            s2.set_input({"data": "second"})

        # Both spans should complete without error
        trace.end()

    def test_multiple_nested_spans(self) -> None:
        backend = PhoenixTracingBackend(endpoint="http://localhost:6006")
        trace = backend.create_trace(name="nested")

        with trace.span("classify"):
            pass

        with trace.span("route"):
            pass

        with trace.span("agent.handle"):
            pass

        trace.end()


class TestSpanAttributes:
    def test_set_input(self) -> None:
        backend = PhoenixTracingBackend(endpoint="http://localhost:6006")
        trace = backend.create_trace(name="test")

        with trace.span("test-span") as span:
            result = span.set_input({"query": "hello"})
            # set_input returns self for chaining
            assert result is span

        trace.end()

    def test_set_output(self) -> None:
        backend = PhoenixTracingBackend(endpoint="http://localhost:6006")
        trace = backend.create_trace(name="test")

        with trace.span("test-span") as span:
            result = span.set_output({"response": "world"})
            assert result is span

        trace.end()

    def test_set_usage(self) -> None:
        backend = PhoenixTracingBackend(endpoint="http://localhost:6006")
        trace = backend.create_trace(name="test")

        with trace.span("llm-call") as span:
            result = span.set_usage(
                input_tokens=100,
                output_tokens=50,
                model="test-model",
            )
            assert result is span

        trace.end()

    def test_chained_attribute_calls(self) -> None:
        backend = PhoenixTracingBackend(endpoint="http://localhost:6006")
        trace = backend.create_trace(name="test")

        with trace.span("test-span") as span:
            span.set_input({"q": "hello"}).set_output({"r": "world"}).set_usage(
                input_tokens=10, output_tokens=5
            )

        trace.end()


class TestTraceLifecycle:
    def test_trace_end_completes(self) -> None:
        backend = PhoenixTracingBackend(endpoint="http://localhost:6006")
        trace = backend.create_trace(name="test")
        # Should not raise
        trace.end()

    def test_trace_score(self) -> None:
        backend = PhoenixTracingBackend(endpoint="http://localhost:6006")
        trace = backend.create_trace(name="test")
        # Should not raise
        trace.score("quality", 0.95, comment="good response")
        trace.end()

    def test_trace_update_metadata(self) -> None:
        backend = PhoenixTracingBackend(endpoint="http://localhost:6006")
        trace = backend.create_trace(name="test")
        trace.update({"model": "gpt-4", "agent": "artificer", "task_type": "code"})
        trace.end()

    def test_trace_full_lifecycle(self) -> None:
        """Simulate a real request trace lifecycle."""
        backend = PhoenixTracingBackend(endpoint="http://localhost:6006")
        trace = backend.create_trace(
            user_id="user-1",
            session_id="sess-1",
            name="route_request",
        )

        # Classify
        with trace.span("conduit.classify") as cs:
            cs.set_input({"text": "write a function"})
            cs.set_output({"task_type": "code", "classified_by": "keywords"})

        # Route
        with trace.span("conduit.route") as rs:
            rs.set_input({"task_type": "code"})
            rs.set_output({"model": "test/large", "score": 0.85})

        # Agent handle
        with trace.span("agent.artificer") as ags:
            ags.set_input({"message_count": 3})
            ags.set_output({"response_length": 500})
            ags.set_usage(input_tokens=200, output_tokens=100, model="test/large")

        trace.update({"model": "test/large", "agent": "artificer"})
        trace.score("quality", 0.9)
        trace.end()

    def test_flush_does_not_raise(self) -> None:
        backend = PhoenixTracingBackend(endpoint="http://localhost:6006")
        # flush() should not raise even if Phoenix is not reachable
        backend.flush()
