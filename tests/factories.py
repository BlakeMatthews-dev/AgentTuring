"""Test data factories — builder functions for all types."""

from __future__ import annotations

from stronghold.types.auth import AuthContext, PermissionTable
from stronghold.types.config import RoutingConfig
from stronghold.types.intent import Intent
from stronghold.types.memory import EpisodicMemory, Learning, MemoryScope, MemoryTier
from stronghold.types.model import ModelConfig, ProviderConfig


def build_intent(**overrides: object) -> Intent:
    """Build an Intent with sensible defaults."""
    defaults: dict[str, object] = {
        "task_type": "chat",
        "complexity": "simple",
        "priority": "normal",
        "min_tier": "small",
        "preferred_strengths": ("chat",),
        "classified_by": "keywords",
        "keyword_score": 3.0,
        "user_text": "hello",
    }
    defaults.update(overrides)
    return Intent(**defaults)  # type: ignore[arg-type]


def build_model_config(**overrides: object) -> ModelConfig:
    """Build a ModelConfig with sensible defaults."""
    defaults: dict[str, object] = {
        "provider": "test_provider",
        "litellm_id": "test/model",
        "tier": "medium",
        "quality": 0.6,
        "speed": 500,
        "modality": "text",
        "strengths": ("code",),
    }
    defaults.update(overrides)
    valid = {f.name for f in ModelConfig.__dataclass_fields__.values()}
    return ModelConfig(**{k: v for k, v in defaults.items() if k in valid})  # type: ignore[arg-type]


def build_provider_config(**overrides: object) -> ProviderConfig:
    """Build a ProviderConfig with sensible defaults."""
    defaults: dict[str, object] = {
        "status": "active",
        "billing_cycle": "monthly",
        "free_tokens": 1_000_000_000,
    }
    defaults.update(overrides)
    valid = {f.name for f in ProviderConfig.__dataclass_fields__.values()}
    return ProviderConfig(**{k: v for k, v in defaults.items() if k in valid})  # type: ignore[arg-type]


def build_routing_config(**overrides: object) -> RoutingConfig:
    """Build a RoutingConfig with sensible defaults."""
    defaults: dict[str, object] = {
        "quality_weight": 0.6,
        "cost_weight": 0.4,
        "reserve_pct": 0.05,
    }
    defaults.update(overrides)
    return RoutingConfig(**defaults)  # type: ignore[arg-type]


def build_auth_context(**overrides: object) -> AuthContext:
    """Build an AuthContext with sensible defaults."""
    defaults: dict[str, object] = {
        "user_id": "test-user",
        "username": "tester",
        "roles": frozenset({"admin", "user"}),
        "auth_method": "api_key",
    }
    defaults.update(overrides)
    return AuthContext(**defaults)  # type: ignore[arg-type]


def build_learning(**overrides: object) -> Learning:
    """Build a Learning with sensible defaults."""
    defaults: dict[str, object] = {
        "category": "tool_correction",
        "trigger_keys": ["fan", "bedroom"],
        "learning": "entity_id for the fan is fan.bedroom_lamp",
        "tool_name": "ha_control",
        "agent_id": "warden-at-arms",
        "scope": MemoryScope.AGENT,
    }
    defaults.update(overrides)
    return Learning(**defaults)  # type: ignore[arg-type]


def build_episodic_memory(**overrides: object) -> EpisodicMemory:
    """Build an EpisodicMemory with sensible defaults."""
    defaults: dict[str, object] = {
        "memory_id": "test-memory-001",
        "tier": MemoryTier.LESSON,
        "content": "Schema injection improves parse rate for HA commands",
        "weight": 0.6,
        "agent_id": "warden-at-arms",
        "scope": MemoryScope.AGENT,
        "source": "test",
    }
    defaults.update(overrides)
    return EpisodicMemory(**defaults)  # type: ignore[arg-type]


def build_permission_table(**overrides: object) -> PermissionTable:
    """Build a PermissionTable with sensible defaults."""
    defaults: dict[str, object] = {
        "roles": {
            "admin": {"*"},
            "engineer": {"web_search", "file_ops", "shell"},
            "viewer": {"web_search"},
        },
    }
    defaults.update(overrides)
    return PermissionTable(**defaults)  # type: ignore[arg-type]
