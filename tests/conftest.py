"""Shared test fixtures, fakes, and configuration.

Test Tiers
----------
Tests are organized into three tiers for CI efficiency:

  critical  — Fast regression (<3s total). Runs on EVERY change.
              Covers: auth, warden blocks, pipeline routes, scoring invariants.
  happy     — One happy-path per feature (~10s). Runs on feature branch push.
              Covers: each module's golden path (CRUD, classify, route, memory, etc.)
  (unmarked)— Full suite (~50s). Runs pre-commit / pre-merge.
              Covers: edge cases, extended properties, integration, all API routes.

Run a tier:
  pytest -m critical        # ~120 tests, <3s
  pytest -m happy           # ~400 tests, <10s
  pytest                    # all 1700+ tests, ~50s
  pytest -m "not perf"      # everything except real-LLM perf tests
"""

from __future__ import annotations

import os

import pytest


# ── Session-wide env hygiene ─────────────────────────────────────────
# CI sets ROUTER_API_KEY=sk-ci-test-key-minimum-32-characters which
# overrides any yaml-loaded key. Integration tests hardcode the
# Authorization header to "sk-example-stronghold" (the example.yaml
# value), so without forcing this env var the tests would 401 in CI.
# Using a session-scoped autouse fixture avoids requiring every
# integration test to know about CI's env layer.
os.environ["ROUTER_API_KEY"] = "sk-example-stronghold"

from stronghold.types.config import (
    RoutingConfig,
    SecurityConfig,
    SessionsConfig,
    StrongholdConfig,
    TaskTypeConfig,
)

from .fakes import (
    FakeAuthProvider,
    FakeLLMClient,
    FakePromptManager,
    FakeQuotaTracker,
    NoopTracingBackend,
)


# ── Tier assignment: file path → marker ──────────────────────────────
# Critical tier: tests that must pass on every single change.
# These cover the "contract" — auth works, security blocks, pipeline routes,
# routing math is sound, types construct.
_CRITICAL_FILES = {
    # Security — injection blocked, PII redacted, gate sanitizes
    "security/test_gate.py",
    "security/test_prompt_injection.py",
    "security/test_pii_filter.py",
    "security/test_warden_heuristics.py",
    "security/test_rate_limiter.py",
    "security/test_schema_validation.py",
    # Auth — tokens validated, keys checked, permissions enforced
    "auth/test_static_key.py",
    "auth/test_jwt_auth.py",
    "auth/test_permissions.py",
    # Routing — scoring formula invariants, tier filtering, fallback
    "routing/test_scoring_properties.py",
    "routing/test_tier_filtering.py",
    "routing/test_fallback.py",
    # Classification — keyword engine, complexity
    "classification/test_classifier_engine.py",
    "classification/test_keyword_matching.py",
    # Core pipeline — E2E, route_request, strategies
    "integration/test_full_pipeline_e2e.py",
    "container/test_route_request.py",
    "agents/test_strategies.py",
    # Types — data model construction
    "test_types.py",
    # Config — loads without crashing
    "config/test_validation.py",
}

# Happy-path tier: one golden-path test per feature module.
# These cover breadth — does each feature work at all?
_HAPPY_FILES = {
    # All critical files are also happy-path
    *_CRITICAL_FILES,
    # Security extended
    "security/test_warden_extended.py",
    "security/test_sentinel_pipeline.py",
    "security/test_audit_log.py",
    "security/test_gate_sufficiency.py",
    "security/test_llm_classifier.py",
    "security/test_flag_response.py",
    "security/test_semantic_poisoning.py",
    "security/test_warden_isolation.py",
    # Auth extended
    "auth/test_openwebui_headers.py",
    # Routing extended
    "routing/test_scarcity_curve.py",
    "routing/test_strength_matching.py",
    "routing/test_modality_filtering.py",
    "routing/test_speed_bonus.py",
    "routing/test_quota_integration.py",
    # Classification extended
    "classification/test_complexity.py",
    "classification/test_multi_intent.py",
    "classification/test_priority.py",
    "classification/test_llm_fallback.py",
    # Agents — core handle, request analysis, agent store
    "agents/test_agent_handle.py",
    "agents/test_request_analyzer.py",
    "agents/test_context_filter.py",
    "agents/test_full_pipeline.py",
    "agents/test_agent_store.py",
    "agents/test_task_queue.py",
    "agents/test_worker.py",
    # Memory — learnings, episodic tiers, scope isolation
    "memory/test_learning_feedback.py",
    "memory/test_learning_storage.py",
    "memory/test_episodic_tiers.py",
    "memory/test_scope_isolation.py",
    "memory/test_correction_extraction.py",
    "memory/test_mutations.py",
    # Sessions — CRUD, store
    "sessions/test_crud.py",
    "sessions/test_session_store.py",
    # Skills — registry, parser, forge
    "skills/test_registry.py",
    "skills/test_parser.py",
    "skills/test_forge.py",
    # Prompts — store, diff
    "prompts/test_prompt_store.py",
    "prompts/test_diff.py",
    # Tools — registry, executor
    "tools/test_registry.py",
    "tools/test_executor.py",
    # Quota — tracker
    "quota/test_quota_tracker.py",
    "quota/test_billing.py",
    # Integration — HTTP lifecycle, warden-in-pipeline, gate
    "integration/test_http_lifecycle.py",
    "integration/test_warden_in_pipeline.py",
    "integration/test_gate.py",
    # Config
    "config/test_loader.py",
    "config/test_env_override.py",
    # Reactor
    "reactor/test_reactor.py",
    # Tracing
    "tracing/test_phoenix_backend.py",
    # Properties
    "properties/test_tenant_isolation.py",
    # Types
    "types/test_prompt_types.py",
}


def _file_suffix(nodeid: str) -> str:
    """Extract the path suffix after 'tests/' from a pytest node ID."""
    # nodeid looks like "tests/security/test_gate.py::TestClass::test_method"
    parts = nodeid.split("::")
    filepath = parts[0]  # "tests/security/test_gate.py"
    if filepath.startswith("tests/"):
        return filepath[len("tests/") :]
    return filepath


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Auto-assign critical/happy markers based on file membership."""
    critical_marker = pytest.mark.critical
    happy_marker = pytest.mark.happy

    for item in items:
        suffix = _file_suffix(item.nodeid)
        if suffix in _CRITICAL_FILES:
            item.add_marker(critical_marker)
            item.add_marker(happy_marker)
        elif suffix in _HAPPY_FILES:
            item.add_marker(happy_marker)


@pytest.fixture
def fake_config() -> StrongholdConfig:
    """Minimal valid Stronghold config for tests."""
    return StrongholdConfig(
        providers={
            "test_provider": {
                "status": "active",
                "billing_cycle": "monthly",
                "free_tokens": 1_000_000_000,
            },
            "small_provider": {
                "status": "active",
                "billing_cycle": "daily",
                "free_tokens": 1_000_000,
            },
            "inactive_provider": {
                "status": "inactive",
                "billing_cycle": "monthly",
                "free_tokens": 100_000,
            },
        },
        models={
            "test-small": {
                "provider": "test_provider",
                "tier": "small",
                "quality": 0.4,
                "speed": 120,
                "litellm_id": "test/small",
                "strengths": ["chat"],
            },
            "test-medium": {
                "provider": "test_provider",
                "tier": "medium",
                "quality": 0.6,
                "speed": 500,
                "litellm_id": "test/medium",
                "strengths": ["code", "reasoning"],
            },
            "test-large": {
                "provider": "test_provider",
                "tier": "large",
                "quality": 0.9,
                "speed": 100,
                "litellm_id": "test/large",
                "strengths": ["code", "reasoning", "creative"],
            },
            "test-fast": {
                "provider": "small_provider",
                "tier": "small",
                "quality": 0.3,
                "speed": 2000,
                "litellm_id": "test/fast",
                "strengths": ["chat"],
            },
        },
        task_types={
            "chat": TaskTypeConfig(
                keywords=["hello", "hi", "hey", "thanks"],
                min_tier="small",
                preferred_strengths=["chat"],
            ),
            "code": TaskTypeConfig(
                keywords=["code", "function", "bug", "error", "implement"],
                min_tier="medium",
                preferred_strengths=["code"],
            ),
            "automation": TaskTypeConfig(
                keywords=["light", "fan", "turn on", "turn off", "chore"],
                min_tier="small",
                preferred_strengths=["chat"],
            ),
            "search": TaskTypeConfig(
                keywords=["search", "look up", "find"],
                min_tier="small",
                preferred_strengths=["chat"],
            ),
        },
        routing=RoutingConfig(),
        sessions=SessionsConfig(),
        security=SecurityConfig(),
        permissions={
            "admin": ["*"],
            "engineer": ["web_search", "file_ops", "shell"],
            "viewer": ["web_search"],
        },
        router_api_key="sk-test-key",
        jwt_secret="sk-test-jwt-secret-key-for-testing",
    )


@pytest.fixture
def fake_llm() -> FakeLLMClient:
    """Fake LLM client with configurable responses."""
    return FakeLLMClient()


@pytest.fixture
def fake_tracer() -> NoopTracingBackend:
    """No-op tracing backend."""
    return NoopTracingBackend()


@pytest.fixture
def fake_prompts() -> FakePromptManager:
    """Dict-backed prompt manager."""
    return FakePromptManager()


@pytest.fixture
def fake_quota() -> FakeQuotaTracker:
    """Fake quota tracker with configurable usage."""
    return FakeQuotaTracker()


@pytest.fixture
def fake_auth() -> FakeAuthProvider:
    """Fake auth provider that always returns system auth."""
    return FakeAuthProvider()
