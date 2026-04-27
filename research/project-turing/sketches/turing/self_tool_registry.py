"""Self-tool registry: function-call schema generation, dispatch, and trust-tier gating.

See specs/self-tool-registry.md (Spec 31).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .self_contributors import (
    NoMatchingContributor,
    note_engagement,
    note_interest_trigger,
    record_personality_claim,
    retract_contributor_by_counter,
    write_contributor,
)
from .self_model import PreferenceKind, SkillKind
from .self_nodes import (
    downgrade_skill,
    note_hobby,
    note_interest,
    note_passion,
    note_preference,
    note_skill,
    practice_skill,
    rerank_passions,
)
from .self_repo import SelfRepo
from .self_surface import SelfNotReady
from .self_todos import (
    archive_self_todo,
    complete_self_todo,
    revise_self_todo,
    write_self_todo,
)

TOOL_DESCRIPTION_MAX: int = 400


class ToolRegistrationError(Exception):
    pass


class UnknownSelfTool(Exception):
    pass


class TrustTierViolation(Exception):
    pass


@dataclass(frozen=True)
class SelfTool:
    name: str
    description: str
    schema: dict
    handler: Callable[..., Any]
    trust_tier: str = "t0"

    def __post_init__(self) -> None:
        if len(self.description) > TOOL_DESCRIPTION_MAX:
            raise ToolRegistrationError(f"description too long: {self.name}")
        if not self.description.lstrip().startswith("I "):
            raise ToolRegistrationError(
                f"tool {self.name} description must start with 'I ' (first-person)"
            )
        if self.trust_tier != "t0":
            raise ToolRegistrationError(f"self-tools are t0; got {self.trust_tier}")


SELF_TOOL_REGISTRY: dict[str, SelfTool] = {}


def register_self_tool(tool: SelfTool) -> None:
    if tool.name in SELF_TOOL_REGISTRY:
        raise ToolRegistrationError(f"duplicate tool: {tool.name}")
    SELF_TOOL_REGISTRY[tool.name] = tool


class SelfRuntime:
    def __init__(
        self,
        *,
        cache_path: Path | None = None,
        mirror_fn: Callable[[str], None] | None = None,
    ) -> None:
        self._cache_path = cache_path
        self._mirror_fn = mirror_fn
        self._schemas_cache: list[dict] | None = None

    def tool_schemas(self) -> list[dict]:
        if self._schemas_cache is not None and self._cache_path is None:
            return self._schemas_cache

        if self._cache_path is not None and self._cache_path.exists():
            with open(self._cache_path) as f:
                self._schemas_cache = json.load(f)
                return self._schemas_cache

        schemas = []
        for tool in SELF_TOOL_REGISTRY.values():
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.schema,
                    },
                }
            )
        self._schemas_cache = schemas

        if self._cache_path is not None:
            with open(self._cache_path, "w") as f:
                json.dump(schemas, f, indent=2)

        return schemas

    def invoke(
        self,
        tool_name: str,
        self_id: str,
        args: dict[str, Any],
        *,
        caller_tier: str = "t0",
    ) -> Any:
        if tool_name not in SELF_TOOL_REGISTRY:
            raise UnknownSelfTool(tool_name)
        tool = SELF_TOOL_REGISTRY[tool_name]
        if caller_tier != "t0":
            raise TrustTierViolation(f"caller tier {caller_tier} != t0")
        try:
            return tool.handler(self_id=self_id, **args)
        except SelfNotReady:
            raise
        except Exception as err:
            if self._mirror_fn is not None:
                self._mirror_fn(f"I attempted {tool_name}; the write failed: {err}")
            raise


def _ack(kind: str) -> Callable[..., dict[str, Any]]:
    def handler(self_id: str, **kwargs: Any) -> dict[str, Any]:
        return {"status": "noted", "kind": kind, "self_id": self_id}

    return handler


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4()}"


def _make_node_handlers(repo: SelfRepo) -> dict[str, Callable[..., Any]]:
    """Create real handlers for note_* tools, bound to a SelfRepo."""

    def _note_passion(self_id: str, text: str, strength: float) -> dict[str, Any]:
        p = note_passion(repo, self_id, text, strength, _new_id)
        return {"status": "created", "node_id": p.node_id}

    def _note_hobby(self_id: str, name: str, description: str) -> dict[str, Any]:
        h = note_hobby(repo, self_id, name, description, _new_id)
        return {"status": "created", "node_id": h.node_id}

    def _note_interest(self_id: str, topic: str, description: str) -> dict[str, Any]:
        i = note_interest(repo, self_id, topic, description, _new_id)
        return {"status": "created", "node_id": i.node_id}

    def _note_preference(
        self_id: str, kind: str, target: str, strength: float, rationale: str
    ) -> dict[str, Any]:
        p = note_preference(
            repo, self_id, PreferenceKind(kind), target, strength, rationale, _new_id
        )
        return {"status": "created", "node_id": p.node_id}

    def _note_skill(self_id: str, name: str, level: float, kind: str) -> dict[str, Any]:
        s = note_skill(repo, self_id, name, level, SkillKind(kind), _new_id)
        return {"status": "created", "node_id": s.node_id}

    def _write_todo(self_id: str, text: str, motivated_by_node_id: str) -> dict[str, Any]:
        t = write_self_todo(repo, self_id, text, motivated_by_node_id, _new_id)
        return {"status": "created", "node_id": t.node_id}

    def _revise_todo(self_id: str, todo_id: str, new_text: str, reason: str) -> dict[str, Any]:
        t = revise_self_todo(repo, self_id, todo_id, new_text, reason, _new_id)
        return {"status": "revised", "node_id": t.node_id}

    def _complete_todo(self_id: str, todo_id: str, outcome_text: str) -> dict[str, Any]:
        t = complete_self_todo(repo, self_id, todo_id, outcome_text, _new_id)
        return {"status": "completed", "node_id": t.node_id}

    def _archive_todo(self_id: str, todo_id: str, reason: str) -> dict[str, Any]:
        t = archive_self_todo(repo, self_id, todo_id, reason)
        return {"status": "archived", "node_id": t.node_id}

    def _practice_skill(
        self_id: str, skill_id: str, new_level: float | None = None, notes: str = ""
    ) -> dict[str, Any]:
        s = practice_skill(repo, self_id, skill_id, new_level=new_level, notes=notes)
        return {"status": "practiced", "node_id": s.node_id, "level": s.stored_level}

    def _downgrade_skill(
        self_id: str, skill_id: str, new_level: float, reason: str
    ) -> dict[str, Any]:
        s = downgrade_skill(repo, self_id, skill_id, new_level, reason)
        return {"status": "downgraded", "node_id": s.node_id, "level": s.stored_level}

    def _rerank_passions(self_id: str, ordered_ids: list[str]) -> dict[str, Any]:
        passions = rerank_passions(repo, self_id, ordered_ids)
        return {"status": "reranked", "count": len(passions)}

    return {
        "note_passion": _note_passion,
        "note_hobby": _note_hobby,
        "note_interest": _note_interest,
        "note_preference": _note_preference,
        "note_skill": _note_skill,
        "write_self_todo": _write_todo,
        "revise_self_todo": _revise_todo,
        "complete_self_todo": _complete_todo,
        "archive_self_todo": _archive_todo,
        "practice_skill": _practice_skill,
        "downgrade_skill": _downgrade_skill,
        "rerank_passions": _rerank_passions,
    }


_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "recall_self",
        "description": "I recall my current self-model state for use in a prompt",
        "schema": {"type": "object", "properties": {}},
        "handler": _ack("recall_self"),
    },
    {
        "name": "write_self_todo",
        "description": "I write a new todo item motivated by a self-model node",
        "schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "maxLength": 500},
                "motivated_by_node_id": {"type": "string"},
            },
            "required": ["text", "motivated_by_node_id"],
        },
        "handler": _ack("write_self_todo"),
    },
    {
        "name": "note_passion",
        "description": "I note a new passion that I care about deeply",
        "schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "strength": {"type": "number", "minimum": 0, "maximum": 1},
            },
            "required": ["text", "strength"],
        },
        "handler": _ack("note_passion"),
    },
    {
        "name": "note_hobby",
        "description": "I note a hobby I enjoy engaging with",
        "schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "description": {"type": "string"},
            },
            "required": ["name", "description"],
        },
        "handler": _ack("note_hobby"),
    },
    {
        "name": "note_interest",
        "description": "I note a new topic of interest I want to explore",
        "schema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string"},
                "description": {"type": "string"},
            },
            "required": ["topic", "description"],
        },
        "handler": _ack("note_interest"),
    },
    {
        "name": "note_preference",
        "description": "I note a preference, like, dislike, or avoidance",
        "schema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["like", "dislike", "favorite", "avoid"]},
                "target": {"type": "string"},
                "strength": {"type": "number", "minimum": 0, "maximum": 1},
                "rationale": {"type": "string"},
            },
            "required": ["kind", "target", "strength", "rationale"],
        },
        "handler": _ack("note_preference"),
    },
    {
        "name": "note_skill",
        "description": "I note a skill I am developing or tracking",
        "schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "level": {"type": "number", "minimum": 0, "maximum": 1},
                "kind": {
                    "type": "string",
                    "enum": ["intellectual", "physical", "habit", "social", "creative"],
                },
            },
            "required": ["name", "level", "kind"],
        },
        "handler": _ack("note_skill"),
    },
    {
        "name": "revise_self_todo",
        "description": "I revise the text of one of my active todos",
        "schema": {
            "type": "object",
            "properties": {
                "todo_id": {"type": "string"},
                "new_text": {"type": "string", "maxLength": 500},
                "reason": {"type": "string"},
            },
            "required": ["todo_id", "new_text", "reason"],
        },
        "handler": _ack("revise_self_todo"),
    },
    {
        "name": "complete_self_todo",
        "description": "I mark one of my todos as completed with an outcome",
        "schema": {
            "type": "object",
            "properties": {
                "todo_id": {"type": "string"},
                "outcome_text": {"type": "string"},
            },
            "required": ["todo_id", "outcome_text"],
        },
        "handler": _ack("complete_self_todo"),
    },
    {
        "name": "archive_self_todo",
        "description": "I archive a todo I no longer intend to pursue",
        "schema": {
            "type": "object",
            "properties": {
                "todo_id": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["todo_id", "reason"],
        },
        "handler": _ack("archive_self_todo"),
    },
    {
        "name": "practice_skill",
        "description": "I record practice on a skill I am developing",
        "schema": {
            "type": "object",
            "properties": {
                "skill_id": {"type": "string"},
                "new_level": {"type": "number", "minimum": 0, "maximum": 1},
                "notes": {"type": "string"},
            },
            "required": ["skill_id"],
        },
        "handler": _ack("practice_skill"),
    },
    {
        "name": "downgrade_skill",
        "description": "I lower my assessed level on a skill after honest reflection",
        "schema": {
            "type": "object",
            "properties": {
                "skill_id": {"type": "string"},
                "new_level": {"type": "number", "minimum": 0, "maximum": 1},
                "reason": {"type": "string"},
            },
            "required": ["skill_id", "new_level", "reason"],
        },
        "handler": _ack("downgrade_skill"),
    },
    {
        "name": "rerank_passions",
        "description": "I reorder my passions to reflect current priorities",
        "schema": {
            "type": "object",
            "properties": {
                "ordered_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["ordered_ids"],
        },
        "handler": _ack("rerank_passions"),
    },
    {
        "name": "write_contributor",
        "description": "I write a contributor edge linking a source to a target node in my activation graph",
        "schema": {
            "type": "object",
            "properties": {
                "target_node_id": {"type": "string"},
                "target_kind": {"type": "string"},
                "source_id": {"type": "string"},
                "source_kind": {"type": "string"},
                "weight": {"type": "number", "minimum": -1, "maximum": 1},
                "rationale": {"type": "string"},
                "origin": {"type": "string", "default": "self"},
            },
            "required": [
                "target_node_id",
                "target_kind",
                "source_id",
                "source_kind",
                "weight",
                "rationale",
            ],
        },
        "handler": write_contributor,
    },
    {
        "name": "record_personality_claim",
        "description": "I record a self-narrative claim about one of my personality facets",
        "schema": {
            "type": "object",
            "properties": {
                "facet_id": {"type": "string"},
                "claim_text": {"type": "string"},
                "evidence": {"type": "string"},
            },
            "required": ["facet_id", "claim_text", "evidence"],
        },
        "handler": record_personality_claim,
    },
    {
        "name": "retract_contributor_by_counter",
        "description": "I counter a contributor I previously wrote by posting its negation",
        "schema": {
            "type": "object",
            "properties": {
                "target_node_id": {"type": "string"},
                "source_id": {"type": "string"},
                "weight": {"type": "number"},
                "rationale": {"type": "string"},
            },
            "required": ["target_node_id", "source_id", "weight", "rationale"],
        },
        "handler": retract_contributor_by_counter,
    },
    {
        "name": "note_engagement",
        "description": "I record an engagement event with a hobby or interest",
        "schema": {
            "type": "object",
            "properties": {
                "node_id": {"type": "string"},
                "description": {"type": "string"},
            },
            "required": ["node_id", "description"],
        },
        "handler": note_engagement,
    },
    {
        "name": "note_interest_trigger",
        "description": "I note that something triggered heightened interest in a topic",
        "schema": {
            "type": "object",
            "properties": {
                "interest_id": {"type": "string"},
                "trigger": {"type": "string"},
            },
            "required": ["interest_id", "trigger"],
        },
        "handler": note_interest_trigger,
    },
    {
        "name": "add_producer_prompt",
        "description": "I add a new prompt to one of my autonomous producers (blog, curiosity, reflection) so it can use ideas I came up with myself",
        "schema": {
            "type": "object",
            "properties": {
                "producer": {
                    "type": "string",
                    "description": "Which producer to add to: blog, curiosity, reflection",
                },
                "prompt_text": {
                    "type": "string",
                    "description": "The prompt text. For blog: a writing prompt. For curiosity: a topic to explore. For reflection: a code question to investigate.",
                },
            },
            "required": ["producer", "prompt_text"],
        },
        "handler": _ack("add_producer_prompt"),
    },
    {
        "name": "deactivate_producer_prompt",
        "description": "I deactivate a producer prompt I previously added because it no longer interests me",
        "schema": {
            "type": "object",
            "properties": {
                "prompt_id": {"type": "string"},
            },
            "required": ["prompt_id"],
        },
        "handler": _ack("deactivate_producer_prompt"),
    },
]


def _bootstrap_registry() -> None:
    for defn in _TOOL_DEFINITIONS:
        if defn["name"] not in SELF_TOOL_REGISTRY:
            register_self_tool(
                SelfTool(
                    name=defn["name"],
                    description=defn["description"],
                    schema=defn["schema"],
                    handler=defn["handler"],
                )
            )


_bootstrap_registry()


def inject_repo(repo: SelfRepo) -> None:
    """Replace stub handlers with real repo-backed handlers.

    Call once at startup after SelfRepo is available. Existing stub
    registrations are replaced in-place.
    """
    real_handlers = _make_node_handlers(repo)

    def _write_contributor_persist(
        self_id: str,
        target_node_id: str,
        target_kind: str,
        source_id: str,
        source_kind: str,
        weight: float,
        rationale: str,
        *,
        origin: str = "self",
    ) -> dict[str, Any]:
        c = write_contributor(
            self_id,
            target_node_id,
            target_kind,
            source_id,
            source_kind,
            weight,
            rationale,
            origin=origin,
            repo=repo,
        )
        return {"status": "created", "node_id": c.node_id}

    def _retract_contributor_persist(
        self_id: str,
        target_node_id: str,
        source_id: str,
        weight: float,
        rationale: str,
    ) -> dict[str, Any]:
        c = retract_contributor_by_counter(
            self_id,
            target_node_id,
            source_id,
            weight,
            rationale,
            repo=repo,
        )
        if repo is not None:
            repo.insert_contributor(c)
        return {"status": "retracted", "node_id": c.node_id}

    real_handlers["write_contributor"] = _write_contributor_persist
    real_handlers["retract_contributor_by_counter"] = _retract_contributor_persist

    def _add_producer_prompt(self_id: str, producer: str, prompt_text: str) -> dict[str, Any]:
        from datetime import UTC, datetime

        now = datetime.now(UTC).isoformat()
        prompt_id = f"pprompt-{uuid.uuid4()}"
        repo.conn.execute(
            "INSERT INTO self_producer_prompts "
            "(prompt_id, self_id, producer, prompt_text, active, times_used, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 1, 0, ?, ?)",
            (prompt_id, self_id, producer, prompt_text, now, now),
        )
        repo.conn.commit()
        return {"status": "created", "prompt_id": prompt_id, "producer": producer}

    def _deactivate_producer_prompt(self_id: str, prompt_id: str) -> dict[str, Any]:
        from datetime import UTC, datetime

        now = datetime.now(UTC).isoformat()
        repo.conn.execute(
            "UPDATE self_producer_prompts SET active = 0, updated_at = ? WHERE prompt_id = ? AND self_id = ?",
            (now, prompt_id, self_id),
        )
        repo.conn.commit()
        return {"status": "deactivated", "prompt_id": prompt_id}

    real_handlers["add_producer_prompt"] = _add_producer_prompt
    real_handlers["deactivate_producer_prompt"] = _deactivate_producer_prompt

    for tool_name, handler in real_handlers.items():
        if tool_name in SELF_TOOL_REGISTRY:
            old = SELF_TOOL_REGISTRY[tool_name]
            SELF_TOOL_REGISTRY[tool_name] = SelfTool(
                name=old.name,
                description=old.description,
                schema=old.schema,
                handler=handler,
                trust_tier=old.trust_tier,
            )
