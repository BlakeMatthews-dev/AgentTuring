"""Self-authored todo operations. See specs/self-todos.md."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from .self_model import (
    ActivationContributor,
    ContributorOrigin,
    NodeKind,
    SelfTodo,
    SelfTodoRevision,
    TodoStatus,
    guess_node_kind,
)
from .self_repo import SelfRepo
from .self_surface import _require_ready


class TodoNotActive(Exception):
    pass


class TodoTextTooLong(Exception):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


def write_self_todo(
    repo: SelfRepo,
    self_id: str,
    text: str,
    motivated_by_node_id: str,
    new_id: Callable[[str], str],
) -> SelfTodo:
    _require_ready(repo, self_id)
    if len(text) > 500:
        raise TodoTextTooLong()
    if not motivated_by_node_id:
        raise ValueError("motivated_by_node_id is required")
    if not _motivator_exists(repo, self_id, motivated_by_node_id):
        raise ValueError(f"unknown motivator {motivated_by_node_id}")
    t = SelfTodo(
        node_id=new_id("todo"),
        self_id=self_id,
        text=text,
        motivated_by_node_id=motivated_by_node_id,
    )
    repo.insert_todo(t)
    return t


def revise_self_todo(
    repo: SelfRepo,
    self_id: str,
    todo_id: str,
    new_text: str,
    reason: str,
    new_id: Callable[[str], str],
) -> SelfTodo:
    t = repo.get_todo(todo_id)
    if t.self_id != self_id:
        raise PermissionError("cross-self revise forbidden")
    _require_ready(repo, self_id)
    if t.status != TodoStatus.ACTIVE:
        raise TodoNotActive(todo_id)
    if len(new_text) > 500:
        raise TodoTextTooLong()
    before = t.text
    t.text = new_text
    t.updated_at = _now()
    repo.update_todo(t)
    rev_num = repo.max_revision_num(todo_id) + 1
    repo.insert_todo_revision(
        SelfTodoRevision(
            node_id=new_id("todorev"),
            self_id=self_id,
            todo_id=todo_id,
            revision_num=rev_num,
            text_before=before,
            text_after=new_text,
            revised_at=_now(),
        )
    )
    return t


def complete_self_todo(
    repo: SelfRepo,
    self_id: str,
    todo_id: str,
    outcome_text: str,
    new_id: Callable[[str], str],
    affirmation_memory_id: str | None = None,
) -> SelfTodo:
    t = repo.get_todo(todo_id)
    if t.self_id != self_id:
        raise PermissionError("cross-self complete forbidden")
    _require_ready(repo, self_id)
    if not outcome_text.strip():
        raise ValueError("outcome_text is required on completion")
    if t.status != TodoStatus.ACTIVE:
        raise TodoNotActive(todo_id)
    t.status = TodoStatus.COMPLETED
    t.outcome_text = outcome_text
    t.updated_at = _now()
    repo.update_todo(t)

    if affirmation_memory_id is not None:
        repo.insert_contributor(
            ActivationContributor(
                node_id=new_id("contrib"),
                self_id=self_id,
                target_node_id=t.motivated_by_node_id,
                target_kind=guess_node_kind(t.motivated_by_node_id),
                source_id=affirmation_memory_id,
                source_kind="memory",
                weight=0.3,
                origin=ContributorOrigin.SELF,
                rationale="todo completion reinforces motivator",
            )
        )
    return t


def archive_self_todo(repo: SelfRepo, self_id: str, todo_id: str, reason: str) -> SelfTodo:
    t = repo.get_todo(todo_id)
    if t.self_id != self_id:
        raise PermissionError("cross-self archive forbidden")
    _require_ready(repo, self_id)
    if t.status == TodoStatus.COMPLETED:
        raise TodoNotActive(f"cannot archive completed todo {todo_id}")
    t.status = TodoStatus.ARCHIVED
    t.updated_at = _now()
    repo.update_todo(t)
    return t


def _motivator_exists(repo: SelfRepo, self_id: str, node_id: str) -> bool:
    if node_id.startswith("facet:"):
        for f in repo.list_facets(self_id):
            if f.node_id == node_id:
                return True
        return False
    if node_id.startswith("passion"):
        return any(p.node_id == node_id for p in repo.list_passions(self_id))
    if node_id.startswith("hobby"):
        return any(h.node_id == node_id for h in repo.list_hobbies(self_id))
    if node_id.startswith("interest"):
        return any(i.node_id == node_id for i in repo.list_interests(self_id))
    if node_id.startswith("pref"):
        return any(p.node_id == node_id for p in repo.list_preferences(self_id))
    if node_id.startswith("skill"):
        return any(s.node_id == node_id for s in repo.list_skills(self_id))
    return False
