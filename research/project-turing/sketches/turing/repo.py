"""Repository for durable and non-durable memory. Enforces the INV-1..8 invariants.

Thin layer over sqlite3. Serializes/deserializes `EpisodicMemory` dataclass.
See specs/durability-invariants.md and specs/persistence.md.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterable, Iterator
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .protocols import (
    ImmutableViolation,
    ProvenanceViolation,
    RepoError,
    WisdomDeferred,
    WisdomInvariantViolation,
)
from .tiers import WEIGHT_BOUNDS, clamp_weight
from .types import DURABLE_TIERS, EpisodicMemory, MemoryTier, SourceKind


_VALID_TABLES: frozenset[str] = frozenset({"durable_memory", "episodic_memory"})


class Repo:
    """SQLite-backed storage for the memory layer.

    Does not manage transactions around groups of operations; callers
    compose atomic actions (like minting REGRET + setting superseded_by
    on the predecessor) at the write-paths layer.
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._path = ":memory:" if db_path is None else str(db_path)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._apply_schema()

    # ------------------------------------------------------------------ setup

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn

    def close(self) -> None:
        self._conn.close()

    def _apply_schema(self) -> None:
        schema_path = Path(__file__).with_name("schema.sql")
        with self._lock:
            self._conn.executescript(schema_path.read_text())
            self._conn.commit()

    @staticmethod
    def _validate_table(table: str) -> None:
        if table not in _VALID_TABLES:
            raise RepoError(f"invalid table name: {table!r}")

    # ------------------------------------------------------------------ insert

    def insert(self, memory: EpisodicMemory) -> str:
        """Insert a new memory. Enforces INV-1, INV-3, INV-4 at the Python layer.

        The SQLite schema itself enforces: tier/source CHECK, WISDOM deferral,
        ACCOMPLISHMENT requires intent, and the DELETE-block trigger.
        """
        if not self._weight_in_bounds(memory):
            lo, hi = WEIGHT_BOUNDS[memory.tier]
            raise RepoError(
                f"weight {memory.weight} outside tier bounds [{lo}, {hi}] for {memory.tier.value}"
            )
        if memory.tier == MemoryTier.WISDOM:
            self._validate_wisdom_invariants(memory)
        table = "durable_memory" if memory.tier in DURABLE_TIERS else "episodic_memory"
        self._validate_table(table)
        with self._lock:
            try:
                self._conn.execute(
                    f"""
                    INSERT INTO {table} (
                        memory_id, self_id, tier, source, content, weight,
                        affect, confidence_at_creation, surprise_delta, intent_at_time,
                        supersedes, superseded_by, origin_episode_id, immutable,
                        reinforcement_count, contradiction_count,
                        {"deleted," if table == "episodic_memory" else ""}
                        created_at, last_accessed_at, context
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?,
                        ?, ?, ?, ?,
                        ?, ?,
                        {"?," if table == "episodic_memory" else ""}
                        ?, ?, ?
                    )
                    """,
                    self._row_for_insert(memory, table == "episodic_memory"),
                )
                self._conn.commit()
            except sqlite3.IntegrityError as e:
                raise RepoError(str(e)) from e
        return memory.memory_id

    def _weight_in_bounds(self, memory: EpisodicMemory) -> bool:
        lo, hi = WEIGHT_BOUNDS[memory.tier]
        return lo <= memory.weight <= hi

    def _validate_wisdom_invariants(self, memory: EpisodicMemory) -> None:
        """Enforce the invariants from specs/wisdom-write-path.md."""
        if not memory.origin_episode_id:
            raise WisdomInvariantViolation(
                "WISDOM requires origin_episode_id pointing at a dream session marker"
            )
        lineage = memory.context.get("supersedes_via_lineage") if memory.context else None
        if not isinstance(lineage, list) or not lineage:
            raise WisdomInvariantViolation(
                "WISDOM requires context['supersedes_via_lineage'] as a non-empty list"
            )
        with self._lock:
            for mid in lineage:
                if self.get(str(mid)) is None:
                    raise WisdomInvariantViolation(
                        f"WISDOM lineage references unknown memory_id: {mid}"
                    )
            if memory.supersedes is not None:
                prior = self.get(memory.supersedes)
                if prior is not None and prior.tier == MemoryTier.WISDOM:
                    raise WisdomInvariantViolation(
                        "WISDOM may not supersede existing WISDOM; extend instead"
                    )
            marker_row = self._conn.execute(
                "SELECT tier, source, content FROM episodic_memory "
                "WHERE memory_id = ? OR origin_episode_id = ? "
                "LIMIT 1",
                (memory.origin_episode_id, memory.origin_episode_id),
            ).fetchone()
        if marker_row is None:
            raise WisdomInvariantViolation(
                f"WISDOM origin_episode_id {memory.origin_episode_id} does not resolve to any marker"
            )

    def _row_for_insert(self, m: EpisodicMemory, include_deleted: bool) -> tuple[Any, ...]:
        base = [
            m.memory_id,
            m.self_id,
            m.tier.value,
            m.source.value,
            m.content,
            m.weight,
            m.affect,
            m.confidence_at_creation,
            m.surprise_delta,
            m.intent_at_time,
            m.supersedes,
            m.superseded_by,
            m.origin_episode_id,
            1 if m.immutable else 0,
            m.reinforcement_count,
            m.contradiction_count,
        ]
        if include_deleted:
            base.append(1 if m.deleted else 0)
        base.extend(
            [
                m.created_at.isoformat(),
                m.last_accessed_at.isoformat(),
                json.dumps(m.context) if m.context else None,
            ]
        )
        return tuple(base)

    # ------------------------------------------------------------------ read

    def get(self, memory_id: str) -> EpisodicMemory | None:
        row = self._fetch_by_id(memory_id, "durable_memory")
        if row is not None:
            return self._row_to_memory(row, include_deleted=False)
        row = self._fetch_by_id(memory_id, "episodic_memory")
        if row is not None:
            return self._row_to_memory(row, include_deleted=True)
        return None

    def get_head(self, memory_id: str) -> EpisodicMemory | None:
        """Walk forward through `superseded_by` to the current head."""
        current = self.get(memory_id)
        while current is not None and current.superseded_by is not None:
            nxt = self.get(current.superseded_by)
            if nxt is None:
                break
            current = nxt
        return current

    def walk_lineage(self, memory_id: str) -> list[EpisodicMemory]:
        """Walk backward through `supersedes` returning the chain oldest-first."""
        chain: list[EpisodicMemory] = []
        current = self.get(memory_id)
        while current is not None:
            chain.append(current)
            if current.supersedes is None:
                break
            current = self.get(current.supersedes)
        chain.reverse()
        return chain

    def _fetch_by_id(self, memory_id: str, table: str) -> sqlite3.Row | None:
        self._validate_table(table)
        with self._lock:
            cur = self._conn.execute(f"SELECT * FROM {table} WHERE memory_id = ?", (memory_id,))
            cur.row_factory = sqlite3.Row  # type: ignore[assignment]
            result: sqlite3.Row | None = cur.fetchone()
            return result

    def _row_to_memory(self, row: sqlite3.Row, *, include_deleted: bool) -> EpisodicMemory:
        return EpisodicMemory(
            memory_id=row["memory_id"],
            self_id=row["self_id"],
            tier=MemoryTier(row["tier"]),
            source=SourceKind(row["source"]),
            content=row["content"],
            weight=row["weight"],
            affect=row["affect"],
            confidence_at_creation=row["confidence_at_creation"],
            surprise_delta=row["surprise_delta"],
            intent_at_time=row["intent_at_time"],
            supersedes=row["supersedes"],
            superseded_by=row["superseded_by"],
            origin_episode_id=row["origin_episode_id"],
            immutable=bool(row["immutable"]),
            reinforcement_count=row["reinforcement_count"],
            contradiction_count=row["contradiction_count"],
            deleted=bool(row["deleted"]) if include_deleted else False,
            created_at=datetime.fromisoformat(row["created_at"]),
            last_accessed_at=datetime.fromisoformat(row["last_accessed_at"]),
            context=json.loads(row["context"]) if row["context"] else {},
        )

    # ------------------------------------------------------------------ update

    def set_superseded_by(self, memory_id: str, successor_id: str) -> None:
        """Set `superseded_by` on a durable or non-durable memory.

        INV-6 permits this in-place update; it is one of the few permitted.
        """
        with self._lock:
            for table in ("durable_memory", "episodic_memory"):
                cur = self._conn.execute(
                    f"SELECT superseded_by FROM {table} WHERE memory_id = ?",
                    (memory_id,),
                )
                row = cur.fetchone()
                if row is None:
                    continue
                if row[0] is not None:
                    raise ImmutableViolation(f"superseded_by already set on {memory_id}")
                self._conn.execute(
                    f"UPDATE {table} SET superseded_by = ? WHERE memory_id = ?",
                    (successor_id, memory_id),
                )
                self._conn.commit()
                return
        raise RepoError(f"no memory with id {memory_id}")

    def increment_contradiction_count(self, memory_id: str) -> None:
        with self._lock:
            for table in ("durable_memory", "episodic_memory"):
                cur = self._conn.execute(
                    f"SELECT memory_id FROM {table} WHERE memory_id = ?", (memory_id,)
                )
                if cur.fetchone() is not None:
                    self._conn.execute(
                        f"UPDATE {table} SET contradiction_count = contradiction_count + 1 "
                        f"WHERE memory_id = ?",
                        (memory_id,),
                    )
                    self._conn.commit()
                    return
        raise RepoError(f"no memory with id {memory_id}")

    def touch_access(self, memory_id: str) -> None:
        now_iso = datetime.now(UTC).isoformat()
        with self._lock:
            for table in ("durable_memory", "episodic_memory"):
                self._conn.execute(
                    f"UPDATE {table} SET last_accessed_at = ? WHERE memory_id = ?",
                    (now_iso, memory_id),
                )
            self._conn.commit()

    def decay_weight(self, memory_id: str, delta: float) -> float:
        """Decay a non-durable memory's weight, clamped to tier floor.

        Durable memories can also decay *within* their tier bounds (INV-1);
        the floor is enforced via clamp.
        """
        m = self.get(memory_id)
        if m is None:
            raise RepoError(f"no memory with id {memory_id}")
        new_weight = clamp_weight(m.tier, m.weight - delta)
        table = "durable_memory" if m.tier in DURABLE_TIERS else "episodic_memory"
        self._validate_table(table)
        with self._lock:
            self._conn.execute(
                f"UPDATE {table} SET weight = ? WHERE memory_id = ?",
                (new_weight, memory_id),
            )
            self._conn.commit()
        return new_weight

    # ------------------------------------------------------------------ delete

    def soft_delete(self, memory_id: str) -> None:
        """Soft-delete a non-durable memory. Durable memories cannot be deleted.

        Enforces INV-2 in Python (the schema trigger backs this up for durable).
        """
        m = self.get(memory_id)
        if m is None:
            raise RepoError(f"no memory with id {memory_id}")
        if m.immutable or m.tier in DURABLE_TIERS:
            raise ImmutableViolation(f"cannot delete immutable/durable memory {memory_id}")
        with self._lock:
            self._conn.execute(
                "UPDATE episodic_memory SET deleted = 1 WHERE memory_id = ?",
                (memory_id,),
            )
            self._conn.commit()

    # ------------------------------------------------------------------ queries

    def find(
        self,
        *,
        self_id: str | None = None,
        tier: MemoryTier | None = None,
        tiers: Iterable[MemoryTier] | None = None,
        source: SourceKind | None = None,
        sources: Iterable[SourceKind] | None = None,
        intent_at_time: str | None = None,
        created_after: datetime | None = None,
        include_deleted: bool = False,
        include_superseded: bool = True,
    ) -> Iterator[EpisodicMemory]:
        all_tiers = {tier} if tier is not None else set(tiers) if tiers else set(MemoryTier)
        durable = all_tiers & DURABLE_TIERS
        nondurable = all_tiers - DURABLE_TIERS

        if durable:
            yield from self._find_in_table(
                "durable_memory",
                self_id=self_id,
                tiers=durable,
                source=source,
                sources=sources,
                intent_at_time=intent_at_time,
                created_after=created_after,
                include_deleted=False,
                include_superseded=include_superseded,
            )
        if nondurable:
            yield from self._find_in_table(
                "episodic_memory",
                self_id=self_id,
                tiers=nondurable,
                source=source,
                sources=sources,
                intent_at_time=intent_at_time,
                created_after=created_after,
                include_deleted=include_deleted,
                include_superseded=include_superseded,
            )

    def _find_in_table(
        self,
        table: str,
        *,
        self_id: str | None,
        tiers: set[MemoryTier],
        source: SourceKind | None,
        sources: Iterable[SourceKind] | None,
        intent_at_time: str | None,
        created_after: datetime | None,
        include_deleted: bool,
        include_superseded: bool,
    ) -> Iterator[EpisodicMemory]:
        self._validate_table(table)
        where: list[str] = []
        params: list[object] = []
        if self_id is not None:
            where.append("self_id = ?")
            params.append(self_id)
        if tiers:
            placeholders = ",".join(["?"] * len(tiers))
            where.append(f"tier IN ({placeholders})")
            params.extend(t.value for t in tiers)
        if source is not None:
            where.append("source = ?")
            params.append(source.value)
        elif sources is not None:
            sources_list = list(sources)
            placeholders = ",".join(["?"] * len(sources_list))
            where.append(f"source IN ({placeholders})")
            params.extend(s.value for s in sources_list)
        if intent_at_time is not None:
            where.append("intent_at_time = ?")
            params.append(intent_at_time)
        if created_after is not None:
            where.append("created_at > ?")
            params.append(created_after.isoformat())
        if not include_deleted and table == "episodic_memory":
            where.append("deleted = 0")
        if not include_superseded:
            where.append("superseded_by IS NULL")

        sql = f"SELECT * FROM {table}"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at DESC"
        with self._lock:
            cur = self._conn.execute(sql, tuple(params))
            cur.row_factory = sqlite3.Row  # type: ignore[assignment]
            rows = cur.fetchall()
        for row in rows:
            yield self._row_to_memory(row, include_deleted=(table == "episodic_memory"))

    def count_by_tier(self, tier: MemoryTier) -> int:
        table = "durable_memory" if tier in DURABLE_TIERS else "episodic_memory"
        self._validate_table(table)
        with self._lock:
            cur = self._conn.execute(f"SELECT COUNT(*) FROM {table} WHERE tier = ?", (tier.value,))
            return int(cur.fetchone()[0])


__all__ = [
    "ImmutableViolation",
    "ProvenanceViolation",
    "Repo",
    "RepoError",
    "WisdomDeferred",
]
