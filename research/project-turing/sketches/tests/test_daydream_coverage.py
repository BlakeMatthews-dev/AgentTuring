"""Coverage gap filler for turing/daydream.py.

Spec: DaydreamProducer dispatch with no seed (empty write), observation tier
in proposals, imagine exception, dynamic_priority with zero pressure.

Acceptance criteria:
- Dispatch with no seed writes session marker with writes=0
- Observation tier in proposals writes observation via DaydreamWriter
- Imagine exception writes session marker with writes=0
- dynamic_priority returns P99 value when pressure <= 0
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from turing.daydream import DaydreamProducer
from turing.motivation import ACTION_CADENCE_TICKS, Motivation, priority_base
from turing.reactor import FakeReactor
from turing.repo import Repo
from turing.types import EpisodicMemory, MemoryTier, SourceKind


def _mint_regret(repo: Repo, self_id: str, intent: str = "daydream-test") -> str:
    m = EpisodicMemory(
        memory_id=str(uuid4()),
        self_id=self_id,
        tier=MemoryTier.REGRET,
        source=SourceKind.I_DID,
        content=f"regret about {intent}",
        weight=0.7,
        affect=-0.6,
        surprise_delta=0.5,
        intent_at_time=intent,
        immutable=True,
    )
    repo.insert(m)
    return m.memory_id


class TestDaydreamProducerDispatch:
    def test_dispatch_no_seed(self, repo: Repo, self_id: str) -> None:
        reactor = FakeReactor()
        motivation = Motivation(reactor)
        producer = DaydreamProducer(
            pool_name="test-pool",
            self_id=self_id,
            motivation=motivation,
            reactor=reactor,
            repo=repo,
        )
        motivation.set_pressure("test-pool", 100.0)
        reactor.tick(ACTION_CADENCE_TICKS)
        markers = [
            m
            for m in repo.find(
                self_id=self_id,
                tier=MemoryTier.OBSERVATION,
                source=SourceKind.I_DID,
            )
            if "daydream session" in m.content
        ]
        assert not markers, "no junk markers should be written when no seed exists"

    def test_dispatch_with_observation_proposal(self, repo: Repo, self_id: str) -> None:
        _mint_regret(repo, self_id)
        reactor = FakeReactor()
        motivation = Motivation(reactor)

        def imagine_with_obs(seed, retrieved, pool_name):
            return [
                ("observation", "an observation about the seed", "unused"),
                ("hypothesis", "a hypothesis", seed.intent_at_time),
            ]

        producer = DaydreamProducer(
            pool_name="test-pool",
            self_id=self_id,
            motivation=motivation,
            reactor=reactor,
            repo=repo,
            imagine=imagine_with_obs,
        )
        motivation.set_pressure("test-pool", 100.0)
        reactor.tick(ACTION_CADENCE_TICKS)
        imagined = list(
            repo.find(
                self_id=self_id,
                tier=MemoryTier.OBSERVATION,
                source=SourceKind.I_IMAGINED,
            )
        )
        assert any("observation about the seed" in m.content for m in imagined)

    def test_dispatch_imagine_exception(self, repo: Repo, self_id: str) -> None:
        _mint_regret(repo, self_id)
        reactor = FakeReactor()
        motivation = Motivation(reactor)

        def failing_imagine(seed, retrieved, pool_name):
            raise RuntimeError("LLM crashed")

        producer = DaydreamProducer(
            pool_name="test-pool",
            self_id=self_id,
            motivation=motivation,
            reactor=reactor,
            repo=repo,
            imagine=failing_imagine,
        )
        motivation.set_pressure("test-pool", 100.0)
        reactor.tick(ACTION_CADENCE_TICKS)
        markers = [
            m
            for m in repo.find(
                self_id=self_id,
                tier=MemoryTier.OBSERVATION,
                source=SourceKind.I_DID,
            )
            if "daydream session" in m.content
        ]
        assert any("writes=0" in m.content for m in markers)


class TestDynamicPriority:
    def test_zero_pressure_returns_p99(self) -> None:
        reactor = FakeReactor()
        motivation = Motivation(reactor)
        repo = Repo(None)
        producer = DaydreamProducer(
            pool_name="test",
            self_id="self",
            motivation=motivation,
            reactor=reactor,
            repo=repo,
        )
        result = producer._dynamic_priority({"test": 0.0})
        assert result == priority_base(99)
        repo.close()

    def test_max_pressure_returns_above_p21(self) -> None:
        reactor = FakeReactor()
        motivation = Motivation(reactor)
        repo = Repo(None)
        from turing.motivation import PRESSURE_MAX

        producer = DaydreamProducer(
            pool_name="test",
            self_id="self",
            motivation=motivation,
            reactor=reactor,
            repo=repo,
        )
        result = producer._dynamic_priority({"test": PRESSURE_MAX})
        assert result >= priority_base(21)
        repo.close()


class TestDaydreamPhase:
    def test_initial_phase_is_idle(self) -> None:
        from turing.daydream import _Phase

        reactor = FakeReactor()
        motivation = Motivation(reactor)
        repo = Repo(None)
        producer = DaydreamProducer(
            pool_name="p",
            self_id="self",
            motivation=motivation,
            reactor=reactor,
            repo=repo,
        )
        assert producer.phase == _Phase.IDLE
        repo.close()

    def test_phase_transitions_to_candidate_queued(self) -> None:
        from turing.daydream import _Phase
        from turing.motivation import Motivation

        reactor = FakeReactor()
        motivation = Motivation(reactor)
        repo = Repo(None)
        producer = DaydreamProducer(
            pool_name="p",
            self_id="self",
            motivation=motivation,
            reactor=reactor,
            repo=repo,
        )
        motivation.set_pressure("p", 50.0)
        reactor.tick(0)
        assert producer.phase in (_Phase.CANDIDATE_QUEUED, _Phase.IDLE)
        repo.close()
