"""Tests for ProgressBar component props in index.html."""

from __future__ import annotations

from pathlib import Path

import pytest

DASHBOARD_DIR = Path("src/stronghold/dashboard")

class TestProgressBarProps:
    def test_progressbar_has_value_prop(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "value" in html, "Missing 'value' prop definition in ProgressBar"

    def test_progressbar_has_max_prop(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "max" in html, "Missing 'max' prop definition in ProgressBar"

    def test_progressbar_has_label_prop(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "label" in html, "Missing 'label' prop definition in ProgressBar"

class TestProgressBarTailwindClasses:
    def test_progressbar_has_correct_colors(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "bg-emerald-500" in html, "Missing 'bg-emerald-500' class for active progress"
        assert "bg-gray-700" in html, "Missing 'bg-gray-700' class for background"

class TestProgressBarPercentageText:
    def test_progressbar_renders_percentage_calculation(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "Math.round((value / max) * 100)" in html, "Missing percentage calculation"

    def test_progressbar_displays_percentage_in_jsx(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "{Math.round((value / max) * 100)}%" in html, "Missing percentage display in JSX"

class TestProgressBarAccessibility:
    def test_progressbar_has_accessibility_role(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "role='progressbar'" in html, "Missing role='progressbar' attribute"

    def test_progressbar_has_aria_value_now(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "aria-valuenow" in html, "Missing aria-valuenow attribute"

    def test_progressbar_has_aria_value_min(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "aria-valuemin" in html, "Missing aria-valuemin attribute"

    def test_progressbar_has_aria_value_max(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "aria-valuemax" in html, "Missing aria-valuemax attribute"

class TestProgressBarPropTypes:
    def test_progressbar_has_prop_types_validation(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "propTypes" in html, "Missing propTypes validation"
        assert ".value" in html, "Missing 'value' propType validation"
        assert ".max" in html, "Missing 'max' propType validation"
        assert ".label" in html, "Missing 'label' propType validation"

    def test_progressbar_has_default_props(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "defaultProps" in html, "Missing defaultProps definition"
        assert "max: 100" in html, "Missing defaultProps for 'max' with value 100"