"""Tests for scroll-smooth class on html element."""

from __future__ import annotations

from pathlib import Path

import pytest

DASHBOARD_DIR = Path("src/stronghold/dashboard")

class TestScrollSmooth:
    def test_html_has_scroll_smooth_class(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert 'class="scroll-smooth"' in html, "Missing scroll-smooth class on html element"

    def test_scroll_smooth_class_not_duplicated(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert html.count('class="scroll-smooth"') == 1, "scroll-smooth class appears more than once"

    def test_no_conflicting_scroll_classes(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        # Check that html tag doesn't have other scroll-related classes
        import re
        html_tag_match = re.search(r'<html[^>]*class="([^"]*)"', html)
        if html_tag_match:
            classes = html_tag_match.group(1)
            # Only scroll-smooth should be present, no other scroll classes
            assert "scroll-" not in classes.replace("scroll-smooth", ""), "Conflicting scroll-related classes found on html element"