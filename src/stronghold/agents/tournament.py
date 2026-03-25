"""Tournament: head-to-head agent scoring + auto-promotion."""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("stronghold.tournament")

# Default Elo parameters
_DEFAULT_ELO = 1200.0
_K_FACTOR = 32.0
_PROMOTION_THRESHOLD = 50  # Elo points above incumbent to trigger promotion
_MIN_BATTLES = 10  # Minimum battles before promotion eligible


@dataclass
class BattleRecord:
    """Result of a head-to-head agent comparison."""

    id: int = 0
    intent: str = ""
    agent_a: str = ""
    agent_b: str = ""
    winner: str = ""  # agent_a, agent_b, or "draw"
    score_a: float = 0.0  # 0-1 quality score
    score_b: float = 0.0
    judge_model: str = ""
    timestamp: float = field(default_factory=time.time)
    org_id: str = ""


@dataclass
class AgentRating:
    """Elo rating for an agent on a specific intent."""

    agent: str
    intent: str
    elo: float = _DEFAULT_ELO
    wins: int = 0
    losses: int = 0
    draws: int = 0
    org_id: str = ""

    @property
    def total_battles(self) -> int:
        return self.wins + self.losses + self.draws

    @property
    def win_rate(self) -> float:
        if self.total_battles == 0:
            return 0.0
        return (self.wins + 0.5 * self.draws) / self.total_battles


class Tournament:
    """In-memory tournament system with Elo ratings."""

    def __init__(self) -> None:
        self._ratings: dict[tuple[str, str, str], AgentRating] = {}  # (agent, intent, org_id)
        self._battles: list[BattleRecord] = []
        self._next_id: int = 1
        self._max_battles: int = 10000

    def _get_rating(self, agent: str, intent: str, org_id: str = "") -> AgentRating:
        key = (agent, intent, org_id)
        if key not in self._ratings:
            self._ratings[key] = AgentRating(agent=agent, intent=intent, org_id=org_id)
        return self._ratings[key]

    def record_battle(
        self,
        intent: str,
        agent_a: str,
        agent_b: str,
        score_a: float,
        score_b: float,
        judge_model: str = "",
        org_id: str = "",
    ) -> BattleRecord:
        """Record a battle result and update Elo ratings."""
        if score_a > score_b:
            winner = agent_a
        elif score_b > score_a:
            winner = agent_b
        else:
            winner = "draw"

        record = BattleRecord(
            id=self._next_id,
            intent=intent,
            agent_a=agent_a,
            agent_b=agent_b,
            winner=winner,
            score_a=score_a,
            score_b=score_b,
            judge_model=judge_model,
            org_id=org_id,
        )
        self._next_id += 1
        self._battles.append(record)

        # FIFO eviction
        if len(self._battles) > self._max_battles:
            self._battles.pop(0)

        # Update Elo
        ra = self._get_rating(agent_a, intent, org_id)
        rb = self._get_rating(agent_b, intent, org_id)

        expected_a = 1 / (1 + math.pow(10, (rb.elo - ra.elo) / 400))
        expected_b = 1 - expected_a

        if winner == agent_a:
            actual_a, actual_b = 1.0, 0.0
            ra.wins += 1
            rb.losses += 1
        elif winner == agent_b:
            actual_a, actual_b = 0.0, 1.0
            ra.losses += 1
            rb.wins += 1
        else:
            actual_a, actual_b = 0.5, 0.5
            ra.draws += 1
            rb.draws += 1

        ra.elo += _K_FACTOR * (actual_a - expected_a)
        rb.elo += _K_FACTOR * (actual_b - expected_b)

        logger.debug(
            "Battle %s vs %s on %s: winner=%s (elo: %.0f vs %.0f)",
            agent_a,
            agent_b,
            intent,
            winner,
            ra.elo,
            rb.elo,
        )
        return record

    def get_leaderboard(self, intent: str, org_id: str = "") -> list[dict[str, Any]]:
        """Get ranked agents for an intent."""
        ratings = [r for r in self._ratings.values() if r.intent == intent and r.org_id == org_id]
        ratings.sort(key=lambda r: r.elo, reverse=True)
        return [
            {
                "agent": r.agent,
                "elo": round(r.elo, 1),
                "wins": r.wins,
                "losses": r.losses,
                "draws": r.draws,
                "total": r.total_battles,
                "win_rate": round(r.win_rate, 3),
            }
            for r in ratings
        ]

    def check_promotions(
        self,
        intent: str,
        incumbent: str,
        org_id: str = "",
    ) -> str | None:
        """Check if any challenger should replace the incumbent.

        Returns challenger name if promotion warranted, None otherwise.
        """
        inc_rating = self._get_rating(incumbent, intent, org_id)
        best_challenger: str | None = None
        best_margin: float = 0.0

        for _key, rating in self._ratings.items():
            if rating.intent != intent or rating.org_id != org_id:
                continue
            if rating.agent == incumbent:
                continue
            if rating.total_battles < _MIN_BATTLES:
                continue

            margin = rating.elo - inc_rating.elo
            if margin >= _PROMOTION_THRESHOLD and margin > best_margin:
                best_challenger = rating.agent
                best_margin = margin

        if best_challenger:
            logger.info(
                "Promotion candidate: %s -> %s on intent=%s (margin=%.0f Elo)",
                incumbent,
                best_challenger,
                intent,
                best_margin,
            )
        return best_challenger

    def get_battle_history(
        self,
        agent: str | None = None,
        intent: str | None = None,
        org_id: str = "",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get recent battle records."""
        filtered = self._battles
        if agent:
            filtered = [b for b in filtered if b.agent_a == agent or b.agent_b == agent]
        if intent:
            filtered = [b for b in filtered if b.intent == intent]
        if org_id:
            filtered = [b for b in filtered if b.org_id == org_id]

        return [
            {
                "id": b.id,
                "intent": b.intent,
                "agent_a": b.agent_a,
                "agent_b": b.agent_b,
                "winner": b.winner,
                "score_a": b.score_a,
                "score_b": b.score_b,
                "judge_model": b.judge_model,
                "timestamp": b.timestamp,
            }
            for b in filtered[-limit:]
        ]

    def get_stats(self) -> dict[str, Any]:
        """Overall tournament statistics."""
        return {
            "total_battles": len(self._battles),
            "total_ratings": len(self._ratings),
            "intents_tracked": len({r.intent for r in self._ratings.values()}),
        }
