"""Self-model write → episodic memory mirror bridge. See specs/memory-mirroring.md.

Every self-model write-site that specs call for mirroring invokes one of these
helpers in the same transaction. The bridge creates an EpisodicMemory row and
returns its memory_id. It never mutates existing memories.
"""

from __future__ import annotations

import contextvars
from datetime import UTC, datetime
from uuid import uuid4

from .repo import Repo
from .tiers import WEIGHT_BOUNDS, clamp_weight
from .types import EpisodicMemory, MemoryTier, SourceKind


MIRROR_CONTENT_MAX = 1000
INTENT_AT_TIME_MAX = 120


class MirrorContentTooLong(ValueError):
    pass


class MirrorIntentTooLong(ValueError):
    pass


_request_hash_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_mirror_request_hash", default=None
)
_perception_tool_call_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_mirror_perception_tool_call_id", default=None
)


def set_mirror_request_hash(h: str | None) -> None:
    _request_hash_var.set(h)


def set_mirror_perception_tool_call_id(tc_id: str | None) -> None:
    _perception_tool_call_id_var.set(tc_id)


def _validate_lengths(content: str, intent_at_time: str) -> None:
    if len(content) > MIRROR_CONTENT_MAX:
        raise MirrorContentTooLong(
            f"content length {len(content)} exceeds MIRROR_CONTENT_MAX={MIRROR_CONTENT_MAX}"
        )
    if len(intent_at_time) > INTENT_AT_TIME_MAX:
        raise MirrorIntentTooLong(
            f"intent_at_time length {len(intent_at_time)} exceeds INTENT_AT_TIME_MAX={INTENT_AT_TIME_MAX}"
        )


def _new_id() -> str:
    return str(uuid4())


def _augment_context(self_id: str, ctx: dict | None) -> dict:
    out = dict(ctx or {})
    out.setdefault("self_id", self_id)
    out["mirror"] = True
    rh = _request_hash_var.get()
    if rh is not None:
        out["request_hash"] = rh
    ptc = _perception_tool_call_id_var.get()
    if ptc is not None:
        out["perception_tool_call_id"] = ptc
    if "request_hash" not in out and "provenance" not in out:
        out["provenance"] = "out_of_band"
    return out


def mirror_observation(
    repo: Repo,
    self_id: str,
    content: str,
    intent_at_time: str,
    context: dict | None = None,
) -> str:
    _validate_lengths(content, intent_at_time)
    ctx = _augment_context(self_id, context)
    low, _ = WEIGHT_BOUNDS[MemoryTier.OBSERVATION]
    m = EpisodicMemory(
        memory_id=_new_id(),
        self_id=self_id,
        tier=MemoryTier.OBSERVATION,
        source=SourceKind.I_DID,
        content=content,
        weight=clamp_weight(MemoryTier.OBSERVATION, low),
        intent_at_time=intent_at_time,
        created_at=datetime.now(UTC),
        context=ctx,
    )
    repo.insert(m)
    return m.memory_id


def mirror_opinion(
    repo: Repo,
    self_id: str,
    content: str,
    intent_at_time: str,
    context: dict | None = None,
) -> str:
    _validate_lengths(content, intent_at_time)
    ctx = _augment_context(self_id, context)
    low, _ = WEIGHT_BOUNDS[MemoryTier.OPINION]
    m = EpisodicMemory(
        memory_id=_new_id(),
        self_id=self_id,
        tier=MemoryTier.OPINION,
        source=SourceKind.I_DID,
        content=content,
        weight=clamp_weight(MemoryTier.OPINION, low),
        intent_at_time=intent_at_time,
        created_at=datetime.now(UTC),
        context=ctx,
    )
    repo.insert(m)
    return m.memory_id


def mirror_affirmation(
    repo: Repo,
    self_id: str,
    content: str,
    intent_at_time: str,
    context: dict | None = None,
) -> str:
    _validate_lengths(content, intent_at_time)
    ctx = _augment_context(self_id, context)
    low, _ = WEIGHT_BOUNDS[MemoryTier.AFFIRMATION]
    m = EpisodicMemory(
        memory_id=_new_id(),
        self_id=self_id,
        tier=MemoryTier.AFFIRMATION,
        source=SourceKind.I_DID,
        content=content,
        weight=clamp_weight(MemoryTier.AFFIRMATION, low),
        intent_at_time=intent_at_time,
        created_at=datetime.now(UTC),
        context=ctx,
    )
    repo.insert(m)
    return m.memory_id


def mirror_lesson(
    repo: Repo,
    self_id: str,
    content: str,
    intent_at_time: str,
    context: dict | None = None,
) -> str:
    _validate_lengths(content, intent_at_time)
    ctx = _augment_context(self_id, context)
    low, _ = WEIGHT_BOUNDS[MemoryTier.LESSON]
    m = EpisodicMemory(
        memory_id=_new_id(),
        self_id=self_id,
        tier=MemoryTier.LESSON,
        source=SourceKind.I_DID,
        content=content,
        weight=clamp_weight(MemoryTier.LESSON, low),
        intent_at_time=intent_at_time,
        created_at=datetime.now(UTC),
        context=ctx,
    )
    repo.insert(m)
    return m.memory_id


def mirror_regret(
    repo: Repo,
    self_id: str,
    content: str,
    intent_at_time: str,
    context: dict | None = None,
) -> str:
    _validate_lengths(content, intent_at_time)
    ctx = _augment_context(self_id, context)
    low, _ = WEIGHT_BOUNDS[MemoryTier.REGRET]
    m = EpisodicMemory(
        memory_id=_new_id(),
        self_id=self_id,
        tier=MemoryTier.REGRET,
        source=SourceKind.I_DID,
        content=content,
        weight=clamp_weight(MemoryTier.REGRET, low),
        intent_at_time=intent_at_time,
        created_at=datetime.now(UTC),
        context=ctx,
    )
    repo.insert(m)
    return m.memory_id
