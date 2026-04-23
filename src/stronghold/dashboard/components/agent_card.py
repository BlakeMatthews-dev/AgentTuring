"""Agent Card UI component.

Displays agent details (name, description, tools, priority tier, trust tier)
with interactive elements (start chat, view stats, edit settings).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from stronghold.dashboard.components import LevelBadge


@dataclass
class AgentStats:
    """Agent statistics."""

    tasks_completed: int = 0
    xp: int = 0
    success_rate: float = 0.0
    total_tasks: int = 0


class AgentCard:
    """Agent Card component.

    Displays agent details with interactive elements.
    """

    def __init__(
        self,
        name: str,
        description: str,
        tools: list[str],
        priority_tier: Literal["P0", "P1", "P2", "P3", "P4", "P5"],
        trust_tier: Literal["t0", "t1", "t2", "t3", "t4"],
        active: bool = True,
        stats: AgentStats | None = None,
    ) -> None:
        """Initialize Agent Card.

        Args:
            name: Agent name
            description: Agent description
            tools: List of tools agent has access to
            priority_tier: Priority tier (P0-P5)
            trust_tier: Trust tier (t0-t4)
            active: Whether agent is active
            stats: Agent statistics (optional)
        """
        self.name = name
        self.description = description
        self.tools = tools
        self.priority_tier = priority_tier
        self.trust_tier = trust_tier
        self.active = active
        self.stats = stats or AgentStats()

    def render(self) -> str:
        """Render Agent Card as HTML.

        Returns:
            HTML string for card
        """
        priority_badge = LevelBadge(self._get_priority_level()).render()

        tools_html = "\n".join(f"              <li>{tool}</li>" for tool in self.tools[:10])

        status_indicator = "active" if self.active else "inactive"

        stats_html = ""
        if self.stats.total_tasks > 0:
            success_rate = (
                (self.stats.success_rate / self.stats.total_tasks) * 100
                if self.stats.total_tasks > 0
                else 0.0
            )
            stats_html = f"""
              <div class="agent-stats">
                <div class="stat-item">
                  <span class="stat-label">Tasks</span>
                  <span class="stat-value">
                    {self.stats.tasks_completed}/{self.stats.total_tasks}
                  </span>
                </div>
                <div class="stat-item">
                  <span class="stat-label">Success Rate</span>
                  <span class="stat-value">{success_rate:.0f}%</span>
                </div>
                <div class="stat-item">
                  <span class="stat-label">XP</span>
                  <span class="stat-value">{self.stats.xp}</span>
                </div>
              </div>
            """

        card_html = f"""
        <div class="agent-card" data-agent="{self.name}">
          <div class="agent-header">
            <div class="agent-name">{self.name}</div>
            <div class="agent-badges">
              {priority_badge}
              <div class="trust-badge t{self.trust_tier}">T{self.trust_tier[1]}</div>
            </div>
            <div class="agent-status {status_indicator}"></div>
          </div>
          <div class="agent-description">{self.description}</div>
          <div class="agent-tools">
            <h4>Tools ({len(self.tools)} total)</h4>
            <ul class="tools-list">
        {tools_html}
            </ul>
          </div>
        {stats_html}
          <div class="agent-actions">
            <button class="btn btn-primary" data-action="start-chat">Start Chat</button>
            <button class="btn btn-secondary" data-action="view-stats">View Stats</button>
            <button class="btn btn-secondary" data-action="edit-settings">Edit</button>
          </div>
        </div>
        """
        return card_html

    def _get_priority_level(self) -> int:
        """Convert priority tier to level number for LevelBadge.

        Returns:
            Level number (1-10)
        """
        priority_map = {
            "P0": 10,
            "P1": 8,
            "P2": 6,
            "P3": 5,
            "P4": 4,
            "P5": 3,
        }
        return priority_map.get(self.priority_tier, 5)


def agent_card(
    name: str,
    description: str,
    tools: list[str],
    priority_tier: Literal["P0", "P1", "P2", "P3", "P4", "P5"],
    trust_tier: Literal["t0", "t1", "t2", "t3", "t4"],
    active: bool = True,
    stats: AgentStats | None = None,
) -> str:
    """Convenience function to render Agent Card.

    Args:
        name: Agent name
        description: Agent description
        tools: List of tools
        priority_tier: Priority tier (P0-P5)
        trust_tier: Trust tier (t0-t4)
        active: Whether agent is active
        stats: Agent statistics

    Returns:
        HTML string for card
    """
    return AgentCard(
        name=name,
        description=description,
        tools=tools,
        priority_tier=priority_tier,
        trust_tier=trust_tier,
        active=active,
        stats=stats,
    ).render()
