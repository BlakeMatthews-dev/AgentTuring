"""Tests for runtime/workload.py — WorkloadDriver + scenario loading."""

from __future__ import annotations

import random
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from turing.motivation import ACTION_CADENCE_TICKS, Motivation
from turing.reactor import FakeReactor
from turing.repo import Repo
from turing.runtime.workload import (
    ContradictionInjection,
    Scenario,
    StreamSpec,
    WorkloadDriver,
    load_scenario,
)
from turing.scheduler import Scheduler
from turing.types import MemoryTier, SourceKind


@pytest.fixture
def scenario_dir(tmp_path: Path) -> Path:
    return tmp_path


def test_load_scenario_baseline_round_trip(scenario_dir: Path) -> None:
    scenario_file = scenario_dir / "s.yaml"
    scenario_file.write_text(
        """
streams:
  - kind: p1_chat
    class_: 1
    every_seconds: 5
    fit: {gemini: 1.0}
  - kind: p4_asap
    class_: 4
    every_seconds: 10
    outcome_success_rate: 0.5
contradictions:
  - intent: route
    a_content: X is true
    b_content: X is false
    c_content: X is true
    after_seconds: 2
"""
    )
    scenario = load_scenario(scenario_file)
    assert len(scenario.streams) == 2
    assert scenario.streams[0].kind == "p1_chat"
    assert scenario.streams[0].fit == {"gemini": 1.0}
    assert scenario.streams[1].outcome_success_rate == 0.5
    assert len(scenario.contradictions) == 1
    assert scenario.contradictions[0].intent == "route"


def test_driver_emits_items_on_cadence(repo: Repo, self_id: str) -> None:
    reactor = FakeReactor()
    motivation = Motivation(reactor)
    scheduler = Scheduler(reactor, motivation)

    stream = StreamSpec(
        kind="p1_chat",
        class_=1,
        every_seconds=0.0,             # emit immediately every tick
        jitter_seconds=0.0,
        fit={"gemini": 1.0},
        intent="chat",
    )
    scenario = Scenario(streams=(stream,))

    driver = WorkloadDriver(
        scenario=scenario,
        motivation=motivation,
        reactor=reactor,
        scheduler=scheduler,
        repo=repo,
        self_id=self_id,
        rng=random.Random(0),
    )

    reactor.tick(1)
    # One emit per tick (interval = 0s)
    items = [b for b in motivation.backlog if b.kind == "p1_chat"]
    assert len(items) >= 1


def test_dispatch_mints_accomplishments_on_success(
    repo: Repo, self_id: str
) -> None:
    reactor = FakeReactor()
    motivation = Motivation(reactor)
    scheduler = Scheduler(reactor, motivation)

    stream = StreamSpec(
        kind="p1_chat",
        class_=1,
        every_seconds=0.0,
        jitter_seconds=0.0,
        fit={"gemini": 1.0},
        intent="chat-turn",
        outcome_success_rate=1.0,                # always succeeds
        outcome_affect_range=(0.5, 0.7),
        outcome_surprise_range=(0.5, 0.7),
    )
    scenario = Scenario(streams=(stream,))

    WorkloadDriver(
        scenario=scenario,
        motivation=motivation,
        reactor=reactor,
        scheduler=scheduler,
        repo=repo,
        self_id=self_id,
        rng=random.Random(0),
    )

    reactor.tick(ACTION_CADENCE_TICKS * 3)

    accomplishments = list(
        repo.find(
            self_id=self_id,
            tier=MemoryTier.ACCOMPLISHMENT,
            source=SourceKind.I_DID,
        )
    )
    assert accomplishments, "expected at least one ACCOMPLISHMENT"


def test_dispatch_mints_regrets_on_failure(
    repo: Repo, self_id: str
) -> None:
    reactor = FakeReactor()
    motivation = Motivation(reactor)
    scheduler = Scheduler(reactor, motivation)

    stream = StreamSpec(
        kind="p4_asap",
        class_=4,
        every_seconds=0.0,
        jitter_seconds=0.0,
        fit={"gemini": 1.0},
        intent="async-task",
        outcome_success_rate=0.0,                # always fails
        outcome_affect_range=(0.5, 0.7),
        outcome_surprise_range=(0.5, 0.7),
    )
    scenario = Scenario(streams=(stream,))

    WorkloadDriver(
        scenario=scenario,
        motivation=motivation,
        reactor=reactor,
        scheduler=scheduler,
        repo=repo,
        self_id=self_id,
        rng=random.Random(0),
    )

    reactor.tick(ACTION_CADENCE_TICKS * 3)

    regrets = list(
        repo.find(
            self_id=self_id,
            tier=MemoryTier.REGRET,
            source=SourceKind.I_DID,
        )
    )
    assert regrets, "expected at least one REGRET"


def test_contradiction_injection_creates_triple(
    repo: Repo, self_id: str
) -> None:
    reactor = FakeReactor()
    motivation = Motivation(reactor)
    scheduler = Scheduler(reactor, motivation)

    scenario = Scenario(
        streams=(),
        contradictions=(
            ContradictionInjection(
                intent="route-writing-request",
                a_content="artificer fits here is true",
                b_content="artificer fits here is false",
                c_content="artificer fits here is false",
                after_seconds=0.0,                 # fire immediately
            ),
        ),
    )

    WorkloadDriver(
        scenario=scenario,
        motivation=motivation,
        reactor=reactor,
        scheduler=scheduler,
        repo=repo,
        self_id=self_id,
    )

    reactor.tick(1)

    affirmations = list(
        repo.find(
            self_id=self_id,
            tier=MemoryTier.AFFIRMATION,
            source=SourceKind.I_DID,
        )
    )
    observations = list(
        repo.find(
            self_id=self_id,
            tier=MemoryTier.OBSERVATION,
            source=SourceKind.I_DID,
        )
    )
    assert len(affirmations) == 2
    assert any(o.content == "artificer fits here is false" for o in observations)


def test_contradiction_injection_fires_once(
    repo: Repo, self_id: str
) -> None:
    reactor = FakeReactor()
    motivation = Motivation(reactor)
    scheduler = Scheduler(reactor, motivation)

    scenario = Scenario(
        streams=(),
        contradictions=(
            ContradictionInjection(
                intent="x",
                a_content="X is true",
                b_content="X is false",
                c_content="X is true",
                after_seconds=0.0,
            ),
        ),
    )
    WorkloadDriver(
        scenario=scenario,
        motivation=motivation,
        reactor=reactor,
        scheduler=scheduler,
        repo=repo,
        self_id=self_id,
    )
    reactor.tick(5)
    affs = list(
        repo.find(
            self_id=self_id,
            tier=MemoryTier.AFFIRMATION,
            source=SourceKind.I_DID,
        )
    )
    # Exactly 2 (a_content + b_content), even after 5 ticks.
    assert len(affs) == 2
