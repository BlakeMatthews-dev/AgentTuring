"""Tests for specs/self-bootstrap.md: AC-33.1..3, 33.7, 33.9.

Verify that finalize() registers interval triggers on the reactor.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from turing.reactor import FakeReactor
from turing.self_bootstrap import finalize
from turing.self_mood import tick_mood_decay


# --------- AC-33.1 mood-decay trigger registered -----------------------------


def test_ac_33_1_mood_decay_trigger_exists(srepo, self_id) -> None:
    reactor = FakeReactor()
    finalize(repo=srepo, self_id=self_id, reactor=reactor)
    name = f"mood-decay:{self_id}"
    assert name in reactor.triggers
    assert reactor.triggers[name].interval == timedelta(hours=1)


# --------- AC-33.2 personality-retest trigger registered ---------------------


def test_ac_33_2_personality_retest_trigger_exists(srepo, self_id) -> None:
    reactor = FakeReactor()
    finalize(repo=srepo, self_id=self_id, reactor=reactor)
    name = f"personality-retest:{self_id}"
    assert name in reactor.triggers
    assert reactor.triggers[name].interval == timedelta(days=7)


# --------- AC-33.3 idempotent re-finalize does not duplicate -----------------


def test_ac_33_3_idempotent_finalize_no_duplicates(srepo, self_id) -> None:
    reactor = FakeReactor()
    finalize(repo=srepo, self_id=self_id, reactor=reactor)
    srepo._conn.execute("DELETE FROM self_mood WHERE self_id = ?", (self_id,))
    srepo._conn.commit()
    finalize(repo=srepo, self_id=self_id, reactor=reactor)
    assert len(reactor.triggers) == 2
    assert f"mood-decay:{self_id}" in reactor.triggers
    assert f"personality-retest:{self_id}" in reactor.triggers


# --------- AC-33.7 firing mood trigger updates mood --------------------------


def test_ac_33_7_firing_mood_trigger_updates_mood(srepo, self_id) -> None:
    reactor = FakeReactor()
    finalize(repo=srepo, self_id=self_id, reactor=reactor)

    m = srepo.get_mood(self_id)
    m.valence = 0.8
    m.last_tick_at = datetime.now(UTC) - timedelta(hours=3)
    srepo.update_mood(m)

    before = srepo.get_mood(self_id).valence
    reactor.fire_trigger(f"mood-decay:{self_id}")
    after = srepo.get_mood(self_id).valence

    assert after < before
    trigger = reactor.triggers[f"mood-decay:{self_id}"]
    assert trigger.fire_count == 1


# --------- AC-33.9 unregister removes both triggers --------------------------


def test_ac_33_9_unregister_removes_triggers(srepo, self_id) -> None:
    reactor = FakeReactor()
    finalize(repo=srepo, self_id=self_id, reactor=reactor)
    reactor.unregister_trigger(f"mood-decay:{self_id}")
    reactor.unregister_trigger(f"personality-retest:{self_id}")
    assert len(reactor.triggers) == 0


# --------- finalize without reactor still creates mood -----------------------


def test_finalize_without_reactor_creates_mood(srepo, self_id) -> None:
    finalize(repo=srepo, self_id=self_id, reactor=None)
    m = srepo.get_mood(self_id)
    assert (m.valence, m.arousal, m.focus) == (0.0, 0.3, 0.5)
