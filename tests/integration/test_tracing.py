"""Test that requests produce real traces, not noop."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stronghold.tracing.phoenix_backend import PhoenixTracingBackend


@pytest.fixture(scope="module")
def phoenix_backend() -> PhoenixTracingBackend:
    b = PhoenixTracingBackend(endpoint="http://localhost:6006")
    yield b
    b.shutdown()


class TestTracingWired:
    def test_trace_created_on_request(self, phoenix_backend: PhoenixTracingBackend) -> None:
        """Every request should create a trace with spans."""
        trace = phoenix_backend.create_trace(user_id="test", name="test-request")
        assert trace.trace_id != "noop-trace"

        with trace.span("test-span") as s:
            s.set_input({"test": True})
            s.set_output({"result": "ok"})

        trace.end()
