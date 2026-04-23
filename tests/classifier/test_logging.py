"""Tests for ClassifierLogger.

Spec: Audit logging for classification decisions with enable/disable toggle.
AC: log_decision records decisions, get_decisions filters by time/limit,
    get_stats returns distribution, disable_audit makes log a no-op,
    clear resets state.
Edge cases: disabled audit ignores logs, empty stats returns {total:0},
            limit filter, since filter.
Contracts: log_decision is void, get_decisions returns list, get_stats returns dict.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from stronghold.classifier.logging import ClassifierLogger


class TestLogDecision:
    def test_records_decision(self) -> None:
        cl = ClassifierLogger()
        cl.log_decision("hello", None, "chat", 0.9, "simple", "arbiter")
        decisions = cl.get_decisions()
        assert len(decisions) == 1
        assert decisions[0].classified_intent == "chat"

    def test_disabled_audit_is_noop(self) -> None:
        cl = ClassifierLogger()
        cl.disable_audit()
        cl.log_decision("hello", None, "chat", 0.9, "simple", "arbiter")
        assert cl.get_decisions() == []


class TestAuditToggle:
    def test_enable_audit(self) -> None:
        cl = ClassifierLogger()
        cl.disable_audit()
        cl.enable_audit()
        cl.log_decision("hi", None, "chat", 0.8, "simple", "arbiter")
        assert len(cl.get_decisions()) == 1

    def test_disable_audit(self) -> None:
        cl = ClassifierLogger()
        cl.log_decision("hi", None, "chat", 0.8, "simple", "arbiter")
        cl.disable_audit()
        cl.log_decision("bye", None, "code", 0.7, "complex", "mason")
        assert len(cl.get_decisions()) == 1


class TestGetDecisions:
    def test_filter_by_since(self) -> None:
        import time

        cl = ClassifierLogger()
        cl.log_decision("old", None, "chat", 0.9, "simple", "arbiter")
        time.sleep(0.01)
        cutoff = datetime.now(UTC)
        time.sleep(0.01)
        cl.log_decision("new", None, "code", 0.8, "complex", "mason")
        decisions = cl.get_decisions(since=cutoff)
        assert len(decisions) == 1
        assert decisions[0].input_text == "new"

    def test_limit(self) -> None:
        cl = ClassifierLogger()
        for i in range(10):
            cl.log_decision(f"q-{i}", None, "chat", 0.5, "simple", "arbiter")
        decisions = cl.get_decisions(limit=3)
        assert len(decisions) == 3


class TestGetStats:
    def test_empty_stats(self) -> None:
        cl = ClassifierLogger()
        stats = cl.get_stats()
        assert stats == {"total": 0}

    def test_distribution(self) -> None:
        cl = ClassifierLogger()
        cl.log_decision("a", None, "chat", 0.9, "simple", "arbiter")
        cl.log_decision("b", None, "chat", 0.8, "simple", "arbiter")
        cl.log_decision("c", None, "code", 0.7, "complex", "mason")
        stats = cl.get_stats()
        assert stats["total"] == 3
        assert stats["intent_distribution"]["chat"] == 2
        assert stats["intent_distribution"]["code"] == 1
        assert stats["agent_distribution"]["arbiter"] == 2
        assert stats["agent_distribution"]["mason"] == 1


class TestClear:
    def test_clear_empties_decisions(self) -> None:
        cl = ClassifierLogger()
        cl.log_decision("a", None, "chat", 0.9, "simple", "arbiter")
        cl.clear()
        assert cl.get_decisions() == []
        assert cl.get_stats() == {"total": 0}
