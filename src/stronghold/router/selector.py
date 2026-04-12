"""Router engine: filter → score → rank → fallback."""

from __future__ import annotations

from typing import TYPE_CHECKING

from stronghold.router.filter import filter_candidates
from stronghold.router.scorer import score_candidate
from stronghold.types.errors import NoModelsError, QuotaReserveError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from stronghold.protocols.quota import QuotaTracker
    from stronghold.types.config import RoutingConfig
    from stronghold.types.intent import Intent
    from stronghold.types.model import ModelConfig, ModelSelection, ProviderConfig


class RouterEngine:
    """Implements ModelRouter protocol. Selects the best model for an intent."""

    def __init__(self, quota_tracker: QuotaTracker) -> None:
        self._quota = quota_tracker

    def select(
        self,
        intent: Intent,
        models: dict[str, ModelConfig],
        providers: dict[str, ProviderConfig],
        routing_config: RoutingConfig,
    ) -> ModelSelection:
        """Select the best model. Synchronous — uses cached quota data."""
        return self.select_with_usage(intent, models, providers, routing_config, {})

    def select_with_usage(
        self,
        intent: Intent,
        models: dict[str, ModelConfig],
        providers: dict[str, ProviderConfig],
        routing_config: RoutingConfig,
        usage_pcts: dict[str, float],
    ) -> ModelSelection:
        """Select the best model with pre-fetched usage data."""
        from stronghold.types.model import ModelSelection

        reserve_pct = routing_config.reserve_pct

        filtered = filter_candidates(
            intent,
            models,
            providers,
            usage_pcts=usage_pcts,
            reserve_pct=reserve_pct,
        )

        if not filtered:
            # Check if everything was filtered by reserve
            # Try again without reserve to see if models exist
            all_candidates = filter_candidates(
                intent,
                models,
                providers,
                usage_pcts=usage_pcts,
                reserve_pct=0.0,
            )
            if all_candidates:
                raise QuotaReserveError(
                    f"All {len(all_candidates)} eligible models are in quota reserve. "
                    "Use tier=P0 to override."
                )
            # Absolute fallback — highest quality active model
            return self._fallback(models, providers)

        # Score each candidate
        candidates = [
            score_candidate(
                model_id,
                model_cfg,
                provider_cfg,
                intent,
                routing_config,
                usage_pct,
            )
            for model_id, model_cfg, provider_cfg, usage_pct in filtered
        ]

        # Sort by score descending
        candidates.sort(key=lambda c: c.score, reverse=True)
        best = candidates[0]

        return ModelSelection(
            model_id=best.model_id,
            litellm_id=best.litellm_id,
            provider=best.provider,
            score=best.score,
            reason=self._build_reason(best, intent, candidates),
            candidates=tuple(candidates),
        )

    def _fallback(
        self,
        models: dict[str, ModelConfig],
        providers: dict[str, ProviderConfig],
    ) -> ModelSelection:
        """Fallback: return highest quality active model regardless of filters."""
        from stronghold.types.model import ModelSelection

        best_quality = -1.0
        best_id = ""
        best_cfg: ModelConfig | None = None

        for model_id, model_cfg in models.items():
            prov = providers.get(model_cfg.provider)
            if prov and prov.status == "active" and model_cfg.quality > best_quality:
                best_quality = model_cfg.quality
                best_id = model_id
                best_cfg = model_cfg

        if best_cfg is None:
            raise NoModelsError("No active models available")

        return ModelSelection(
            model_id=best_id,
            litellm_id=best_cfg.litellm_id or best_id,
            provider=best_cfg.provider,
            score=0.0,
            reason="fallback — no models matched filters",
            candidates=(),
        )

    @staticmethod
    def _build_reason(
        best: object,
        intent: Intent,
        candidates: Sequence[object],
    ) -> str:
        """Human-readable explanation of selection."""
        from stronghold.types.model import ModelCandidate

        parts = [
            f"task={intent.task_type}",
            f"complexity={intent.complexity}",
            f"tier={intent.tier}",
        ]
        if isinstance(best, ModelCandidate):
            parts.append(f"quality={best.quality}")
            parts.append(f"quota={best.usage_pct:.0%}")
        if len(candidates) > 1:
            runner_up = candidates[1]
            if isinstance(runner_up, ModelCandidate):
                parts.append(f"runner_up={runner_up.model_id}({runner_up.score})")
        return "; ".join(parts)
