"""Core reactor triggers — registered at container startup.

Each trigger is a TriggerSpec + async action handler.
The reactor evaluates conditions at 1000Hz and dispatches matches.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from stronghold.types.reactor import Event, TriggerMode, TriggerSpec

if TYPE_CHECKING:
    from stronghold.container import Container

logger = logging.getLogger("stronghold.triggers")


def register_core_triggers(container: Container) -> None:
    """Register all core triggers with the reactor."""
    reactor = container.reactor

    # 1. Learning promotion check (every 60s)
    async def _check_learning_promotions(event: Event) -> dict[str, Any]:
        if hasattr(container, "learning_promoter") and container.learning_promoter:
            promoted = await container.learning_promoter.check_and_promote()
            return {"promoted_count": len(promoted)}
        return {"skipped": True}

    reactor.register(
        TriggerSpec(
            name="learning_promotion_check",
            mode=TriggerMode.INTERVAL,
            interval_secs=60.0,
            jitter=0.1,
        ),
        _check_learning_promotions,
    )

    # 2. Rate limiter stale key eviction (every 5 minutes)
    async def _evict_stale_rate_keys(event: Event) -> dict[str, Any]:
        import time

        before = len(container.rate_limiter._windows)
        container.rate_limiter._evict_stale_keys(time.monotonic())
        after = len(container.rate_limiter._windows)
        evicted = before - after
        if evicted > 0:
            logger.debug("Evicted %d stale rate limit keys", evicted)
        return {"evicted": evicted}

    reactor.register(
        TriggerSpec(
            name="rate_limit_eviction",
            mode=TriggerMode.INTERVAL,
            interval_secs=300.0,
        ),
        _evict_stale_rate_keys,
    )

    # 3. Outcome stats snapshot (every 5 minutes)
    async def _snapshot_outcome_stats(event: Event) -> dict[str, Any]:
        stats = await container.outcome_store.get_task_completion_rate()
        logger.debug(
            "Outcome stats: %d total, %.1f%% success",
            stats.get("total", 0),
            stats.get("rate", 0) * 100,
        )
        return stats

    reactor.register(
        TriggerSpec(
            name="outcome_stats_snapshot",
            mode=TriggerMode.INTERVAL,
            interval_secs=300.0,
            jitter=0.2,
        ),
        _snapshot_outcome_stats,
    )

    # 4. Security rescan on flagged events
    async def _security_rescan(event: Event) -> dict[str, Any]:
        content = event.data.get("content", "")
        boundary = event.data.get("boundary", "tool_result")
        if content:
            verdict = await container.warden.scan(content, boundary)
            if not verdict.clean:
                logger.warning(
                    "Security rescan flagged content: %s",
                    verdict.flags,
                )
            return {"clean": verdict.clean, "flags": list(verdict.flags)}
        return {"skipped": True}

    reactor.register(
        TriggerSpec(
            name="security_rescan",
            mode=TriggerMode.EVENT,
            event_pattern=r"security\.rescan",
        ),
        _security_rescan,
    )

    # 5. Post-tool-loop event handler (emit learning extraction opportunity)
    async def _post_tool_learning(event: Event) -> dict[str, Any]:
        tool_name = event.data.get("tool_name", "")
        success = event.data.get("success", True)
        if not success and tool_name:
            logger.debug("Tool failure on %s — learning extraction opportunity", tool_name)
        return {"tool_name": tool_name, "success": success}

    reactor.register(
        TriggerSpec(
            name="post_tool_learning",
            mode=TriggerMode.EVENT,
            event_pattern=r"post_tool_loop",
        ),
        _post_tool_learning,
    )

    # 6. Tournament check (every 10 minutes — evaluate promotions)
    async def _tournament_check(event: Event) -> dict[str, Any]:
        if hasattr(container, "tournament") and container.tournament:
            stats: dict[str, Any] = container.tournament.get_stats()
            return stats
        return {"skipped": True}

    reactor.register(
        TriggerSpec(
            name="tournament_evaluation",
            mode=TriggerMode.INTERVAL,
            interval_secs=600.0,
            jitter=0.15,
        ),
        _tournament_check,
    )

    # 7. Canary deployment check (every 30 seconds)
    async def _canary_check(event: Event) -> dict[str, Any]:
        if hasattr(container, "canary_manager") and container.canary_manager:
            active = container.canary_manager.list_active()
            for deploy in active:
                result = container.canary_manager.check_promotion_or_rollback(
                    deploy["skill_name"],
                )
                if result in ("rollback", "advance", "complete"):
                    logger.info(
                        "Canary %s: %s → %s",
                        deploy["skill_name"],
                        deploy["stage"],
                        result,
                    )
            return {"active_canaries": len(active)}
        return {"skipped": True}

    reactor.register(
        TriggerSpec(
            name="canary_deployment_check",
            mode=TriggerMode.INTERVAL,
            interval_secs=30.0,
        ),
        _canary_check,
    )

    logger.info("Registered %d core triggers", len(reactor._triggers))
