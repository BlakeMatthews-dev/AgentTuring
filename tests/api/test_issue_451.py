"""Tests for removing quoted type annotations in services.py."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

SERVICES_PATH = Path("src/stronghold/builders/services.py")


@pytest.fixture
def services_file() -> Path:
    """Fixture providing the services.py file path."""
    return SERVICES_PATH


class TestQuotedTypeAnnotations:
    def test_no_up037_errors_in_services(self, services_file: Path) -> None:
        """Test that no UP037 errors exist in services.py after removing quoted annotations."""
        result = subprocess.run(
            ["ruff", "check", str(services_file)],
            capture_output=True,
            text=True,
        )
        assert "UP037" not in result.stdout, "UP037 errors found in services.py"
        assert "UP037" not in result.stderr, "UP037 errors found in services.py"

        # Verify line 63 doesn't contain quoted type annotation
        lines = services_file.read_text().splitlines()
        line_63 = lines[62]  # 0-indexed
        assert not line_63.strip().startswith(("status: str =", "status: 'str' =")), (
            "Line 63 still contains quoted type annotation"
        )


class TestRuffFormatCompliance:
    def test_ruff_format_passes_for_services(self, services_file: Path) -> None:
        """Test that ruff format --check passes for services.py.

        Ruff's `format --check` exits 0 when the file is correctly
        formatted and 1 when it is not. On success it still prints a
        status line like '1 file already formatted' to stdout — that
        text is normal output, NOT a failure signal. The earlier
        version of this test asserted `not result.stdout.strip()`
        which incorrectly treated the success status line as a
        failure, so the test was permanently red. Fixed: rely on the
        return code only.
        """
        result = subprocess.run(
            ["ruff", "format", "--check", str(services_file)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"ruff format --check failed for services.py with return code "
            f"{result.returncode}.\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
