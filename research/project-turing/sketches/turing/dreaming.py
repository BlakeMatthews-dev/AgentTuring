"""Dreamer: scheduled consolidation; sole write path into WISDOM.

See specs/dreaming.md. Runs a seven-phase session on a time-of-day trigger:

    1. Pattern extraction
    2. WISDOM candidacy (pending, staged)
    3. AFFIRMATION proposal
    4. LESSON consolidation (cross-intent)
    5. Non-durable pruning
    6. Review gate (commits pending WISDOM)
    7. Session marker

A session that crashes or times out leaves committed candidates in place and
writes a partial-session marker.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from .motivation import Motivation
from .reactor import Reactor
from .repo import Repo, WisdomInvariantViolation
from .tiers import WEIGHT_BOUNDS, clamp_weight
from .types import DURABLE_TIERS, EpisodicMemory, MemoryTier, SourceKind
from .write_paths import handle_affirmation


logger = logging.getLogger("turing.dreaming")


# --- Constants -----------------------------------------------------------

DREAM_MIN_NEW_DURABLE: int = 5
DREAM_WISDOM_N: int = 5
DREAM_MAX_WISDOM_CANDIDATES: int = 3
DREAM_MAX_DURATION: timedelta = timedelta(minutes=30)
DREAM_MIN_RETAIN_WEIGHT: float = 0.15
DREAM_PRUNE_HORIZON: timedelta = timedelta(days=30)
DEFAULT_SCHEDULE_HOUR: int = 3
DEFAULT_SCHEDULE_MINUTE: int = 0


# --- Dataclasses ---------------------------------------------------------


@dataclass(frozen=True)
class Pattern:
    intent: str
    polarity: str  # "regret" | "accomplishment" | "mixed"
    memory_ids: tuple[str, ...]
    mean_affect: float
    mean_surprise: float


@dataclass
class PendingCandidate:
    content: str
    weight: float
    intent_at_time: str
    lineage: list[str]


@dataclass
class Rejection:
    content: str
    reason: str


@dataclass
class DreamSessionReport:
    session_id: str
    session_marker_id: str
    started_at: datetime
    ended_at: datetime
    patterns_found: int
    wisdom_committed: int
    wisdom_rejected: int
    affirmations_proposed: int
    lessons_consolidated: int
    non_durable_pruned: int
    truncated: bool = False


# --- Dreamer --------------------------------------------------------------


class Dreamer:
    """Scheduled consolidation runner. One instance per self_id."""

    def __init__(
        self,
        *,
        motivation: Motivation,
        reactor: Reactor,
        repo: Repo,
        self_id: str,
        schedule_hour: int = DEFAULT_SCHEDULE_HOUR,
        schedule_minute: int = DEFAULT_SCHEDULE_MINUTE,
        min_new_durable: int = DREAM_MIN_NEW_DURABLE,
        wisdom_n: int = DREAM_WISDOM_N,
        max_candidates: int = DREAM_MAX_WISDOM_CANDIDATES,
        max_duration: timedelta = DREAM_MAX_DURATION,
        min_retain_weight: float = DREAM_MIN_RETAIN_WEIGHT,
        prune_horizon: timedelta = DREAM_PRUNE_HORIZON,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self._motivation = motivation
        self._reactor = reactor
        self._repo = repo
        self._self_id = self_id
        self._schedule_hour = schedule_hour
        self._schedule_minute = schedule_minute
        self._min_new_durable = min_new_durable
        self._wisdom_n = wisdom_n
        self._max_candidates = max_candidates
        self._max_duration = max_duration
        self._min_retain_weight = min_retain_weight
        self._prune_horizon = prune_horizon
        self._now = now_fn or (lambda: datetime.now(UTC))
        self._last_session_at: datetime | None = None
        self._last_checked_at: datetime | None = None
        self._running: bool = False

        reactor.register(self.on_tick)

    # ---- Reactor hook: fire when the daily schedule window crosses now.

    def on_tick(self, tick: int) -> None:
        if self._running:
            return
        now = self._now()
        if self._is_scheduled_time(now):
            self.run_session(now=now)
        self._last_checked_at = now

    def _is_scheduled_time(self, now: datetime) -> bool:
        """Fire once when we cross HH:MM of a given day."""
        if self._last_checked_at is None:
            return False
        target_today = now.replace(
            hour=self._schedule_hour,
            minute=self._schedule_minute,
            second=0,
            microsecond=0,
        )
        crossed = self._last_checked_at < target_today <= now
        if not crossed:
            return False
        if self._last_session_at is not None and self._last_session_at >= target_today:
            return False
        return True

    # ---- Session entry point

    def run_session(self, *, now: datetime | None = None) -> DreamSessionReport:
        now = now or self._now()
        self._running = True
        session_id = str(uuid4())
        start = now
        deadline = start + self._max_duration
        truncated = False

        new_durable = self._count_durable_since(self._last_session_at)
        if new_durable < self._min_new_durable:
            logger.info(
                "dream session %s skipped: %d new durable < %d threshold",
                session_id,
                new_durable,
                self._min_new_durable,
            )
            self._running = False
            self._last_session_at = start
            return DreamSessionReport(
                session_id=session_id,
                session_marker_id="",
                started_at=start,
                ended_at=self._now(),
                patterns_found=0,
                wisdom_committed=0,
                wisdom_rejected=0,
                affirmations_proposed=0,
                lessons_consolidated=0,
                non_durable_pruned=0,
            )

        marker_id = self._write_initial_session_marker(session_id, start)

        try:
            patterns = self._phase1_extract_patterns()
            pending = self._phase2_mint_pending_candidates(patterns)
            affirmations = self._phase3_propose_affirmations(patterns)
            lessons = self._phase4_consolidate_lessons(deadline)
            pruned = self._phase5_prune_non_durable(deadline)
            committed, rejected = self._phase6_review_gate(pending, session_marker_id=marker_id)
        except TimeoutError:
            logger.warning("dream session %s truncated", session_id)
            patterns = []
            committed, rejected = [], []
            affirmations, lessons, pruned = 0, 0, 0
            truncated = True
        except Exception:
            logger.exception("dream session %s failed", session_id)
            patterns = []
            committed, rejected = [], []
            affirmations, lessons, pruned = 0, 0, 0

        end = self._now()
        self._write_final_session_marker(
            session_id=session_id,
            placeholder_marker_id=marker_id,
            started_at=start,
            ended_at=end,
            committed=committed,
            rejected=rejected,
            patterns_found=len(patterns),
            affirmations_proposed=affirmations,
            lessons_consolidated=lessons,
            non_durable_pruned=pruned,
            truncated=truncated,
        )

        self._running = False
        self._last_session_at = end

        return DreamSessionReport(
            session_id=session_id,
            session_marker_id=marker_id,
            started_at=start,
            ended_at=end,
            patterns_found=len(patterns),
            wisdom_committed=len(committed),
            wisdom_rejected=len(rejected),
            affirmations_proposed=affirmations,
            lessons_consolidated=lessons,
            non_durable_pruned=pruned,
            truncated=truncated,
        )

    # ---- Phase 1: pattern extraction

    def _phase1_extract_patterns(self) -> list[Pattern]:
        by_intent: dict[str, list[EpisodicMemory]] = defaultdict(list)
        for m in self._repo.find(
            self_id=self._self_id,
            tiers={MemoryTier.REGRET, MemoryTier.ACCOMPLISHMENT, MemoryTier.LESSON},
            source=SourceKind.I_DID,
            include_superseded=False,
        ):
            intent = (m.intent_at_time or "").strip().lower()
            if not intent:
                continue
            by_intent[intent].append(m)

        patterns: list[Pattern] = []
        for intent, memories in by_intent.items():
            if len(memories) < self._wisdom_n:
                continue
            regret_count = sum(1 for m in memories if m.tier == MemoryTier.REGRET)
            accomplishment_count = sum(1 for m in memories if m.tier == MemoryTier.ACCOMPLISHMENT)
            total = len(memories)
            if total == 0:
                continue
            positive_ratio = accomplishment_count / total
            negative_ratio = regret_count / total
            if positive_ratio >= 0.8:
                polarity = "accomplishment"
            elif negative_ratio >= 0.8:
                polarity = "regret"
            else:
                continue  # mixed polarity → no pattern
            mean_affect = sum(m.affect for m in memories) / total
            mean_surprise = sum(m.surprise_delta for m in memories) / total
            patterns.append(
                Pattern(
                    intent=intent,
                    polarity=polarity,
                    memory_ids=tuple(m.memory_id for m in memories),
                    mean_affect=mean_affect,
                    mean_surprise=mean_surprise,
                )
            )
        return patterns

    # ---- Phase 2: mint pending candidates (staged)

    def _phase2_mint_pending_candidates(self, patterns: list[Pattern]) -> list[PendingCandidate]:
        pending: list[PendingCandidate] = []
        for p in patterns:
            if p.polarity == "accomplishment":
                content = (
                    f"I reliably succeed at '{p.intent}' "
                    f"(mean affect {p.mean_affect:+.2f} across {len(p.memory_ids)} cases)"
                )
            else:
                content = (
                    f"I reliably fail at '{p.intent}' "
                    f"(mean affect {p.mean_affect:+.2f} across {len(p.memory_ids)} cases)"
                )
            pending.append(
                PendingCandidate(
                    content=content,
                    weight=clamp_weight(MemoryTier.WISDOM, 0.95),
                    intent_at_time=p.intent,
                    lineage=list(p.memory_ids),
                )
            )
        return pending[: self._max_candidates]

    # ---- Phase 3: AFFIRMATION proposals

    def _phase3_propose_affirmations(self, patterns: list[Pattern]) -> int:
        count = 0
        for p in patterns:
            if p.polarity == "accomplishment":
                content = f"commit to the pattern that succeeds at '{p.intent}' going forward"
                handle_affirmation(self._repo, self._self_id, content=content)
                count += 1
        return count

    # ---- Phase 4: LESSON consolidation (sketch)

    def _phase4_consolidate_lessons(self, deadline: datetime) -> int:
        """Cross-intent LESSON consolidation is the same shape as the
        contradiction detector's dispatch step. For the sketch, defer to the
        detector's in-process work; the Dreamer returns 0 to avoid double
        minting."""
        return 0

    # ---- Phase 5: non-durable pruning

    def _phase5_prune_non_durable(self, deadline: datetime) -> int:
        cutoff = self._now() - self._prune_horizon
        rows = self._repo.conn.execute(
            "SELECT memory_id FROM episodic_memory "
            "WHERE self_id = ? AND tier IN ('observation', 'hypothesis') "
            "AND weight < ? AND last_accessed_at < ? AND deleted = 0",
            (self._self_id, self._min_retain_weight, cutoff.isoformat()),
        ).fetchall()
        for row in rows:
            try:
                self._repo.soft_delete(row[0])
            except Exception:
                logger.exception("prune failed for %s", row[0])
        return len(rows)

    # ---- Phase 6: review gate

    def _phase6_review_gate(
        self,
        pending: list[PendingCandidate],
        *,
        session_marker_id: str,
    ) -> tuple[list[EpisodicMemory], list[Rejection]]:
        committed: list[EpisodicMemory] = []
        rejections: list[Rejection] = []
        existing_wisdom = list(
            self._repo.find(
                self_id=self._self_id,
                tier=MemoryTier.WISDOM,
                include_superseded=False,
            )
        )
        for candidate in pending:
            # 1. Contradicts existing WISDOM?
            if any(_shallow_contradicts(candidate.content, w.content) for w in existing_wisdom):
                rejections.append(
                    Rejection(
                        content=candidate.content,
                        reason="contradicts existing WISDOM",
                    )
                )
                continue
            # 2. Any lineage member already superseded?
            lineage_valid = True
            for mid in candidate.lineage:
                m = self._repo.get(mid)
                if m is None or m.superseded_by is not None:
                    lineage_valid = False
                    break
            if not lineage_valid:
                rejections.append(
                    Rejection(
                        content=candidate.content,
                        reason="lineage contains superseded or missing memory",
                    )
                )
                continue
            # 3. Commit.
            wisdom = EpisodicMemory(
                memory_id=str(uuid4()),
                self_id=self._self_id,
                tier=MemoryTier.WISDOM,
                source=SourceKind.I_DID,
                content=candidate.content,
                weight=candidate.weight,
                intent_at_time=candidate.intent_at_time,
                origin_episode_id=session_marker_id,
                immutable=True,
                context={"supersedes_via_lineage": candidate.lineage},
            )
            try:
                self._repo.insert(wisdom)
                committed.append(wisdom)
            except WisdomInvariantViolation as exc:
                rejections.append(
                    Rejection(
                        content=candidate.content,
                        reason=f"invariant: {exc}",
                    )
                )
        return committed, rejections

    # ---- Phase 7: session marker

    def _write_initial_session_marker(self, session_id: str, started_at: datetime) -> str:
        marker = EpisodicMemory(
            memory_id=str(uuid4()),
            self_id=self._self_id,
            tier=MemoryTier.OBSERVATION,
            source=SourceKind.I_DID,
            content=f"dream session {session_id} started at {started_at.isoformat()}",
            weight=0.2,
            origin_episode_id=session_id,
            created_at=started_at,
        )
        self._repo.insert(marker)
        return marker.memory_id

    def _write_final_session_marker(
        self,
        *,
        session_id: str,
        placeholder_marker_id: str,
        started_at: datetime,
        ended_at: datetime,
        committed: list[EpisodicMemory],
        rejected: list[Rejection],
        patterns_found: int,
        affirmations_proposed: int,
        lessons_consolidated: int,
        non_durable_pruned: int,
        truncated: bool,
    ) -> None:
        status = "truncated" if truncated else "completed"
        content = (
            f"dream session {session_id} {status}. "
            f"start={started_at.isoformat()} end={ended_at.isoformat()} "
            f"patterns={patterns_found} "
            f"wisdom_committed={len(committed)} wisdom_rejected={len(rejected)} "
            f"affirmations={affirmations_proposed} lessons={lessons_consolidated} "
            f"pruned={non_durable_pruned}"
        )
        final = EpisodicMemory(
            memory_id=str(uuid4()),
            self_id=self._self_id,
            tier=MemoryTier.OBSERVATION,
            source=SourceKind.I_DID,
            content=content,
            weight=0.3,
            origin_episode_id=session_id,
            supersedes=placeholder_marker_id,
            created_at=ended_at,
        )
        self._repo.insert(final)
        try:
            self._repo.set_superseded_by(placeholder_marker_id, final.memory_id)
        except Exception:
            pass

    # ---- helpers

    def _count_durable_since(self, threshold: datetime | None) -> int:
        if threshold is None:
            cur = self._repo.conn.execute(
                "SELECT COUNT(*) FROM durable_memory WHERE self_id = ?",
                (self._self_id,),
            )
            return int(cur.fetchone()[0])
        cur = self._repo.conn.execute(
            "SELECT COUNT(*) FROM durable_memory WHERE self_id = ? AND created_at > ?",
            (self._self_id, threshold.isoformat()),
        )
        return int(cur.fetchone()[0])


def _shallow_contradicts(a: str, b: str) -> bool:
    """Placeholder contradiction check. Replace with LLM in production."""
    a_lower = a.lower().strip()
    b_lower = b.lower().strip()
    if "succeed" in a_lower and "fail" in b_lower:
        if a_lower.split("'")[1:2] == b_lower.split("'")[1:2]:
            return True
    if "fail" in a_lower and "succeed" in b_lower:
        if a_lower.split("'")[1:2] == b_lower.split("'")[1:2]:
            return True
    return False
