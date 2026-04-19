"""Pool configuration: each pool is a (LiteLLM model, free-tier window).

The operator already runs LiteLLM with their providers wired (Google, z.ai,
OpenRouter, …). Project Turing consumes that proxy through a single virtual
key and treats each *model* operators want it to use as its own pool — with
its own quota window, its own quality weight, and its own pressure scalar.

Pools live in `pools.yaml` (path via `TURING_POOLS_CONFIG`). Example:

    pools:
      - pool_name: gemini-flash
        model: gemini/gemini-2.0-flash-exp
        window_kind: rpm
        window_duration_seconds: 60
        tokens_allowed: 1_000_000
        quality_weight: 0.7
      - pool_name: glm-4-flash
        model: openai/glm-4-flash       # operator's LiteLLM may expose GLM
        window_kind: rolling_hours      # via the openai-compatible adapter
        window_duration_seconds: 18000
        tokens_allowed: 5_000_000
        quality_weight: 0.9
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


VALID_WINDOW_KINDS: set[str] = {"rpm", "daily", "monthly", "rolling_hours"}


@dataclass(frozen=True)
class PoolConfig:
    pool_name: str
    model: str
    window_kind: str
    window_duration_seconds: int
    tokens_allowed: int
    quality_weight: float = 1.0

    def __post_init__(self) -> None:
        if not self.pool_name:
            raise ValueError("pool_name required")
        if not self.model:
            raise ValueError("model required")
        if self.window_kind not in VALID_WINDOW_KINDS:
            raise ValueError(
                f"window_kind must be one of {sorted(VALID_WINDOW_KINDS)}; "
                f"got {self.window_kind!r}"
            )
        if self.window_duration_seconds <= 0:
            raise ValueError("window_duration_seconds must be positive")
        if self.tokens_allowed <= 0:
            raise ValueError("tokens_allowed must be positive")
        if not 0.0 < self.quality_weight <= 10.0:
            raise ValueError("quality_weight must be in (0, 10]")


def load_pools(path: str | Path) -> list[PoolConfig]:
    raw = yaml.safe_load(Path(path).read_text())
    if not isinstance(raw, dict) or "pools" not in raw:
        raise ValueError(f"pools config must contain a top-level 'pools' list: {path}")
    return [
        PoolConfig(
            pool_name=str(p["pool_name"]),
            model=str(p["model"]),
            window_kind=str(p["window_kind"]),
            window_duration_seconds=int(p["window_duration_seconds"]),
            tokens_allowed=int(p["tokens_allowed"]),
            quality_weight=float(p.get("quality_weight", 1.0)),
        )
        for p in raw["pools"]
    ]
