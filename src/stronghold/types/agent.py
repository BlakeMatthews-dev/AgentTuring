"""Agent types: identity, tasks, execution modes, results."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal


class ExecutionMode(StrEnum):
    """How much effort to put into a request."""

    BEST_EFFORT = "best_effort"
    PERSISTENT = "persistent"
    SUPERVISED = "supervised"


@dataclass(frozen=True)
class AgentIdentity:
    """Everything that defines an agent. Loaded from agent.yaml."""

    name: str
    version: str = "1.0.0"
    description: str = ""
    soul_prompt_name: str = ""
    model: str = "auto"
    model_fallbacks: tuple[str, ...] = ()
    model_constraints: dict[str, Any] = field(default_factory=dict)
    tools: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    rules: tuple[str, ...] = ()
    trust_tier: str = "t4"
    priority_tier: Literal["P0", "P1", "P2", "P3", "P4", "P5"] = "P2"
    max_tool_rounds: int = 3
    delegation_mode: str = "none"
    sub_agents: tuple[str, ...] = ()
    reasoning_strategy: str = "direct"
    memory_config: dict[str, Any] = field(default_factory=dict)
    phases: tuple[dict[str, Any], ...] = ()
    org_id: str = ""

    # Trust & review tracking
    provenance: str = "user"  # builtin / admin / user / community
    ai_reviewed: bool = False
    ai_review_clean: bool = False
    admin_reviewed: bool = False
    admin_reviewed_by: str = ""
    user_reviewed: bool = False
    active: bool = True


@dataclass(frozen=True)
class AgentTask:
    """A2A-shaped task for inter-agent delegation."""

    id: str
    from_agent: str
    to_agent: str
    messages: tuple[dict[str, str], ...] = ()
    execution_mode: ExecutionMode = ExecutionMode.BEST_EFFORT
    token_budget: float | None = None
    status: str = "submitted"
    result: str | None = None
    trace_id: str = ""


@dataclass
class ReasoningResult:
    """What an agent's reasoning strategy decided to do."""

    response: str | None = None
    tool_calls: list[Any] = field(default_factory=list)
    delegate_to: str | None = None
    delegate_message: str | None = None
    request_input: str | None = None
    done: bool = True
    reasoning_trace: str = ""
    tool_history: list[dict[str, Any]] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class AgentResponse:
    """The response from Agent.handle()."""

    content: str = ""
    trace_id: str = ""
    model_used: str = ""
    agent_name: str = ""
    intent_task_type: str = ""
    tool_calls_made: int = 0
    learnings_extracted: int = 0
    blocked: bool = False
    block_reason: str = ""

    @classmethod
    def blocked_response(cls, reason: str) -> AgentResponse:
        """Create a blocked response."""
        return cls(blocked=True, block_reason=reason)
