"""PytestRunner: pytest execution + output parsing.

Extracted from RuntimePipeline to enable isolated testing of the TDD loop's
test-count tracking without constructing the full pipeline.
"""

from __future__ import annotations

import re
from typing import Any


class PytestRunner:
    """Pytest execution and output parsing."""

    def __init__(self, tool_dispatcher: Any) -> None:
        self._td = tool_dispatcher

    async def run(self, workspace: str, path: str = "tests/") -> str:
        """Run pytest with workspace src/ taking priority over installed package."""
        cmd = (
            f"python -c \"import sys; sys.path.insert(0, '{workspace}/src'); "
            f"import pytest; pytest.main(['{path}', '-v'])\""
        )
        return await self._td.execute(
            "shell", {"command": cmd, "workspace": workspace},
        )

    @staticmethod
    def count_passing(output: str) -> int:
        """Count passing tests from pytest output."""
        match = re.search(r"(\d+)\s+passed", output)
        return int(match.group(1)) if match else 0

    @staticmethod
    def count_failing(output: str) -> int:
        """Count failing tests from pytest output."""
        failed = re.search(r"(\d+)\s+failed", output)
        errors = re.search(r"(\d+)\s+error", output)
        return (int(failed.group(1)) if failed else 0) + (int(errors.group(1)) if errors else 0)

    @staticmethod
    def parse_violation_files(output: str) -> list[str]:
        """Extract file paths from ruff/mypy output."""
        paths: list[str] = []
        for match in re.finditer(r"(src/\S+\.py)", output):
            path = match.group(1)
            if path not in paths:
                paths.append(path)
        return paths
