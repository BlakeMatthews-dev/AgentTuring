"""Session types: messages and configuration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SessionMessage:
    """A single message in a session."""

    role: str
    content: str


@dataclass(frozen=True)
class SessionConfig:
    """Session memory configuration."""

    max_messages: int = 20
    ttl_seconds: int = 86400  # 24 hours
