"""Self-tool registry: function-call schema generation, dispatch, and trust-tier gating.

See specs/self-tool-registry.md (Spec 31).
"""

from __future__ import annotations

import json
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
from .self_surface import SelfNotReady

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
