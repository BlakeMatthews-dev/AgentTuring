"""Security types: Warden verdicts, Sentinel verdicts, audit entries, trust tiers.

Warden detects threats (two ingress points: user input + tool results).
Sentinel enforces policy (every boundary crossing).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class TrustTier(StrEnum):
    """Trust tiers for agents and skills.

    Promotion requires passing review gates. Provenance caps apply:
    community-origin agents can never exceed T3 regardless of reviews.

    Tier  | Path                                      | Reviews
    ------+-------------------------------------------+---------------------------
    T0    | Built-in (shipped with Stronghold)         | Code-reviewed, hardcoded
    T1    | Admin-created + AI security review         | Admin + Warden
    T2    | Admin-created (no review yet)              | Admin trust alone
          | OR User-created + AI review + admin review | User + Warden + Admin
    T3    | User-created + AI review                   | User + Warden
          | OR Community + user + AI + admin (CAPPED)  | All 4 gates, max for ext.
    T4    | User-created (no review)                   | Starting point
          | OR Community + user review + AI review     | 2 gates, no admin yet
    Skull | Community + raw user import                | Trust nothing
    """

    SKULL = "skull"  # Community import, no reviews, trust nothing
    T4 = "t4"  # User-created (no review) / community with user+AI review
    T3 = "t3"  # User + AI review / community capped here
    T2 = "t2"  # Admin-created / user + AI + admin review
    T1 = "t1"  # Admin-created + AI security review
    T0 = "t0"  # Built-in, shipped with Stronghold


class Provenance(StrEnum):
    """Origin of an agent or skill. Permanent — never changes after creation."""

    BUILTIN = "builtin"  # Shipped with Stronghold
    ADMIN = "admin"  # Created by an org admin
    USER = "user"  # Created by an approved user
    COMMUNITY = "community"  # Imported from external URL/marketplace


@dataclass(frozen=True)
class WardenVerdict:
    """Result of Warden threat detection scan."""

    clean: bool = True
    sanitized_content: str | None = None
    blocked: bool = False
    flags: tuple[str, ...] = ()
    confidence: float = 1.0


@dataclass(frozen=True)
class Violation:
    """A single policy violation detected by Sentinel."""

    boundary: str
    rule: str
    severity: str = "error"  # error, warning, info
    detail: str = ""
    repair_action: str | None = None


@dataclass(frozen=True)
class SentinelVerdict:
    """Result of Sentinel policy check."""

    allowed: bool = True
    repaired: bool = False
    repaired_data: Any = None
    violations: tuple[Violation, ...] = ()


@dataclass(frozen=True)
class AuditEntry:
    """A single audit log entry — every boundary crossing is logged."""

    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    boundary: str = ""
    user_id: str = ""
    org_id: str = ""
    team_id: str = ""
    agent_id: str = ""
    tool_name: str | None = None
    verdict: str = "allowed"
    violations: tuple[Violation, ...] = ()
    trace_id: str = ""
    request_id: str = ""
    detail: str = ""


@dataclass(frozen=True)
class GateResult:
    """Result of Gate input processing."""

    sanitized_text: str = ""
    improved_text: str | None = None
    clarifying_questions: tuple[ClarifyingQuestion, ...] = ()
    warden_verdict: WardenVerdict = field(default_factory=WardenVerdict)
    blocked: bool = False
    block_reason: str = ""
    # Strike escalation data (populated when blocked)
    strike_number: int = 0  # Current strike count after this violation
    scrutiny_level: str = "normal"  # normal | elevated | locked | disabled
    locked_until: str = ""  # ISO timestamp if locked
    account_disabled: bool = False


@dataclass(frozen=True)
class ClarifyingQuestion:
    """A question the Gate asks to improve the user's request."""

    question: str = ""
    options: tuple[str, ...] = ()  # a, b, c, d options
    allow_freetext: bool = True
