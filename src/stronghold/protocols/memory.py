"""Memory protocols: learnings, episodic, extraction, outcomes, sessions, audit."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from stronghold.types.memory import (
        EpisodicMemory,
        Learning,
        Outcome,
        SessionCheckpoint,
        SkillMutation,
    )
    from stronghold.types.security import AuditEntry


@runtime_checkable
class LearningStore(Protocol):
    """Self-improving memory from tool call patterns."""

    async def store(self, learning: Learning) -> int:
        """Store a learning, dedup against existing. Returns learning ID."""
        ...

    async def find_relevant(
        self,
        user_text: str,
        *,
        agent_id: str | None = None,
        org_id: str = "",
        max_results: int = 10,
    ) -> list[Learning]:
        """Find learnings relevant to the user's message."""
        ...

    async def mark_used(self, learning_ids: list[int]) -> None:
        """Increment hit_count for used learnings."""
        ...

    async def check_auto_promotions(
        self, threshold: int = 5, *, org_id: str = ""
    ) -> list[Learning]:
        """Promote learnings that have been hit enough times."""
        ...

    async def get_promoted(
        self, task_type: str | None = None, *, org_id: str = ""
    ) -> list[Learning]:
        """Get promoted learnings for system prompt injection."""
        ...


@runtime_checkable
class LearningExtractor(Protocol):
    """Extracts learnings from tool call histories. Pure function, no I/O."""

    def extract_corrections(
        self,
        user_text: str,
        tool_history: list[dict[str, Any]],
    ) -> list[Learning]:
        """Extract fail→succeed correction patterns."""
        ...

    def extract_positive_patterns(
        self,
        user_text: str,
        tool_history: list[dict[str, Any]],
    ) -> list[Learning]:
        """Extract first-try success patterns on ambiguous queries."""
        ...


@runtime_checkable
class EpisodicStore(Protocol):
    """7-tier episodic memory with weight-bounded tiers."""

    async def store(self, memory: EpisodicMemory) -> str:
        """Store a memory. Returns memory_id."""
        ...

    async def retrieve(
        self,
        query: str,
        *,
        agent_id: str | None = None,
        user_id: str | None = None,
        team: str | None = None,
        task_type: str = "",
        limit: int = 5,
    ) -> list[EpisodicMemory]:
        """Retrieve relevant memories, scope-filtered."""
        ...

    async def reinforce(self, memory_id: str, delta: float = 0.05) -> None:
        """Reinforce a memory (increase weight, clamped to tier ceiling)."""
        ...


@runtime_checkable
class OutcomeStore(Protocol):
    """Tracks request outcomes for task completion rate and experience-augmented prompts."""

    async def record(self, outcome: Outcome) -> int:
        """Record an outcome. Returns outcome ID."""
        ...

    async def get_task_completion_rate(
        self,
        task_type: str = "",
        days: int = 7,
    ) -> dict[str, Any]:
        """Get completion rate stats: {total, succeeded, failed, rate, by_model}."""
        ...

    async def get_experience_context(
        self,
        task_type: str,
        tool_name: str = "",
        limit: int = 5,
    ) -> str:
        """Get recent failure patterns as a prompt section for experience-augmented context."""
        ...

    async def get_usage_breakdown(
        self,
        group_by: str = "user_id",
        days: int = 7,
        org_id: str = "",
    ) -> list[dict[str, Any]]:
        """Aggregate token usage grouped by a dimension (user_id, team_id, org_id, model_used)."""
        ...

    async def get_daily_timeseries(
        self,
        group_by: str = "",
        days: int = 7,
        org_id: str = "",
    ) -> list[dict[str, Any]]:
        """Daily token usage timeseries, optionally grouped by a dimension."""
        ...

    async def list_outcomes(
        self,
        task_type: str = "",
        days: int = 7,
        limit: int = 50,
    ) -> list[Outcome]:
        """List recent outcomes for admin inspection."""
        ...


@runtime_checkable
class SkillMutationStore(Protocol):
    """Tracks skill mutations triggered by promoted learnings."""

    async def record(self, mutation: SkillMutation) -> int:
        """Record a skill mutation. Returns mutation ID."""
        ...

    async def list_mutations(self, limit: int = 50) -> list[SkillMutation]:
        """List recent mutations."""
        ...


@runtime_checkable
class RCAExtractor(Protocol):
    """Generates root cause analysis when tool loops exhaust max rounds."""

    async def extract_rca(
        self,
        user_text: str,
        tool_history: list[dict[str, Any]],
    ) -> Learning | None:
        """Diagnose why the tool loop failed. Returns a learning or None."""
        ...


@runtime_checkable
class SessionStore(Protocol):
    """Conversation history storage. Org-scoped via session ID format."""

    async def get_history(
        self,
        session_id: str,
        max_messages: int | None = None,
        ttl_seconds: int | None = None,
    ) -> list[dict[str, str]]:
        """Retrieve conversation history, pruning expired messages."""
        ...

    async def append_messages(
        self,
        session_id: str,
        messages: list[dict[str, str]],
    ) -> None:
        """Append messages to session history."""
        ...

    async def delete_session(self, session_id: str) -> None:
        """Delete a session."""
        ...


@runtime_checkable
class AuditLog(Protocol):
    """Immutable audit log for boundary crossings."""

    async def log(self, entry: AuditEntry) -> None:
        """Record an audit entry."""
        ...

    async def get_entries(
        self,
        *,
        user_id: str | None = None,
        agent_id: str | None = None,
        org_id: str = "",
        limit: int = 100,
    ) -> list[AuditEntry]:
        """Retrieve audit entries with optional filtering (org-scoped)."""
        ...


@runtime_checkable
class CheckpointStore(Protocol):
    """Typed-snapshot store for SessionCheckpoint (S1.3).

    Distinct from the conversation-history `SessionStore` above — this stores
    structured snapshots of working state (summary, decisions, remaining work)
    that enable cross-session handoff. Schema-compatible with the client-side
    `/checkpoint-save` skill.

    Tenant isolation: all operations are org-scoped. A checkpoint saved under
    org A cannot be loaded with org_id=B — the store returns None, never raises,
    to avoid leaking existence via error messages.
    """

    async def save(self, checkpoint: SessionCheckpoint) -> str:
        """Persist a checkpoint and return its id.

        Implementations may use the provided checkpoint_id or generate a new one
        when the input is empty. The returned id is the canonical handle.
        """
        ...

    async def load(
        self,
        checkpoint_id: str,
        *,
        org_id: str,
    ) -> SessionCheckpoint | None:
        """Load a checkpoint. Returns None for unknown id or cross-org access."""
        ...

    async def list_recent(
        self,
        *,
        org_id: str,
        user_id: str | None = None,
        agent_id: str | None = None,
        team_id: str | None = None,
        limit: int = 20,
    ) -> list[SessionCheckpoint]:
        """List checkpoints (org-scoped, ordered by created_at desc, limit applied)."""
        ...
