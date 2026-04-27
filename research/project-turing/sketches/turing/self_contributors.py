"""Self-contributor tool handlers for the tool registry.

write_contributor, record_personality_claim, retract_contributor_by_counter,
note_engagement, note_interest_trigger.

See specs/self-tool-registry.md (Spec 31, AC-31.10 - 31.13).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from .self_model import (
    ActivationContributor,
    ContributorOrigin,
    FACET_TO_TRAIT,
    NodeKind,
)
from .self_personality import narrative_weight
from .self_repo import SelfRepo
from .types import EpisodicMemory, MemoryTier, SourceKind


class NoMatchingContributor(Exception):
    pass


def write_contributor(
    self_id: str,
    target_node_id: str,
    target_kind: str,
    source_id: str,
    source_kind: str,
    weight: float,
    rationale: str,
    *,
    origin: str = "self",
    repo: SelfRepo | None = None,
) -> ActivationContributor:
    if origin.upper() == "RETRIEVAL":
        raise ValueError("RETRIEVAL origin not allowed via write_contributor")
    if target_node_id == source_id:
        raise ValueError("contributor cannot self-loop: target == source")
    origin_enum = ContributorOrigin(origin.lower())
    contrib = ActivationContributor(
        node_id=f"contrib:{uuid.uuid4()}",
        self_id=self_id,
        target_node_id=target_node_id,
        target_kind=NodeKind(target_kind),
        source_id=source_id,
        source_kind=source_kind,
        weight=weight,
        origin=origin_enum,
        rationale=rationale,
    )
    if repo is not None:
        repo.insert_contributor(contrib)
    return contrib


def record_personality_claim(
    self_id: str,
    facet_id: str,
    claim_text: str,
    evidence: str,
) -> EpisodicMemory:
    if facet_id not in FACET_TO_TRAIT:
        raise ValueError(f"unknown facet_id: {facet_id}")
    now = datetime.now(UTC)
    return EpisodicMemory(
        memory_id=f"claim:{uuid.uuid4()}",
        self_id=self_id,
        tier=MemoryTier.OPINION,
        source=SourceKind.I_DID,
        content=f"I notice: {claim_text}",
        weight=narrative_weight(evidence, claim_text),
        intent_at_time="narrative personality revision",
        context={"facet_id": facet_id, "evidence": evidence},
        created_at=now,
        last_accessed_at=now,
    )


def retract_contributor_by_counter(
    self_id: str,
    target_node_id: str,
    source_id: str,
    weight: float,
    rationale: str,
    *,
    repo: SelfRepo | None = None,
) -> ActivationContributor:
    if repo is not None:
        matching = [
            c
            for c in repo.active_contributors_for(target_node_id, at=datetime.now(UTC))
            if c.source_id == source_id
        ]
        if not matching:
            raise NoMatchingContributor(
                f"no active contributor for target={target_node_id} source={source_id}"
            )
    return ActivationContributor(
        node_id=f"contrib:{uuid.uuid4()}",
        self_id=self_id,
        target_node_id=target_node_id,
        target_kind=NodeKind.PERSONALITY_FACET,
        source_id=source_id,
        source_kind="memory",
        weight=-weight,
        origin=ContributorOrigin.SELF,
        rationale=f"counter:{rationale}",
    )


def note_engagement(self_id: str, **kwargs: Any) -> dict[str, Any]:
    return {"status": "noted", "kind": "engagement", "self_id": self_id}


def note_interest_trigger(self_id: str, **kwargs: Any) -> dict[str, Any]:
    return {"status": "noted", "kind": "interest_trigger", "self_id": self_id}
