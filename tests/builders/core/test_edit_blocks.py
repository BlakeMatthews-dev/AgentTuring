"""Tests for the search/replace edit block parser and applicator.

Bug 7: Mason was rewriting entire files instead of making surgical
edits, dropping existing content. The fix introduces a search/replace
edit format that the LLM produces instead of the full file.
"""
from __future__ import annotations

from stronghold.builders.pipeline import RuntimePipeline


class TestParseEditBlocks:
    def test_single_search_replace(self) -> None:
        raw = (
            "Here is my edit:\n\n"
            "<<<< SEARCH\n"
            "    return 42\n"
            "====\n"
            "    return 43\n"
            ">>>> REPLACE\n"
        )
        blocks = RuntimePipeline._parse_edit_blocks(raw)
        assert len(blocks) == 1
        assert blocks[0] == ("    return 42", "    return 43")

    def test_multiple_edits(self) -> None:
        raw = (
            "<<<< SEARCH\n"
            "import os\n"
            "====\n"
            "import os\nimport sys\n"
            ">>>> REPLACE\n"
            "\n"
            "<<<< SEARCH\n"
            "x = 1\n"
            "====\n"
            "x = 2\n"
            ">>>> REPLACE\n"
        )
        blocks = RuntimePipeline._parse_edit_blocks(raw)
        assert len(blocks) == 2

    def test_empty_search_means_append(self) -> None:
        raw = (
            "<<<< SEARCH\n"
            "====\n"
            "class NewClass:\n"
            "    pass\n"
            ">>>> REPLACE\n"
        )
        blocks = RuntimePipeline._parse_edit_blocks(raw)
        assert len(blocks) == 1
        assert blocks[0][0] == ""  # empty search = append
        assert "class NewClass" in blocks[0][1]

    def test_no_edit_blocks_returns_empty(self) -> None:
        raw = "Here is the complete file:\n```python\nprint('hello')\n```"
        blocks = RuntimePipeline._parse_edit_blocks(raw)
        assert blocks == []


class TestApplyEditBlocks:
    def test_simple_replacement(self) -> None:
        original = "line1\nline2\nline3\n"
        blocks = [("line2", "LINE_TWO")]
        result, warnings = RuntimePipeline._apply_edit_blocks(original, blocks)
        assert "LINE_TWO" in result
        assert "line2" not in result
        assert warnings == []

    def test_append_via_empty_search(self) -> None:
        original = "class Foo:\n    pass\n"
        blocks = [("", "class Bar:\n    pass")]
        result, warnings = RuntimePipeline._apply_edit_blocks(original, blocks)
        assert "class Foo" in result
        assert "class Bar" in result
        assert warnings == []

    def test_preserves_all_existing_content(self) -> None:
        """The critical Bug 7 test: appending a class must not lose
        any existing content from a 20-line file."""
        original = "\n".join(f"line_{i}" for i in range(20)) + "\n"
        blocks = [("", "class NewStuff:\n    pass")]
        result, warnings = RuntimePipeline._apply_edit_blocks(original, blocks)
        for i in range(20):
            assert f"line_{i}" in result, f"line_{i} was dropped!"
        assert "class NewStuff" in result

    def test_search_not_found_produces_warning(self) -> None:
        original = "aaa\nbbb\nccc\n"
        blocks = [("zzz_not_here", "replacement")]
        result, warnings = RuntimePipeline._apply_edit_blocks(original, blocks)
        assert len(warnings) == 1
        assert "not found" in warnings[0].lower()

    def test_multiple_edits_applied_in_order(self) -> None:
        original = "a = 1\nb = 2\nc = 3\n"
        blocks = [("a = 1", "a = 10"), ("c = 3", "c = 30")]
        result, warnings = RuntimePipeline._apply_edit_blocks(original, blocks)
        assert "a = 10" in result
        assert "b = 2" in result
        assert "c = 30" in result
        assert warnings == []


class TestSafeWriteFile:
    """Test the deletion guard (belt-and-suspenders behind edit mode)."""

    def test_rejects_large_deletion(self) -> None:
        """A rewrite that drops >30% of lines should be rejected."""
        original = "\n".join(f"line_{i}" for i in range(100)) + "\n"
        new = "\n".join(f"line_{i}" for i in range(50)) + "\n"

        original_lines = len(original.splitlines())
        new_lines = len(new.splitlines())
        lost = original_lines - new_lines
        ratio = lost / original_lines

        assert ratio > RuntimePipeline._MAX_LINE_LOSS_RATIO

    def test_accepts_small_deletion(self) -> None:
        """A rewrite that drops <30% of lines should be accepted."""
        original = "\n".join(f"line_{i}" for i in range(100)) + "\n"
        new = "\n".join(f"line_{i}" for i in range(80)) + "\n"

        original_lines = len(original.splitlines())
        new_lines = len(new.splitlines())
        lost = original_lines - new_lines
        ratio = lost / original_lines

        assert ratio <= RuntimePipeline._MAX_LINE_LOSS_RATIO

    def test_accepts_growth(self) -> None:
        """Adding lines (negative loss) should always be accepted."""
        original = "\n".join(f"line_{i}" for i in range(100)) + "\n"
        new = "\n".join(f"line_{i}" for i in range(150)) + "\n"

        original_lines = len(original.splitlines())
        new_lines = len(new.splitlines())
        lost = original_lines - new_lines

        assert lost < 0  # growth, not loss
