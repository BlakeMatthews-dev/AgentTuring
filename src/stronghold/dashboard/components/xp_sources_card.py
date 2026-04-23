"""XP Sources Card component for Mason dashboard.

Displays total XP, current level, progress to next level,
and recent XP gains with sources.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class XPSource:
    """Single XP source entry."""

    source: str
    xp_amount: int
    timestamp: str
    description: str = ""


@dataclass
class XPProgress:
    """XP progress data."""

    total_xp: int
    current_level: int
    xp_for_next_level: int
    progress_percent: float


class XPSourcesCard:
    """XP Sources Card component.

    Displays XP total, level progress, and recent XP gains.
    """

    def __init__(self, total_xp: int = 0, recent_sources: list[XPSource] | None = None) -> None:
        """Initialize XP Sources Card.

        Args:
            total_xp: Total XP earned
            recent_sources: List of recent XP sources (default: empty list)
        """
        self.total_xp = total_xp
        self.recent_sources = recent_sources or []

    def _calculate_level(self, total_xp: int) -> int:
        """Calculate level from total XP.

        Level thresholds:
            Level 1: 0 XP
            Level 2: 100 XP
            Level 3: 300 XP
            Level 4: 600 XP
            Level 5: 1000 XP
            Level 6: 1500 XP
            Level 7: 2100 XP
            Level 8: 2800 XP
            Level 9: 3600 XP
            Level 10: 4500 XP
        """
        thresholds = [0, 100, 300, 600, 1000, 1500, 2100, 2800, 3600, 4500]
        level = 1
        for threshold in reversed(thresholds):
            if total_xp >= threshold:
                level = thresholds.index(threshold) + 1
                break
        return level

    def _get_progress(self, total_xp: int, current_level: int) -> XPProgress:
        """Calculate progress to next level.

        Args:
            total_xp: Total XP earned
            current_level: Current level (1-10)

        Returns:
            XPProgress with level data
        """
        thresholds = [0, 100, 300, 600, 1000, 1500, 2100, 2800, 3600, 4500]
        if current_level >= len(thresholds):
            next_level_xp = 4500
            progress = 100.0
        else:
            next_level_xp = thresholds[current_level]
            prev_level_xp = thresholds[current_level - 1]
            if next_level_xp > prev_level_xp:
                progress = ((total_xp - prev_level_xp) / (next_level_xp - prev_level_xp)) * 100
            else:
                progress = 100.0
        return XPProgress(
            total_xp=total_xp,
            current_level=current_level,
            xp_for_next_level=max(0, next_level_xp - total_xp),
            progress_percent=min(100.0, max(0.0, progress)),
        )

    def render(self) -> str:
        """Render XP Sources Card as HTML.

        Returns:
            HTML string for card
        """
        level = self._calculate_level(self.total_xp)
        progress = self._get_progress(self.total_xp, level)

        recent_html = "\n".join(
            f'        <li><span class="xp-source">{s.source}</span>: '
            f'<span class="xp-amount">+{s.xp_amount} XP</span> - {s.description}</li>'
            for s in self.recent_sources[:10]
        )

        progress_label = f"{progress.progress_percent:.0f}% to Level {min(10, level + 1)}"
        xp_total_text = f"Level {level} - {self.total_xp} XP"

        card_html = f"""
        <div class="xp-sources-card">
          <div class="xp-header">
            <div class="xp-total">{xp_total_text}</div>
            <div class="xp-progress">
              <span class="progress-label">{progress_label}</span>
              <div class="progress-bar">
                <div class="progress-fill" style="width: {progress.progress_percent:.0f}%"></div>
              </div>
            </div>
          </div>
        </div>
          <div class="xp-recent">
            <h3>Recent XP Gains</h3>
            <ul class="xp-sources-list">
        {recent_html}
            </ul>
          </div>
        </div>
        """
        return card_html


def xp_sources_card(total_xp: int = 0, recent_sources: list[XPSource] | None = None) -> str:
    """Convenience function to render XP Sources Card.

    Args:
        total_xp: Total XP earned
        recent_sources: List of recent XP sources

    Returns:
        HTML string for card
    """
    return XPSourcesCard(total_xp, recent_sources).render()
