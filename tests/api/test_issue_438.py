"""Tests for unused imports in base.py."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

BASE_PY_PATH = Path("src/stronghold/agents/base.py")


@pytest.fixture
def base_py_content() -> str:
    """Read the base.py file content."""
    return BASE_PY_PATH.read_text(encoding="utf-8")


class TestUnusedImports:
    def test_ruff_check_base_py_has_no_unused_imports(self) -> None:
        """Verify ruff check reports zero unused import errors for base.py."""
        result = subprocess.run(
            ["ruff", "check", "src/stronghold/agents/base.py"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"ruff check failed with return code {result.returncode}:\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "F401" not in result.stdout, "Unused imports (F401) still present"

    def test_ruff_check_base_py_has_sorted_imports(self) -> None:
        """Verify ruff check reports zero import order errors (I001) for base.py."""
        result = subprocess.run(
            ["ruff", "check", "src/stronghold/agents/base.py"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"ruff check failed with return code {result.returncode}:\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "I001" not in result.stdout, "Imports are not sorted (I001)"

    def test_ruff_check_base_py_has_no_quoted_annotations(self) -> None:
        """Verify ruff check reports zero UP037 errors for quoted type annotations in base.py."""
        result = subprocess.run(
            ["ruff", "check", "src/stronghold/agents/base.py"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"ruff check failed with return code {result.returncode}:\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "UP037" not in result.stdout, "Quoted type annotations (UP037) still present"
