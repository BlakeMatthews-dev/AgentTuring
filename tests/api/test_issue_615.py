"""Tests for LevelBadge component structure."""

from __future__ import annotations

from pathlib import Path

import pytest

DASHBOARD_DIR = Path("src/stronghold/dashboard")

class TestLevelBadgeComponent:
    def test_level_badge_component_exists(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "LevelBadge" in html, "LevelBadge component not found in HTML"

    def test_level_badge_has_default_export(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert 'export default LevelBadge' in html, "LevelBadge not exported as default"

    def test_level_badge_has_correct_tailwind_classes(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "rounded-full" in html, "Missing rounded-full class"
        assert "bg-emerald-500" in html, "Missing bg-emerald-500 class"
        assert "text-white" in html, "Missing text-white class"
        assert "font-bold" in html, "Missing font-bold class"

    def test_level_badge_renders_level_text(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "Level" in html, "Missing 'Level' text"
        # Check for dynamic level pattern (e.g., Level {level} or Level X)
        assert "Level" in html and ("{" in html or "X" in html), "Level badge doesn't show dynamic level text"

    def test_level_badge_handles_invalid_level_prop(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        # Check for fallback handling in JavaScript (e.g., default value or validation)
        assert "||" in html or "?? 0" in html or "fallback" in html.lower(), "Missing fallback handling for invalid level prop"
        # Check for Level 0 rendering pattern
        assert "Level 0" in html, "Missing fallback 'Level 0' text"