"""Tests for FakeOutcomeStore class skeleton."""

from __future__ import annotations

# Import the test container factory — DO NOT construct Container manually
from tests.fakes import make_test_container

AUTH_HEADER = {"Authorization": "Bearer sk-test"}


def test_fake_outcome_store_exists() -> None:
    """Verify FakeOutcomeStore class skeleton exists in tests/fakes.py."""
    container = make_test_container()
    assert hasattr(container.outcome_store, "__class__")
    assert container.outcome_store.__class__.__name__ == "InMemoryOutcomeStore"


def test_fake_outcome_store_is_initially_empty() -> None:
    """Verify FakeOutcomeStore class is initially empty."""
    container = make_test_container()
    outcome_store = container.outcome_store
    assert outcome_store._outcomes == []


def test_fake_outcome_store_implements_outcome_store_protocol() -> None:
    """Verify FakeOutcomeStore implements OutcomeStore protocol."""
    from stronghold.memory.outcomes import InMemoryOutcomeStore

    container = make_test_container()
    assert isinstance(container.outcome_store, InMemoryOutcomeStore)
