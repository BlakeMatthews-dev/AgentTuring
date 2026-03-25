"""Stronghold error hierarchy.

Every domain-specific error carries a `code` for programmatic handling
and a `detail` for human consumption. Replaces scattered RuntimeError,
HTTPException, and ValueError from Conductor.
"""

from __future__ import annotations


class StrongholdError(Exception):
    """Base error for all Stronghold domain errors."""

    code: str = "STRONGHOLD_ERROR"

    def __init__(self, detail: str = "", *, code: str | None = None) -> None:
        self.detail = detail
        if code is not None:
            self.code = code
        super().__init__(f"[{self.code}] {detail}")


# ── Routing ──────────────────────────────────────────────────────


class RoutingError(StrongholdError):
    """Model routing failure."""

    code = "ROUTING_ERROR"


class QuotaReserveError(RoutingError):
    """All eligible models are in quota reserve."""

    code = "QUOTA_RESERVE_BLOCKED"


class QuotaExhaustedError(RoutingError):
    """All providers are at or above 100% quota usage."""

    code = "QUOTA_EXHAUSTED"


class NoModelsError(RoutingError):
    """No active models available for the request."""

    code = "NO_MODELS_AVAILABLE"


# ── Classification ───────────────────────────────────────────────


class ClassificationError(StrongholdError):
    """Intent classification failure."""

    code = "CLASSIFICATION_ERROR"


# ── Authentication & Authorization ───────────────────────────────


class AuthError(StrongholdError):
    """Authentication or authorization failure."""

    code = "AUTH_ERROR"


class TokenExpiredError(AuthError):
    """JWT token has expired."""

    code = "TOKEN_EXPIRED"


class PermissionDeniedError(AuthError):
    """User lacks permission for the requested action."""

    code = "PERMISSION_DENIED"


# ── Tool Execution ───────────────────────────────────────────────


class ToolError(StrongholdError):
    """Tool execution failure."""

    code = "TOOL_ERROR"


# ── Security ─────────────────────────────────────────────────────


class SecurityError(StrongholdError):
    """Security violation detected."""

    code = "SECURITY_ERROR"


class InjectionError(SecurityError):
    """Prompt injection detected."""

    code = "INJECTION_DETECTED"


class TrustViolationError(SecurityError):
    """Trust tier violation."""

    code = "TRUST_VIOLATION"


# ── Configuration ────────────────────────────────────────────────


class ConfigError(StrongholdError):
    """Configuration validation failure."""

    code = "CONFIG_ERROR"


# ── Skills ───────────────────────────────────────────────────────


class SkillError(StrongholdError):
    """Skill loading, parsing, or forge failure."""

    code = "SKILL_ERROR"
