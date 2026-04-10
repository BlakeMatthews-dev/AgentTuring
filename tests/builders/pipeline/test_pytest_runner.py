"""Unit tests for the extracted PytestRunner module."""

from __future__ import annotations

from stronghold.builders.pipeline.pytest_runner import PytestRunner


class TestCountPassing:
    def test_zero(self) -> None:
        assert PytestRunner.count_passing("0 passed") == 0

    def test_many(self) -> None:
        assert PytestRunner.count_passing("47 passed in 12.3s") == 47

    def test_no_match(self) -> None:
        assert PytestRunner.count_passing("ERROR") == 0


class TestCountFailing:
    def test_both(self) -> None:
        assert PytestRunner.count_failing("3 failed, 2 errors") == 5

    def test_none(self) -> None:
        assert PytestRunner.count_failing("10 passed") == 0


class TestParseViolationFiles:
    def test_extracts(self) -> None:
        out = "src/stronghold/foo.py:10: E501\nsrc/stronghold/bar.py:5: W291"
        assert PytestRunner.parse_violation_files(out) == [
            "src/stronghold/foo.py", "src/stronghold/bar.py"
        ]

    def test_dedupes(self) -> None:
        out = "src/stronghold/foo.py:1: E\nsrc/stronghold/foo.py:2: E"
        assert PytestRunner.parse_violation_files(out) == ["src/stronghold/foo.py"]
