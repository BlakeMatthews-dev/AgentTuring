"""Model routing types.

Represents model configurations, provider configurations, scored candidates,
and the final model selection result. Used by the router and the API layer.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderConfig:
    """Configuration for an LLM provider."""

    status: str = "active"
    billing_cycle: str = "monthly"
    free_tokens: int = 0
    overage_cost_per_1k_input: float = 0.0
    overage_cost_per_1k_output: float = 0.0
    data_sharing: bool = False
    data_sharing_notice: str = ""


@dataclass(frozen=True)
class ModelConfig:
    """Configuration for a single LLM model."""

    provider: str = ""
    litellm_id: str = ""
    tier: str = "small"
    quality: float = 0.5
    speed: int = 100
    modality: str = "text"
    strengths: tuple[str, ...] = ()
    context_window: int = 8192


@dataclass(frozen=True)
class ModelCandidate:
    """A scored model candidate during routing."""

    model_id: str
    litellm_id: str
    provider: str
    score: float
    quality: float
    effective_cost: float
    usage_pct: float
    tier: str
    has_paygo: bool = False


@dataclass(frozen=True)
class ModelSelection:
    """The result of model selection — the chosen model plus all candidates."""

    model_id: str
    litellm_id: str
    provider: str
    score: float
    reason: str
    candidates: tuple[ModelCandidate, ...] = ()
