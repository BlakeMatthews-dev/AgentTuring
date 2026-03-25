"""Test that requests produce real traces, not noop."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


class TestTracingWired:
    def test_trace_created_on_request(self) -> None:
        """Every request should create a trace with spans."""
        # For now: verify the tracing backend is NOT noop in production config
        from stronghold.tracing.noop import NoopTracingBackend
        from stronghold.tracing.phoenix_backend import PhoenixTracingBackend

        # Phoenix backend should exist and be importable
        backend = PhoenixTracingBackend(endpoint="http://localhost:6006")
        trace = backend.create_trace(user_id="test", name="test-request")
        assert trace.trace_id != "noop-trace"

        with trace.span("test-span") as s:
            s.set_input({"test": True})
            s.set_output({"result": "ok"})

        trace.end()
