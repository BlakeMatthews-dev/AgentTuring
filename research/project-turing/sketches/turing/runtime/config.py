"""RuntimeConfig: CLI flags → env vars → YAML → defaults.

Pydantic-free. Stdlib dataclass + manual validation. Keeps deps minimal.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RuntimeConfig:
    # Reactor
    tick_rate_hz: int = 100
    executor_workers: int = 8

    # Storage
    db_path: str = ":memory:"
    journal_dir: str | None = None

    # Logging / observability
    log_level: str = "INFO"
    log_format: str = "plain"  # "plain" | "json"
    metrics_port: int | None = None
    metrics_bind: str = "127.0.0.1"

    # Providers — single LiteLLM endpoint, virtual key, pools config.
    use_fake_provider: bool = True
    litellm_base_url: str | None = None
    litellm_virtual_key: str | None = None
    pools_config_path: str | None = None

    # Workload (chunk 3)
    scenario: str | None = None

    # Tools (outward-facing)
    obsidian_vault_dir: str | None = None
    rss_feeds: tuple[str, ...] = ()
    wordpress_site_url: str | None = None
    wordpress_username: str | None = None
    wordpress_app_password: str | None = None

    # Chat HTTP
    chat_port: int | None = None
    chat_bind: str = "127.0.0.1"

    # Operator-controlled base prompt. Read once at startup; never mutated
    # by the self. Working memory (self-controlled) is composed alongside
    # this in every chat prompt.
    base_prompt_path: str | None = None

    # Stronghold integration — delegate work to the agent governance platform.
    stronghold_base_url: str | None = None
    stronghold_api_key: str | None = None

    # Voice section — the self-owned text block Turing writes to describe
    # how it sounds. Starts empty by default; populated over time by the
    # voice-section-maintenance loop.
    # - voice_section_path: operator seed file (optional; overrides the DB
    #   value only on the very first boot if the DB row is empty).
    # - voice_self_edit_enabled: gates the maintenance loop.
    # - voice_section_max_chars: hard cap on the content length.
    # - voice_maintenance_ticks: how often the maintenance loop fires.
    voice_section_path: str | None = None
    voice_self_edit_enabled: bool = True
    voice_section_max_chars: int = 600
    voice_maintenance_ticks: int = 50_000

    # Embedding
    skip_embedding_rebuild: bool = False

    # Self identity
    self_label: str = "default"

    def validate(self) -> None:
        if self.tick_rate_hz <= 0:
            raise ValueError("tick_rate_hz must be positive")
        if self.executor_workers <= 0:
            raise ValueError("executor_workers must be positive")
        if self.log_level not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
            raise ValueError(f"invalid log_level: {self.log_level}")
        if self.log_format not in {"plain", "json"}:
            raise ValueError(f"invalid log_format: {self.log_format}")
        if not self.use_fake_provider:
            if not self.litellm_base_url:
                raise ValueError("litellm_base_url required when use_fake_provider is false")
            if not self.litellm_virtual_key:
                raise ValueError("litellm_virtual_key required when use_fake_provider is false")
            if not self.pools_config_path:
                raise ValueError("pools_config_path required when use_fake_provider is false")


def _parse_bool(value: str) -> bool:
    return value.lower() in {"1", "true", "yes", "on"}


def _parse_int(value: str, default: int) -> int:
    try:
        return int(value)
    except ValueError:
        return default


def load_config_from_env(
    overrides: dict[str, Any] | None = None,
) -> RuntimeConfig:
    """Load config in precedence order: overrides → env vars → defaults."""
    env = os.environ
    cfg_kwargs: dict[str, Any] = {}

    if "TURING_TICK_RATE_HZ" in env:
        cfg_kwargs["tick_rate_hz"] = _parse_int(env["TURING_TICK_RATE_HZ"], 100)
    if "TURING_EXECUTOR_WORKERS" in env:
        cfg_kwargs["executor_workers"] = _parse_int(env["TURING_EXECUTOR_WORKERS"], 8)
    if "TURING_DB_PATH" in env:
        cfg_kwargs["db_path"] = env["TURING_DB_PATH"]
    if "TURING_JOURNAL_DIR" in env:
        cfg_kwargs["journal_dir"] = env["TURING_JOURNAL_DIR"]
    if "TURING_LOG_LEVEL" in env:
        cfg_kwargs["log_level"] = env["TURING_LOG_LEVEL"].upper()
    if "TURING_LOG_FORMAT" in env:
        cfg_kwargs["log_format"] = env["TURING_LOG_FORMAT"]
    if "TURING_METRICS_PORT" in env:
        cfg_kwargs["metrics_port"] = _parse_int(env["TURING_METRICS_PORT"], 0) or None
    if "TURING_METRICS_BIND" in env:
        cfg_kwargs["metrics_bind"] = env["TURING_METRICS_BIND"]
    if "TURING_USE_FAKE_PROVIDER" in env:
        cfg_kwargs["use_fake_provider"] = _parse_bool(env["TURING_USE_FAKE_PROVIDER"])
    if "LITELLM_BASE_URL" in env:
        cfg_kwargs["litellm_base_url"] = env["LITELLM_BASE_URL"]
    if "LITELLM_VIRTUAL_KEY" in env:
        cfg_kwargs["litellm_virtual_key"] = env["LITELLM_VIRTUAL_KEY"]
    if "TURING_POOLS_CONFIG" in env:
        cfg_kwargs["pools_config_path"] = env["TURING_POOLS_CONFIG"]
    if "TURING_SCENARIO" in env:
        cfg_kwargs["scenario"] = env["TURING_SCENARIO"]
    if "TURING_OBSIDIAN_VAULT" in env:
        cfg_kwargs["obsidian_vault_dir"] = env["TURING_OBSIDIAN_VAULT"]
    if "TURING_RSS_FEEDS" in env:
        cfg_kwargs["rss_feeds"] = tuple(
            f.strip() for f in env["TURING_RSS_FEEDS"].split(",") if f.strip()
        )
    if "TURING_WORDPRESS_SITE_URL" in env:
        cfg_kwargs["wordpress_site_url"] = env["TURING_WORDPRESS_SITE_URL"]
    if "TURING_WORDPRESS_USERNAME" in env:
        cfg_kwargs["wordpress_username"] = env["TURING_WORDPRESS_USERNAME"]
    if "TURING_WORDPRESS_APP_PASSWORD" in env:
        cfg_kwargs["wordpress_app_password"] = env["TURING_WORDPRESS_APP_PASSWORD"]
    if "TURING_CHAT_PORT" in env:
        cfg_kwargs["chat_port"] = _parse_int(env["TURING_CHAT_PORT"], 0) or None
    if "TURING_CHAT_BIND" in env:
        cfg_kwargs["chat_bind"] = env["TURING_CHAT_BIND"]
    if "TURING_BASE_PROMPT_PATH" in env:
        cfg_kwargs["base_prompt_path"] = env["TURING_BASE_PROMPT_PATH"]
    if "STRONGHOLD_BASE_URL" in env:
        cfg_kwargs["stronghold_base_url"] = env["STRONGHOLD_BASE_URL"]
    if "STRONGHOLD_API_KEY" in env:
        cfg_kwargs["stronghold_api_key"] = env["STRONGHOLD_API_KEY"]
    if "TURING_VOICE_SECTION_PATH" in env:
        cfg_kwargs["voice_section_path"] = env["TURING_VOICE_SECTION_PATH"]
    if "TURING_VOICE_SELF_EDIT_ENABLED" in env:
        cfg_kwargs["voice_self_edit_enabled"] = _parse_bool(env["TURING_VOICE_SELF_EDIT_ENABLED"])
    if "TURING_VOICE_SECTION_MAX_CHARS" in env:
        cfg_kwargs["voice_section_max_chars"] = _parse_int(
            env["TURING_VOICE_SECTION_MAX_CHARS"], 600
        )
    if "TURING_VOICE_MAINTENANCE_TICKS" in env:
        cfg_kwargs["voice_maintenance_ticks"] = _parse_int(
            env["TURING_VOICE_MAINTENANCE_TICKS"], 50_000
        )
    if "TURING_SELF_LABEL" in env:
        cfg_kwargs["self_label"] = env["TURING_SELF_LABEL"]
    if "TURING_SKIP_EMBEDDING_REBUILD" in env:
        cfg_kwargs["skip_embedding_rebuild"] = _parse_bool(env["TURING_SKIP_EMBEDDING_REBUILD"])

    cfg = RuntimeConfig(**cfg_kwargs)
    if overrides:
        cfg = replace(cfg, **overrides)
    cfg.validate()
    return cfg
