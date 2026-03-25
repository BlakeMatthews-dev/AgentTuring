"""Scarcity-based effective cost computation.

Cost = 1 / ln(remaining_daily_tokens)

Providers with larger budgets are naturally cheaper.
Cost rises smoothly as tokens get consumed — no cliffs.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stronghold.types.model import ProviderConfig


def _daily_budget(provider: ProviderConfig) -> float:
    """Normalize free_tokens to a daily budget regardless of billing cycle."""
    free_tokens = provider.free_tokens
    if provider.billing_cycle == "daily":
        return float(free_tokens)
    # Monthly: divide by 30 for daily budget
    return float(free_tokens) / 30.0


def compute_effective_cost(usage_pct: float, provider: ProviderConfig) -> float:
    """Compute effective cost based on token scarcity.

    cost = 1 / ln(remaining_daily_tokens)

    - Providers with large budgets are naturally cheap
    - Cost rises smoothly as tokens deplete
    - Over quota without paygo: 999.0
    - Over quota with paygo: average overage rate
    - Zero free tokens: 1.0
    """
    has_paygo = provider.overage_cost_per_1k_input > 0 or provider.overage_cost_per_1k_output > 0

    if usage_pct >= 1.0:
        if has_paygo:
            return (
                provider.overage_cost_per_1k_input + provider.overage_cost_per_1k_output
            ) / 2000  # average per-token cost
        return 999.0

    daily = _daily_budget(provider)
    if daily <= 0:
        return 1.0

    remaining = daily * max(0.01, 1.0 - usage_pct)
    return 1.0 / math.log(max(remaining, 2.0))
