"""Dashboard UI components."""

from __future__ import annotations


class LevelBadge:
    """Renders a visual badge for a numeric level (1-10)."""

    def __init__(self, level: int) -> None:
        self.level = max(1, min(10, level))

    def render(self) -> str:
        color = _level_color(self.level)
        return f'<div class="level-badge" style="background:{color}">L{self.level}</div>'


def _level_color(level: int) -> str:
    if level >= 8:
        return "#22c55e"
    if level >= 5:
        return "#3b82f6"
    return "#94a3b8"
