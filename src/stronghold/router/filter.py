"""Model filtering: modality, tier, quota, active status."""

from __future__ import annotations

from typing import TYPE_CHECKING

from stronghold.types.intent import TIER_ORDER

if TYPE_CHECKING:
    from stronghold.types.intent import Intent
    from stronghold.types.model import ModelConfig, ProviderConfig


def filter_candidates(
    intent: Intent,
    models: dict[str, ModelConfig],
    providers: dict[str, ProviderConfig],
    *,
    usage_pcts: dict[str, float] | None = None,
    reserve_pct: float = 0.05,
) -> list[tuple[str, ModelConfig, ProviderConfig, float]]:
    """Filter models by modality, tier, quota, and active status.

    Returns list of (model_id, model_config, provider_config, usage_pct) tuples.
    """
    if usage_pcts is None:
        usage_pcts = {}

    result: list[tuple[str, ModelConfig, ProviderConfig, float]] = []

    for model_id, model_cfg in models.items():
        provider_name = model_cfg.provider
        provider_cfg = providers.get(provider_name)
        if provider_cfg is None:
            continue

        # Skip inactive providers
        if provider_cfg.status != "active":
            continue

        # Filter by modality
        model_modality = model_cfg.modality
        task_type = intent.task_type
        if task_type == "image_gen" and model_modality != "image_gen":
            continue
        if task_type == "embedding" and model_modality != "embedding":
            continue
        if task_type not in ("image_gen", "embedding") and model_modality in (
            "image_gen",
            "embedding",
        ):
            continue

        # Filter by tier (min and max)
        model_tier = model_cfg.tier
        if TIER_ORDER.get(model_tier, 0) < TIER_ORDER.get(intent.min_tier, 0):
            continue
        if intent.max_tier and TIER_ORDER.get(model_tier, 0) > TIER_ORDER.get(intent.max_tier, 99):
            continue

        # Get usage
        usage_pct = usage_pcts.get(provider_name, 0.0)

        # Check pay-as-you-go
        has_paygo = (
            provider_cfg.overage_cost_per_1k_input > 0
            or provider_cfg.overage_cost_per_1k_output > 0
        )

        # Hard block if over 100% and no paygo
        if usage_pct >= 1.0 and not has_paygo:
            continue

        # Reserve enforcement — block non-critical when in reserve zone OR over quota with paygo
        if usage_pct >= (1.0 - reserve_pct) and intent.tier != "P0" and not has_paygo:
            continue

        result.append((model_id, model_cfg, provider_cfg, usage_pct))

    return result
