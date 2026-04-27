"""Thin SQLite persistence layer for self-model nodes.

Row (de)serialization for every self-model dataclass in `self_model.py`.
Caller composes atomic sequences; this layer is intentionally small.

See specs/self-schema.md.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime

from .self_model import (
    ActivationContributor,
    ContributorOrigin,
    Hobby,
    Interest,
    Mood,
    NodeKind,
    PersonalityAnswer,
    PersonalityFacet,
    PersonalityItem,
    PersonalityRevision,
    Passion,
    Preference,
    PreferenceKind,
    SelfTodo,
    SelfTodoRevision,
    Skill,
    SkillKind,
    TodoStatus,
    Trait,
)


class CrossSelfAccess(Exception):
    pass


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat()


def _parse(s: str | None) -> datetime | None:
    if s is None:
        return None
    return datetime.fromisoformat(s).astimezone(UTC)


def _parse_req(s: str | None) -> datetime:
    parsed = _parse(s)
    if parsed is None:
        return datetime.now(UTC)
    return parsed


def get_mood_or_default(self_repo: SelfRepo, self_id: str) -> Mood:
    try:
        return self_repo.get_mood(self_id)
    except KeyError:
        return Mood(
            self_id=self_id,
            valence=0.0,
            arousal=0.3,
            focus=0.5,
            last_tick_at=datetime.now(UTC),
        )


class SelfRepo:
    """Self-model repository. Shares the connection with the memory `Repo`."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn

    # ------------------------------------------------ personality facets -----

    def insert_facet(self, f: PersonalityFacet) -> PersonalityFacet:
        self._conn.execute(
            """INSERT INTO self_personality_facets
               (node_id, self_id, trait, facet_id, score,
                last_revised_at, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                f.node_id,
                f.self_id,
                f.trait.value,
                f.facet_id,
                f.score,
                _iso(f.last_revised_at),
                _iso(f.created_at),
                _iso(f.updated_at),
            ),
        )
        self._conn.commit()
        return f

    def update_facet_score(
        self,
        self_id: str,
        facet_id: str,
        new_score: float,
        revised_at: datetime,
        *,
        acting_self_id: str | None = None,
    ) -> None:
        if acting_self_id is not None and self_id != acting_self_id:
            raise CrossSelfAccess(f"{self_id} vs {acting_self_id}")
        if not 1.0 <= new_score <= 5.0:
            raise ValueError(f"facet score out of range: {new_score}")
        now = _iso(datetime.now(UTC))
        cur = self._conn.execute(
            """UPDATE self_personality_facets
               SET score = ?, last_revised_at = ?, updated_at = ?
               WHERE self_id = ? AND facet_id = ?""",
            (new_score, _iso(revised_at), now, self_id, facet_id),
        )
        if cur.rowcount == 0:
            raise KeyError(f"no facet for self_id={self_id} facet_id={facet_id}")
        self._conn.commit()

    def get_facet(self, node_id: str) -> PersonalityFacet:
        row = self._conn.execute(
            "SELECT * FROM self_personality_facets WHERE node_id = ?", (node_id,)
        ).fetchone()
        if row is None:
            raise KeyError(node_id)
        return self._row_to_facet(row)

    def get_facet_score(self, self_id: str, facet_id: str) -> float:
        row = self._conn.execute(
            "SELECT score FROM self_personality_facets WHERE self_id = ? AND facet_id = ?",
            (self_id, facet_id),
        ).fetchone()
        if row is None:
            raise KeyError(f"{self_id}/{facet_id}")
        return float(row[0])

    def list_facets(self, self_id: str) -> list[PersonalityFacet]:
        rows = self._conn.execute(
            "SELECT * FROM self_personality_facets WHERE self_id = ?",
            (self_id,),
        ).fetchall()
        return [self._row_to_facet(r) for r in rows]

    def count_facets(self, self_id: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM self_personality_facets WHERE self_id = ?",
            (self_id,),
        ).fetchone()
        return int(row[0])

    def _row_to_facet(self, row: sqlite3.Row | tuple) -> PersonalityFacet:
        cols = [
            "node_id",
            "self_id",
            "trait",
            "facet_id",
            "score",
            "last_revised_at",
            "created_at",
            "updated_at",
        ]
        d = dict(zip(cols, row, strict=True))
        return PersonalityFacet(
            node_id=d["node_id"],
            self_id=d["self_id"],
            trait=Trait(d["trait"]),
            facet_id=d["facet_id"],
            score=float(d["score"]),
            last_revised_at=_parse_req(d["last_revised_at"]),
            created_at=_parse_req(d["created_at"]),
            updated_at=_parse_req(d["updated_at"]),
        )

    # ------------------------------------------------ personality items ------

    def insert_item(self, it: PersonalityItem) -> PersonalityItem:
        self._conn.execute(
            """INSERT INTO self_personality_items
               (node_id, self_id, item_number, prompt_text, keyed_facet,
                reverse_scored, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                it.node_id,
                it.self_id,
                it.item_number,
                it.prompt_text,
                it.keyed_facet,
                1 if it.reverse_scored else 0,
                _iso(it.created_at),
                _iso(it.updated_at),
            ),
        )
        self._conn.commit()
        return it

    def list_items(self, self_id: str) -> list[PersonalityItem]:
        rows = self._conn.execute(
            "SELECT node_id, self_id, item_number, prompt_text, keyed_facet, "
            "reverse_scored, created_at, updated_at "
            "FROM self_personality_items WHERE self_id = ? ORDER BY item_number",
            (self_id,),
        ).fetchall()
        return [
            PersonalityItem(
                node_id=r[0],
                self_id=r[1],
                item_number=int(r[2]),
                prompt_text=r[3],
                keyed_facet=r[4],
                reverse_scored=bool(r[5]),
                created_at=_parse_req(r[6]),
                updated_at=_parse_req(r[7]),
            )
            for r in rows
        ]

    def count_items(self, self_id: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM self_personality_items WHERE self_id = ?",
            (self_id,),
        ).fetchone()
        return int(row[0])

    # ------------------------------------------------ personality answers ---

    def insert_answer(self, a: PersonalityAnswer) -> PersonalityAnswer:
        self._conn.execute(
            """INSERT INTO self_personality_answers
               (node_id, self_id, item_id, revision_id, answer_1_5,
                justification_text, asked_at, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                a.node_id,
                a.self_id,
                a.item_id,
                a.revision_id,
                a.answer_1_5,
                a.justification_text,
                _iso(a.asked_at),
                _iso(a.created_at),
                _iso(a.updated_at),
            ),
        )
        self._conn.commit()
        return a

    def count_answers(self, self_id: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM self_personality_answers WHERE self_id = ?",
            (self_id,),
        ).fetchone()
        return int(row[0])

    def last_asked_map(self, self_id: str) -> dict[str, datetime]:
        rows = self._conn.execute(
            """SELECT item_id, MAX(asked_at) FROM self_personality_answers
               WHERE self_id = ? GROUP BY item_id""",
            (self_id,),
        ).fetchall()
        result: dict[str, datetime] = {}
        for r in rows:
            result[str(r[0])] = _parse_req(r[1])
        return result

    # ------------------------------------------------ revisions -------------

    def insert_revision(self, r: PersonalityRevision) -> PersonalityRevision:
        self._conn.execute(
            """INSERT INTO self_personality_revisions
               (node_id, self_id, revision_id, ran_at,
                sampled_item_ids, deltas_by_facet, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                r.node_id,
                r.self_id,
                r.revision_id,
                _iso(r.ran_at),
                json.dumps(r.sampled_item_ids),
                json.dumps(r.deltas_by_facet),
                _iso(r.created_at),
                _iso(r.updated_at),
            ),
        )
        self._conn.commit()
        return r

    # ------------------------------------------------ passions --------------

    def insert_passion(self, p: Passion) -> Passion:
        self._conn.execute(
            """INSERT INTO self_passions
               (node_id, self_id, text, strength, rank,
                first_noticed_at, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                p.node_id,
                p.self_id,
                p.text,
                p.strength,
                p.rank,
                _iso(p.first_noticed_at),
                _iso(p.created_at),
                _iso(p.updated_at),
            ),
        )
        self._conn.commit()
        return p

    def list_passions(self, self_id: str) -> list[Passion]:
        rows = self._conn.execute(
            "SELECT node_id, self_id, text, strength, rank, first_noticed_at, "
            "created_at, updated_at FROM self_passions WHERE self_id = ? "
            "ORDER BY rank",
            (self_id,),
        ).fetchall()
        return [
            Passion(
                node_id=r[0],
                self_id=r[1],
                text=r[2],
                strength=float(r[3]),
                rank=int(r[4]),
                first_noticed_at=_parse_req(r[5]),
                created_at=_parse_req(r[6]),
                updated_at=_parse_req(r[7]),
            )
            for r in rows
        ]

    def get_passion(self, node_id: str) -> Passion:
        row = self._conn.execute(
            "SELECT node_id, self_id, text, strength, rank, first_noticed_at, "
            "created_at, updated_at FROM self_passions WHERE node_id = ?",
            (node_id,),
        ).fetchone()
        if row is None:
            raise KeyError(node_id)
        return Passion(
            node_id=row[0],
            self_id=row[1],
            text=row[2],
            strength=float(row[3]),
            rank=int(row[4]),
            first_noticed_at=_parse_req(row[5]),
            created_at=_parse_req(row[6]),
            updated_at=_parse_req(row[7]),
        )

    def update_passion(self, p: Passion, *, acting_self_id: str | None = None) -> None:
        if acting_self_id is not None and p.self_id != acting_self_id:
            raise CrossSelfAccess(f"{p.self_id} vs {acting_self_id}")
        self._conn.execute(
            "UPDATE self_passions SET text = ?, strength = ?, rank = ?, "
            "updated_at = ? WHERE node_id = ?",
            (p.text, p.strength, p.rank, _iso(datetime.now(UTC)), p.node_id),
        )
        self._conn.commit()

    def max_passion_rank(self, self_id: str) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(MAX(rank), -1) FROM self_passions WHERE self_id = ?",
            (self_id,),
        ).fetchone()
        return int(row[0])

    def top_passion(self, self_id: str) -> Passion | None:
        row = self._conn.execute(
            "SELECT node_id FROM self_passions WHERE self_id = ? AND strength > 0 "
            "ORDER BY rank LIMIT 1",
            (self_id,),
        ).fetchone()
        if row is None:
            return None
        return self.get_passion(row[0])

    # ------------------------------------------------ hobbies, interests ----

    def insert_hobby(self, h: Hobby) -> Hobby:
        self._conn.execute(
            """INSERT INTO self_hobbies
               (node_id, self_id, name, description, strength, last_engaged_at,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                h.node_id,
                h.self_id,
                h.name,
                h.description,
                h.strength,
                _iso(h.last_engaged_at) if h.last_engaged_at else None,
                _iso(h.created_at),
                _iso(h.updated_at),
            ),
        )
        self._conn.commit()
        return h

    def list_hobbies(self, self_id: str) -> list[Hobby]:
        rows = self._conn.execute(
            "SELECT node_id, self_id, name, description, strength, last_engaged_at, "
            "created_at, updated_at FROM self_hobbies WHERE self_id = ?",
            (self_id,),
        ).fetchall()
        return [
            Hobby(
                node_id=r[0],
                self_id=r[1],
                name=r[2],
                description=r[3],
                strength=float(r[4]) if r[4] is not None else 0.5,
                last_engaged_at=_parse(r[5]),
                created_at=_parse_req(r[6]),
                updated_at=_parse_req(r[7]),
            )
            for r in rows
        ]

    def update_hobby(self, h: Hobby, *, acting_self_id: str | None = None) -> None:
        if acting_self_id is not None and h.self_id != acting_self_id:
            raise CrossSelfAccess(f"{h.self_id} vs {acting_self_id}")
        self._conn.execute(
            "UPDATE self_hobbies SET name = ?, description = ?, "
            "last_engaged_at = ?, updated_at = ? WHERE node_id = ?",
            (
                h.name,
                h.description,
                _iso(h.last_engaged_at) if h.last_engaged_at else None,
                _iso(datetime.now(UTC)),
                h.node_id,
            ),
        )
        self._conn.commit()

    def insert_interest(self, i: Interest) -> Interest:
        self._conn.execute(
            """INSERT OR IGNORE INTO self_interests
               (node_id, self_id, topic, description, last_noticed_at,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                i.node_id,
                i.self_id,
                i.topic,
                i.description,
                _iso(i.last_noticed_at) if i.last_noticed_at else None,
                _iso(i.created_at),
                _iso(i.updated_at),
            ),
        )
        self._conn.commit()
        return i

    def list_interests(self, self_id: str) -> list[Interest]:
        rows = self._conn.execute(
            "SELECT node_id, self_id, topic, description, last_noticed_at, "
            "created_at, updated_at FROM self_interests WHERE self_id = ?",
            (self_id,),
        ).fetchall()
        return [
            Interest(
                node_id=r[0],
                self_id=r[1],
                topic=r[2],
                description=r[3],
                last_noticed_at=_parse(r[4]),
                created_at=_parse_req(r[5]),
                updated_at=_parse_req(r[6]),
            )
            for r in rows
        ]

    # ------------------------------------------------ preferences -----------

    def insert_preference(self, p: Preference) -> Preference:
        self._conn.execute(
            """INSERT INTO self_preferences
               (node_id, self_id, kind, target, strength, rationale,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                p.node_id,
                p.self_id,
                p.kind.value,
                p.target,
                p.strength,
                p.rationale,
                _iso(p.created_at),
                _iso(p.updated_at),
            ),
        )
        self._conn.commit()
        return p

    def list_preferences(self, self_id: str) -> list[Preference]:
        rows = self._conn.execute(
            "SELECT node_id, self_id, kind, target, strength, rationale, "
            "created_at, updated_at FROM self_preferences WHERE self_id = ?",
            (self_id,),
        ).fetchall()
        return [
            Preference(
                node_id=r[0],
                self_id=r[1],
                kind=PreferenceKind(r[2]),
                target=r[3],
                strength=float(r[4]),
                rationale=r[5],
                created_at=_parse_req(r[6]),
                updated_at=_parse_req(r[7]),
            )
            for r in rows
        ]

    # ------------------------------------------------ skills ----------------

    def insert_skill(self, s: Skill) -> Skill:
        self._conn.execute(
            """INSERT INTO self_skills
               (node_id, self_id, name, kind, stored_level, best_version,
                last_practiced_at, active_coaching, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                s.node_id,
                s.self_id,
                s.name,
                s.kind.value,
                s.stored_level,
                s.best_version,
                _iso(s.last_practiced_at),
                s.active_coaching,
                _iso(s.created_at),
                _iso(s.updated_at),
            ),
        )
        self._conn.commit()
        return s

    def get_skill(self, node_id: str) -> Skill:
        row = self._conn.execute(
            "SELECT node_id, self_id, name, kind, stored_level, best_version, "
            "last_practiced_at, active_coaching, created_at, updated_at "
            "FROM self_skills WHERE node_id = ?",
            (node_id,),
        ).fetchone()
        if row is None:
            raise KeyError(node_id)
        return self._row_to_skill(row)

    def list_skills(self, self_id: str) -> list[Skill]:
        rows = self._conn.execute(
            "SELECT node_id, self_id, name, kind, stored_level, best_version, "
            "last_practiced_at, active_coaching, created_at, updated_at "
            "FROM self_skills WHERE self_id = ?",
            (self_id,),
        ).fetchall()
        return [self._row_to_skill(r) for r in rows]

    def update_skill(self, s: Skill, *, acting_self_id: str | None = None) -> None:
        if acting_self_id is not None and s.self_id != acting_self_id:
            raise CrossSelfAccess(f"{s.self_id} vs {acting_self_id}")
        self._conn.execute(
            "UPDATE self_skills SET stored_level = ?, best_version = ?, "
            "last_practiced_at = ?, active_coaching = ?, updated_at = ? WHERE node_id = ?",
            (
                s.stored_level,
                s.best_version,
                _iso(s.last_practiced_at),
                s.active_coaching,
                _iso(datetime.now(UTC)),
                s.node_id,
            ),
        )
        self._conn.commit()

    def _row_to_skill(self, r: tuple) -> Skill:
        return Skill(
            node_id=r[0],
            self_id=r[1],
            name=r[2],
            kind=SkillKind(r[3]),
            stored_level=float(r[4]),
            best_version=int(r[5]) if r[5] is not None else 0,
            last_practiced_at=_parse_req(r[6]),
            active_coaching=r[7],
            created_at=_parse_req(r[8]),
            updated_at=_parse_req(r[9]),
        )

    # ------------------------------------------------ todos -----------------

    def insert_todo(self, t: SelfTodo) -> SelfTodo:
        self._conn.execute(
            """INSERT INTO self_todos
               (node_id, self_id, text, motivated_by_node_id, status,
                outcome_text, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                t.node_id,
                t.self_id,
                t.text,
                t.motivated_by_node_id,
                t.status.value,
                t.outcome_text,
                _iso(t.created_at),
                _iso(t.updated_at),
            ),
        )
        self._conn.commit()
        return t

    def get_todo(self, node_id: str) -> SelfTodo:
        row = self._conn.execute(
            "SELECT node_id, self_id, text, motivated_by_node_id, status, "
            "outcome_text, created_at, updated_at "
            "FROM self_todos WHERE node_id = ?",
            (node_id,),
        ).fetchone()
        if row is None:
            raise KeyError(node_id)
        return self._row_to_todo(row)

    def list_active_todos(self, self_id: str) -> list[SelfTodo]:
        rows = self._conn.execute(
            "SELECT node_id, self_id, text, motivated_by_node_id, status, "
            "outcome_text, created_at, updated_at "
            "FROM self_todos WHERE self_id = ? AND status = 'active' "
            "ORDER BY created_at",
            (self_id,),
        ).fetchall()
        return [self._row_to_todo(r) for r in rows]

    def list_todos_for_motivator(
        self, self_id: str, motivator_id: str, include_archived: bool = False
    ) -> list[SelfTodo]:
        q = (
            "SELECT node_id, self_id, text, motivated_by_node_id, status, "
            "outcome_text, created_at, updated_at "
            "FROM self_todos WHERE self_id = ? AND motivated_by_node_id = ?"
        )
        if not include_archived:
            q += " AND status <> 'archived'"
        q += " ORDER BY created_at"
        rows = self._conn.execute(q, (self_id, motivator_id)).fetchall()
        return [self._row_to_todo(r) for r in rows]

    def update_todo(self, t: SelfTodo, *, acting_self_id: str | None = None) -> None:
        if acting_self_id is not None and t.self_id != acting_self_id:
            raise CrossSelfAccess(f"{t.self_id} vs {acting_self_id}")
        self._conn.execute(
            "UPDATE self_todos SET text = ?, status = ?, outcome_text = ?, "
            "updated_at = ? WHERE node_id = ?",
            (
                t.text,
                t.status.value,
                t.outcome_text,
                _iso(datetime.now(UTC)),
                t.node_id,
            ),
        )
        self._conn.commit()

    def insert_todo_revision(
        self,
        r: SelfTodoRevision,
        *,
        acting_self_id: str | None = None,
    ) -> SelfTodoRevision:
        if acting_self_id is not None and r.self_id != acting_self_id:
            raise CrossSelfAccess(f"{r.self_id} vs {acting_self_id}")
        self._conn.execute(
            """INSERT INTO self_todo_revisions
               (node_id, self_id, todo_id, revision_num, text_before, text_after,
                revised_at, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                r.node_id,
                r.self_id,
                r.todo_id,
                r.revision_num,
                r.text_before,
                r.text_after,
                _iso(r.revised_at),
                _iso(r.created_at),
                _iso(r.updated_at),
            ),
        )
        self._conn.commit()
        return r

    def list_todo_revisions(self, todo_id: str) -> list[SelfTodoRevision]:
        rows = self._conn.execute(
            "SELECT node_id, self_id, todo_id, revision_num, text_before, text_after, "
            "revised_at, created_at, updated_at "
            "FROM self_todo_revisions WHERE todo_id = ? ORDER BY revision_num",
            (todo_id,),
        ).fetchall()
        return [
            SelfTodoRevision(
                node_id=r[0],
                self_id=r[1],
                todo_id=r[2],
                revision_num=int(r[3]),
                text_before=r[4],
                text_after=r[5],
                revised_at=_parse_req(r[6]),
                created_at=_parse_req(r[7]),
                updated_at=_parse_req(r[8]),
            )
            for r in rows
        ]

    def max_revision_num(self, todo_id: str) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(MAX(revision_num), 0) FROM self_todo_revisions WHERE todo_id = ?",
            (todo_id,),
        ).fetchone()
        return int(row[0])

    def _row_to_todo(self, r: tuple) -> SelfTodo:
        # Bypass dataclass validation; row is already validated by schema CHECKs.
        # (Completed rows may have non-empty outcome_text, which the ctor enforces,
        # but rows returning from the DB always satisfy ctor invariants.)
        return SelfTodo(
            node_id=r[0],
            self_id=r[1],
            text=r[2],
            motivated_by_node_id=r[3],
            status=TodoStatus(r[4]),
            outcome_text=r[5],
            created_at=_parse_req(r[6]),
            updated_at=_parse_req(r[7]),
        )

    # ------------------------------------------------ mood ------------------

    def insert_mood(self, m: Mood) -> Mood:
        self._conn.execute(
            """INSERT INTO self_mood
               (self_id, valence, arousal, focus, last_tick_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                m.self_id,
                m.valence,
                m.arousal,
                m.focus,
                _iso(m.last_tick_at),
                _iso(m.updated_at),
            ),
        )
        self._conn.commit()
        return m

    def update_mood(self, m: Mood, *, acting_self_id: str | None = None) -> None:
        if acting_self_id is not None and m.self_id != acting_self_id:
            raise CrossSelfAccess(f"{m.self_id} vs {acting_self_id}")
        self._conn.execute(
            "UPDATE self_mood SET valence = ?, arousal = ?, focus = ?, "
            "last_tick_at = ?, updated_at = ? WHERE self_id = ?",
            (
                m.valence,
                m.arousal,
                m.focus,
                _iso(m.last_tick_at),
                _iso(datetime.now(UTC)),
                m.self_id,
            ),
        )
        self._conn.commit()

    def get_mood(self, self_id: str) -> Mood:
        row = self._conn.execute(
            "SELECT self_id, valence, arousal, focus, last_tick_at, updated_at "
            "FROM self_mood WHERE self_id = ?",
            (self_id,),
        ).fetchone()
        if row is None:
            raise KeyError(self_id)
        return Mood(
            self_id=row[0],
            valence=float(row[1]),
            arousal=float(row[2]),
            focus=float(row[3]),
            last_tick_at=_parse_req(row[4]),
            updated_at=_parse_req(row[5]),
        )

    def has_mood(self, self_id: str) -> bool:
        row = self._conn.execute("SELECT 1 FROM self_mood WHERE self_id = ?", (self_id,)).fetchone()
        return row is not None

    # ------------------------------------------------ activation graph ------

    def insert_contributor(
        self,
        c: ActivationContributor,
        *,
        acting_self_id: str | None = None,
    ) -> ActivationContributor:
        if acting_self_id is not None and c.self_id != acting_self_id:
            raise CrossSelfAccess(f"{c.self_id} vs {acting_self_id}")
        self._conn.execute(
            """INSERT INTO self_activation_contributors
               (node_id, self_id, target_node_id, target_kind,
                source_id, source_kind, weight, origin, rationale,
                expires_at, retracted_by, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                c.node_id,
                c.self_id,
                c.target_node_id,
                c.target_kind.value,
                c.source_id,
                c.source_kind,
                c.weight,
                c.origin.value,
                c.rationale,
                _iso(c.expires_at) if c.expires_at else None,
                c.retracted_by,
                _iso(c.created_at),
                _iso(c.updated_at),
            ),
        )
        self._conn.commit()
        return c

    def active_contributors_for(
        self, target_node_id: str, at: datetime
    ) -> list[ActivationContributor]:
        rows = self._conn.execute(
            """SELECT node_id, self_id, target_node_id, target_kind,
                      source_id, source_kind, weight, origin, rationale,
                      expires_at, retracted_by, created_at, updated_at
               FROM self_activation_contributors
               WHERE target_node_id = ?
                 AND (expires_at IS NULL OR expires_at > ?)
                 AND retracted_by IS NULL""",
            (target_node_id, _iso(at)),
        ).fetchall()
        return [self._row_to_contributor(r) for r in rows]

    def mark_contributor_retracted(self, contributor_node_id: str, retracted_by: str) -> None:
        self._conn.execute(
            "UPDATE self_activation_contributors SET retracted_by = ?, updated_at = ? "
            "WHERE node_id = ?",
            (retracted_by, _iso(datetime.now(UTC)), contributor_node_id),
        )
        self._conn.commit()

    def get_contributor(self, node_id: str) -> ActivationContributor | None:
        row = self._conn.execute(
            "SELECT node_id, self_id, target_node_id, target_kind, "
            "source_id, source_kind, weight, origin, rationale, "
            "expires_at, retracted_by, created_at, updated_at "
            "FROM self_activation_contributors WHERE node_id = ?",
            (node_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_contributor(row)

    def _row_to_contributor(self, r: tuple) -> ActivationContributor:
        return ActivationContributor(
            node_id=r[0],
            self_id=r[1],
            target_node_id=r[2],
            target_kind=NodeKind(r[3]),
            source_id=r[4],
            source_kind=r[5],
            weight=float(r[6]),
            origin=ContributorOrigin(r[7]),
            rationale=r[8],
            expires_at=_parse(r[9]),
            retracted_by=r[10],
            created_at=_parse_req(r[11]),
            updated_at=_parse_req(r[12]),
        )

    # ------------------------------------------------ bootstrap progress ----

    def start_bootstrap_progress(self, self_id: str, seed: int | None) -> None:
        now = _iso(datetime.now(UTC))
        self._conn.execute(
            """INSERT INTO self_bootstrap_progress
               (self_id, seed, last_item_number, started_at, updated_at)
               VALUES (?, ?, 0, ?, ?)""",
            (self_id, seed, now, now),
        )
        self._conn.commit()

    def update_bootstrap_progress(self, self_id: str, last_item_number: int) -> None:
        self._conn.execute(
            "UPDATE self_bootstrap_progress SET last_item_number = ?, updated_at = ? "
            "WHERE self_id = ?",
            (last_item_number, _iso(datetime.now(UTC)), self_id),
        )
        self._conn.commit()

    def get_bootstrap_progress(self, self_id: str) -> int | None:
        row = self._conn.execute(
            "SELECT last_item_number FROM self_bootstrap_progress WHERE self_id = ?",
            (self_id,),
        ).fetchone()
        return int(row[0]) if row else None

    def delete_bootstrap_progress(self, self_id: str) -> None:
        self._conn.execute(
            "DELETE FROM self_bootstrap_progress WHERE self_id = ?",
            (self_id,),
        )
        self._conn.commit()

    # ------------------------------------------------ code snapshots ---------

    def upsert_code_snapshot(
        self,
        *,
        snapshot_id: str,
        self_id: str,
        file_path: str,
        content_hash: str,
        content: str,
        line_count: int,
        reflection: str,
        reflection_embedding: bytes | None = None,
        content_embedding: bytes | None = None,
        metadata_json: str | None = None,
    ) -> None:
        now = _iso(datetime.now(UTC))
        existing = self._conn.execute(
            "SELECT snapshot_id FROM code_snapshots "
            "WHERE self_id = ? AND file_path = ? AND content_hash = ?",
            (self_id, file_path, content_hash),
        ).fetchone()
        if existing is not None:
            self._conn.execute(
                """UPDATE code_snapshots
                   SET reflection = ?, reflection_embedding = ?,
                       content_embedding = ?, metadata_json = ?,
                       updated_at = ?
                   WHERE snapshot_id = ?""",
                (
                    reflection,
                    reflection_embedding,
                    content_embedding,
                    metadata_json,
                    now,
                    existing[0],
                ),
            )
        else:
            self._conn.execute(
                """INSERT INTO code_snapshots
                   (snapshot_id, self_id, file_path, content_hash, content,
                    line_count, reflection, reflection_embedding,
                    content_embedding, metadata_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    snapshot_id,
                    self_id,
                    file_path,
                    content_hash,
                    content,
                    line_count,
                    reflection,
                    reflection_embedding,
                    content_embedding,
                    metadata_json,
                    now,
                    now,
                ),
            )
        self._conn.commit()

    def list_code_snapshots(self, self_id: str, limit: int = 20) -> list[dict]:
        rows = self._conn.execute(
            "SELECT snapshot_id, file_path, content_hash, line_count, "
            "reflection, created_at, updated_at "
            "FROM code_snapshots WHERE self_id = ? "
            "ORDER BY updated_at DESC LIMIT ?",
            (self_id, limit),
        ).fetchall()
        return [
            {
                "snapshot_id": r[0],
                "file_path": r[1],
                "content_hash": r[2],
                "line_count": r[3],
                "reflection": r[4],
                "created_at": r[5],
                "updated_at": r[6],
            }
            for r in rows
        ]

    def has_code_snapshot(self, self_id: str, file_path: str, content_hash: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM code_snapshots WHERE self_id = ? AND file_path = ? AND content_hash = ?",
            (self_id, file_path, content_hash),
        ).fetchone()
        return row is not None

    # ------------------------------------------------ concepts ---------------

    def insert_concept(
        self,
        node_id: str,
        self_id: str,
        name: str,
        definition: str,
        importance: float,
        origin_drive: str,
    ) -> None:
        now = _iso(datetime.now(UTC))
        self._conn.execute(
            """INSERT OR IGNORE INTO self_concepts
               (node_id, self_id, name, definition, importance,
                origin_drive, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (node_id, self_id, name, definition, importance, origin_drive, now, now),
        )
        self._conn.commit()

    def list_concepts(self, self_id: str, min_importance: float = 0.0) -> list[dict]:
        rows = self._conn.execute(
            "SELECT node_id, name, definition, importance, origin_drive, "
            "created_at, updated_at FROM self_concepts "
            "WHERE self_id = ? AND importance >= ? "
            "ORDER BY importance DESC",
            (self_id, min_importance),
        ).fetchall()
        return [
            {
                "node_id": r[0],
                "name": r[1],
                "definition": r[2],
                "importance": float(r[3]),
                "origin_drive": r[4],
                "created_at": r[5],
                "updated_at": r[6],
            }
            for r in rows
        ]

    def has_concept(self, self_id: str, name: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM self_concepts WHERE self_id = ? AND name = ?",
            (self_id, name),
        ).fetchone()
        return row is not None

    def count_concepts(self, self_id: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM self_concepts WHERE self_id = ?",
            (self_id,),
        ).fetchone()
        return int(row[0])

    # ------------------------------------------------ skill attempts ---------

    def insert_skill_artifact(
        self,
        *,
        artifact_id: str,
        self_id: str,
        skill_id: str,
        version: int,
        artifact_text: str,
        score: float,
        judge_notes: str,
        coaching: str | None = None,
    ) -> None:
        now = _iso(datetime.now(UTC))
        self._conn.execute(
            """INSERT INTO self_skill_artifacts
               (artifact_id, self_id, skill_id, version, artifact_text,
                score, judge_notes, coaching, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                artifact_id,
                self_id,
                skill_id,
                version,
                artifact_text,
                score,
                judge_notes,
                coaching,
                now,
            ),
        )
        self._conn.execute(
            "UPDATE self_skills SET practice_count = practice_count + 1, "
            "last_practiced_at = ?, updated_at = ? WHERE node_id = ?",
            (now, now, skill_id),
        )
        self._conn.commit()

    def list_skill_artifacts(self, skill_id: str, limit: int = 10) -> list[dict]:
        rows = self._conn.execute(
            "SELECT artifact_id, skill_id, version, artifact_text, score, "
            "judge_notes, coaching, created_at "
            "FROM self_skill_artifacts WHERE skill_id = ? "
            "ORDER BY version DESC LIMIT ?",
            (skill_id, limit),
        ).fetchall()
        return [
            {
                "artifact_id": r[0],
                "skill_id": r[1],
                "version": r[2],
                "artifact_text": r[3],
                "score": r[4],
                "judge_notes": r[5],
                "coaching": r[6],
                "created_at": r[7],
            }
            for r in rows
        ]

    def get_best_artifact(self, skill_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT artifact_id, version, artifact_text, score, judge_notes "
            "FROM self_skill_artifacts WHERE skill_id = ? "
            "ORDER BY score DESC, version DESC LIMIT 1",
            (skill_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "artifact_id": row[0],
            "version": row[1],
            "artifact_text": row[2],
            "score": row[3],
            "judge_notes": row[4],
        }

    def get_latest_artifact(self, skill_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT artifact_id, version, artifact_text, score, judge_notes, coaching "
            "FROM self_skill_artifacts WHERE skill_id = ? "
            "ORDER BY version DESC LIMIT 1",
            (skill_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "artifact_id": row[0],
            "version": row[1],
            "artifact_text": row[2],
            "score": row[3],
            "judge_notes": row[4],
            "coaching": row[5],
        }

    def count_skill_artifacts(self, skill_id: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM self_skill_artifacts WHERE skill_id = ?",
            (skill_id,),
        ).fetchone()
        return int(row[0])

    def set_skill_coaching(self, skill_id: str, coaching: str) -> None:
        self._conn.execute(
            "UPDATE self_skills SET active_coaching = ?, updated_at = ? WHERE node_id = ?",
            (coaching, _iso(datetime.now(UTC)), skill_id),
        )
        self._conn.commit()

    def delete_expired_retrieval_contributors(self, now) -> int:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM self_activation_contributors "
                "WHERE origin = 'retrieval' AND expires_at IS NOT NULL AND expires_at < ?",
                (now.isoformat(),),
            )
            self._conn.commit()
            return cur.rowcount

    def delete_expired_retrieval_contributors_for_target(self, target_node_id: str, now) -> int:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM self_activation_contributors "
                "WHERE origin = 'retrieval' AND target_node_id = ? "
                "AND expires_at IS NOT NULL AND expires_at < ?",
                (target_node_id, now.isoformat()),
            )
            self._conn.commit()
            return cur.rowcount

    def count_active_retrieval_contributors(self, target_node_id: str, now) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM self_activation_contributors "
            "WHERE target_node_id = ? AND origin = 'retrieval' "
            "AND retracted_at IS NULL AND (expires_at IS NULL OR expires_at >= ?)",
            (target_node_id, now.isoformat()),
        ).fetchone()
        return int(row[0])

    def list_revisions_since(self, self_id: str, since):
        rows = self._conn.execute(
            "SELECT node_id, self_id, revision_num, deltas_by_facet, revised_at "
            "FROM self_personality_revisions "
            "WHERE self_id = ? AND revised_at >= ? ORDER BY revised_at",
            (self_id, since.isoformat() if hasattr(since, "isoformat") else since),
        ).fetchall()
        from .self_model import PersonalityRevision

        result = []
        for r in rows:
            import json

            deltas = json.loads(r[3]) if r[3] else {}
            result.append(
                PersonalityRevision(
                    node_id=r[0],
                    self_id=r[1],
                    revision_num=r[2],
                    deltas_by_facet=deltas,
                    revised_at=r[4],
                )
            )
        return result

    def list_todo_ids_with_revisions(self, self_id: str, min_revisions: int = 11) -> list[str]:
        rows = self._conn.execute(
            "SELECT todo_id FROM self_todo_revisions WHERE self_id = ? "
            "GROUP BY todo_id HAVING COUNT(*) >= ?",
            (self_id, min_revisions),
        ).fetchall()
        return [r[0] for r in rows]

    def compact_todo_revision(self, node_id: str, now) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE self_todo_revisions SET text_before = '[compacted]', "
                "text_after = '[compacted]' WHERE node_id = ?",
                (node_id,),
            )
            self._conn.commit()

    def list_recent_revision_ids(self, self_id: str, limit: int = 12) -> list[str]:
        rows = self._conn.execute(
            "SELECT node_id FROM self_personality_revisions "
            "WHERE self_id = ? ORDER BY revised_at DESC LIMIT ?",
            (self_id, limit),
        ).fetchall()
        return [r[0] for r in rows]

    def list_answers_for_compaction(self, self_id: str, exclude_revision_ids: list[str]) -> list:
        if not exclude_revision_ids:
            placeholders = "1=0"
            params: list = [self_id]
        else:
            placeholders = ",".join(["?"] * len(exclude_revision_ids))
            params = [self_id] + exclude_revision_ids
        rows = self._conn.execute(
            f"SELECT node_id FROM self_personality_answers "
            f"WHERE self_id = ? AND revision_id IS NOT NULL "
            f"AND revision_id NOT IN ({placeholders})",
            params,
        ).fetchall()
        return [type("Ans", (), {"node_id": r[0]})() for r in rows]

    def compact_personality_answer(self, node_id: str, now) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE self_personality_answers SET justification_text = '[compacted]' "
                "WHERE node_id = ?",
                (node_id,),
            )
            self._conn.commit()
