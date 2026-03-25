"""Skill canary deployment: staged rollout with auto-rollback."""

from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger("stronghold.skills.canary")


class CanaryStage(StrEnum):
    """Rollout stage."""

    CANARY = "canary"  # 5% traffic
    PARTIAL = "partial"  # 25% traffic
    MAJORITY = "majority"  # 75% traffic
    FULL = "full"  # 100% traffic


_STAGE_TRAFFIC: dict[CanaryStage, float] = {
    CanaryStage.CANARY: 0.05,
    CanaryStage.PARTIAL: 0.25,
    CanaryStage.MAJORITY: 0.75,
    CanaryStage.FULL: 1.0,
}

_STAGE_ORDER = [CanaryStage.CANARY, CanaryStage.PARTIAL, CanaryStage.MAJORITY, CanaryStage.FULL]


@dataclass
class CanaryDeployment:
    """State of a canary deployment for a skill."""

    skill_name: str
    old_version: int = 0
    new_version: int = 0
    stage: CanaryStage = CanaryStage.CANARY
    started_at: float = field(default_factory=time.time)
    stage_started_at: float = field(default_factory=time.time)
    total_requests: int = 0
    errors: int = 0
    org_id: str = ""

    @property
    def error_rate(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.errors / self.total_requests

    @property
    def traffic_pct(self) -> float:
        return _STAGE_TRAFFIC.get(self.stage, 0.0)


class CanaryManager:
    """Manages staged skill rollouts with auto-rollback on errors."""

    def __init__(
        self,
        error_threshold: float = 0.1,
        min_requests_per_stage: int = 20,
        stage_duration_secs: float = 300.0,
    ) -> None:
        self._error_threshold = error_threshold
        self._min_requests = min_requests_per_stage
        self._stage_duration = stage_duration_secs
        self._deployments: dict[tuple[str, str], CanaryDeployment] = {}  # (skill, org_id)
        self._rollbacks: list[dict[str, Any]] = []
        self._lock = threading.RLock()

    def start_canary(
        self,
        skill_name: str,
        old_version: int,
        new_version: int,
        org_id: str = "",
    ) -> CanaryDeployment:
        """Start a canary deployment."""
        deployment = CanaryDeployment(
            skill_name=skill_name,
            old_version=old_version,
            new_version=new_version,
            org_id=org_id,
        )
        with self._lock:
            self._deployments[(skill_name, org_id)] = deployment
        logger.info(
            "Canary started: %s v%d->v%d at %d%% traffic",
            skill_name,
            old_version,
            new_version,
            int(deployment.traffic_pct * 100),
        )
        return deployment

    def get_deployment(self, skill_name: str, org_id: str = "") -> CanaryDeployment | None:
        """Get active canary deployment."""
        return self._deployments.get((skill_name, org_id))

    def should_use_new_version(self, skill_name: str, org_id: str = "") -> bool:
        """Determine whether a request should use the new version.

        Uses random sampling based on traffic percentage for the current stage.
        C14: Always requires org_id — prevents cross-tenant canary interference.
        """
        if not org_id:
            return False  # No org = no canary (prevent shared-state leakage)
        deployment = self._deployments.get((skill_name, org_id))
        if not deployment:
            return False
        return random.random() < deployment.traffic_pct  # noqa: S311

    def record_result(self, skill_name: str, success: bool, org_id: str = "") -> None:
        """Record a canary request result."""
        deployment = self._deployments.get((skill_name, org_id))
        if not deployment:
            return
        deployment.total_requests += 1
        if not success:
            deployment.errors += 1

    def check_promotion_or_rollback(self, skill_name: str, org_id: str = "") -> str:
        """Check if canary should advance, hold, or rollback.

        Returns: "advance", "hold", "rollback", or "complete"
        """
        deployment = self._deployments.get((skill_name, org_id))
        if not deployment:
            return "hold"

        # Check error threshold
        if (
            deployment.total_requests >= self._min_requests
            and deployment.error_rate > self._error_threshold
        ):
            self._rollback(deployment)
            return "rollback"

        # Check if ready to advance stage
        now = time.time()
        elapsed = now - deployment.stage_started_at
        if (
            elapsed >= self._stage_duration
            and deployment.total_requests >= self._min_requests
            and deployment.error_rate <= self._error_threshold
        ):
            return self._advance(deployment)

        return "hold"

    def _advance(self, deployment: CanaryDeployment) -> str:
        """Advance to next canary stage."""
        idx = _STAGE_ORDER.index(deployment.stage)
        if idx >= len(_STAGE_ORDER) - 1:
            # Already at full -- deployment complete
            key = (deployment.skill_name, deployment.org_id)
            del self._deployments[key]
            logger.info("Canary complete: %s promoted to full", deployment.skill_name)
            return "complete"

        deployment.stage = _STAGE_ORDER[idx + 1]
        deployment.stage_started_at = time.time()
        deployment.total_requests = 0
        deployment.errors = 0
        logger.info(
            "Canary advanced: %s -> %s (%d%%)",
            deployment.skill_name,
            deployment.stage.value,
            int(deployment.traffic_pct * 100),
        )
        return "advance"

    def _rollback(self, deployment: CanaryDeployment) -> None:
        """Rollback a canary deployment."""
        key = (deployment.skill_name, deployment.org_id)
        self._rollbacks.append(
            {
                "skill_name": deployment.skill_name,
                "new_version": deployment.new_version,
                "rolled_back_at": time.time(),
                "error_rate": deployment.error_rate,
                "total_requests": deployment.total_requests,
                "stage": deployment.stage.value,
                "org_id": deployment.org_id,
            }
        )
        del self._deployments[key]
        # Cap rollback history to prevent unbounded memory growth
        if len(self._rollbacks) > 200:
            self._rollbacks = self._rollbacks[-100:]
        logger.warning(
            "Canary ROLLBACK: %s (error_rate=%.2f%%, stage=%s)",
            deployment.skill_name,
            deployment.error_rate * 100,
            deployment.stage.value,
        )

    def list_active(self) -> list[dict[str, Any]]:
        """List all active canary deployments."""
        return [
            {
                "skill_name": d.skill_name,
                "old_version": d.old_version,
                "new_version": d.new_version,
                "stage": d.stage.value,
                "traffic_pct": int(d.traffic_pct * 100),
                "total_requests": d.total_requests,
                "errors": d.errors,
                "error_rate": round(d.error_rate, 4),
            }
            for d in self._deployments.values()
        ]

    def list_rollbacks(self, limit: int = 20) -> list[dict[str, Any]]:
        """List recent rollbacks."""
        return self._rollbacks[-limit:]
