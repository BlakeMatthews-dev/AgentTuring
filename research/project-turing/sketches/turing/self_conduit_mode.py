"""Conduit-mode configuration shim. See specs/conduit-mode-shim.md."""

from __future__ import annotations

import os


class ConfigError(Exception):
    pass


class StartupError(Exception):
    pass


VALID_MODES = frozenset({"stateless", "self"})
DEFAULT_MODE = "stateless"


def resolve_conduit_mode(yaml_mode: str | None = None) -> str:
    env_mode = os.environ.get("TURING_CONDUIT_MODE", "").strip()
    mode = env_mode or yaml_mode or DEFAULT_MODE
    if mode not in VALID_MODES:
        raise ConfigError(f"invalid conduit_mode: {mode!r}")
    return mode


def verify_self_ready(repo, srepo) -> str:
    rows = repo.conn.execute(
        "SELECT self_id FROM self_identity WHERE archived_at IS NULL"
    ).fetchall()
    if not rows:
        raise StartupError("self mode selected but no bootstrapped self found")
    sid = rows[0][0]
    from .self_surface import _bootstrap_complete

    if not _bootstrap_complete(srepo, sid):
        raise StartupError(f"self {sid} is not fully bootstrapped")
    return sid
