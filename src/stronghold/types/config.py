"""Stronghold configuration types.

Pydantic-validated config loaded from YAML. Replaces the raw dict
chains in Conductor (config.get("models", {}).get(model_id, {}).get("quality", 0.5)).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RoutingConfig(BaseModel):
    """Model routing parameters."""

    quality_weight: float = 0.6
    cost_weight: float = 0.4
    reserve_pct: float = 0.05
    priority_multipliers: dict[str, float] = Field(
        default_factory=lambda: {
            "P0": 1.5,
            "P1": 1.2,
            "P2": 1.0,
            "P3": 0.9,
            "P4": 0.8,
            "P5": 0.7,
        }
    )


class TaskTypeConfig(BaseModel):
    """Configuration for a single task type."""

    keywords: list[str] = Field(default_factory=list)
    min_tier: str = "small"
    preferred_strengths: list[str] = Field(default_factory=lambda: ["chat"])


class SessionsConfig(BaseModel):
    """Session memory configuration."""

    max_messages: int = 20
    ttl_seconds: int = 86400


class SecurityConfig(BaseModel):
    """Security configuration."""

    warden_enabled: bool = True
    sentinel_enabled: bool = True
    gate_query_improve: bool = True
    gate_model: str = "auto"


class CORSConfig(BaseModel):
    """CORS configuration for browser-based clients (OpenWebUI, dashboard)."""

    allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3200"])
    allowed_methods: list[str] = Field(
        default_factory=lambda: ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
    )
    allowed_headers: list[str] = Field(
        default_factory=lambda: [
            "Authorization",
            "Content-Type",
            "X-OpenWebUI-User-Email",
            "X-OpenWebUI-User-Name",
            "X-OpenWebUI-User-Id",
            "X-OpenWebUI-User-Role",
        ]
    )
    allow_credentials: bool = True


class RateLimitConfig(BaseModel):
    """Per-user rate limiting configuration."""

    requests_per_minute: int = 300
    burst_limit: int = 50
    enabled: bool = True


class AuthConfig(BaseModel):
    """Authentication provider configuration."""

    jwks_url: str = ""
    issuer: str = ""
    audience: str = ""
    client_id: str = ""  # OIDC client ID for frontend login
    client_secret: str = ""  # OIDC client secret (BFF confidential client)
    authorization_url: str = ""  # OIDC authorization endpoint
    token_url: str = ""  # OIDC token endpoint (for server-side code exchange)
    session_cookie_name: str = "stronghold_session"
    session_max_age: int = 3600  # Cookie max-age in seconds
    allowed_registration_orgs: list[str] = Field(default_factory=list)  # Empty = deny all self-reg


class StrongholdConfig(BaseModel):
    """Root configuration for Stronghold. Validated at startup."""

    providers: dict[str, dict[str, object]] = Field(default_factory=dict)
    models: dict[str, dict[str, object]] = Field(default_factory=dict)
    task_types: dict[str, TaskTypeConfig] = Field(default_factory=dict)
    routing: RoutingConfig = Field(default_factory=RoutingConfig)
    sessions: SessionsConfig = Field(default_factory=SessionsConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    cors: CORSConfig = Field(default_factory=CORSConfig)
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    model_groups: dict[str, dict[str, object]] = Field(default_factory=dict)
    permissions: dict[str, list[str]] = Field(default_factory=dict)
    database_url: str = ""
    redis_url: str = ""  # redis://host:6379/0 — distributed sessions + rate limiting
    agents_dir: str = ""  # Path to GitAgent seed directory. Default: auto-detected from package.
    litellm_url: str = "http://litellm:4000"
    litellm_key: str = ""
    router_api_key: str = ""
    jwt_secret: str = ""
    phoenix_endpoint: str = ""

    cors_origins: list[str] = Field(default_factory=list)
    max_request_body_bytes: int = 1_048_576  # 1 MB
    webhook_secret: str = ""
    cache_breakpoints_enabled: bool = False
