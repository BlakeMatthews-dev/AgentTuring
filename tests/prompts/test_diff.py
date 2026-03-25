"""Tests for prompt diff engine."""

from __future__ import annotations

from stronghold.prompts.diff import DiffLine, compute_diff


class TestComputeDiff:
    def test_identical_content_no_diff(self) -> None:
        result = compute_diff("hello\n", "hello\n")
        assert result == []

    def test_added_line(self) -> None:
        result = compute_diff("line1\n", "line1\nline2\n")
        ops = [d.op for d in result]
        assert "add" in ops

    def test_removed_line(self) -> None:
        result = compute_diff("line1\nline2\n", "line1\n")
        ops = [d.op for d in result]
        assert "remove" in ops

    def test_modified_line(self) -> None:
        result = compute_diff("old text\n", "new text\n")
        ops = [d.op for d in result]
        assert "remove" in ops
        assert "add" in ops

    def test_headers_present(self) -> None:
        result = compute_diff("a\n", "b\n")
        headers = [d for d in result if d.op == "header"]
        assert len(headers) >= 2  # --- and +++ at minimum

    def test_context_lines(self) -> None:
        old = "ctx1\nctx2\nold\nctx3\nctx4\n"
        new = "ctx1\nctx2\nnew\nctx3\nctx4\n"
        result = compute_diff(old, new, context_lines=1)
        context = [d for d in result if d.op == "context"]
        assert len(context) >= 1

    def test_labels(self) -> None:
        result = compute_diff("a\n", "b\n", old_label="v1.0", new_label="v2.0")
        header_content = " ".join(d.content for d in result if d.op == "header")
        assert "v1.0" in header_content
        assert "v2.0" in header_content

    def test_line_numbers_tracked(self) -> None:
        result = compute_diff("a\nb\nc\n", "a\nx\nc\n")
        adds = [d for d in result if d.op == "add"]
        removes = [d for d in result if d.op == "remove"]
        for d in adds:
            assert d.new_lineno is not None
        for d in removes:
            assert d.old_lineno is not None

    def test_empty_to_content(self) -> None:
        result = compute_diff("", "new content\n")
        ops = [d.op for d in result]
        assert "add" in ops

    def test_diffline_frozen(self) -> None:
        d = DiffLine(op="add", content="test", new_lineno=1)
        assert d.op == "add"
        assert d.content == "test"

    def test_content_to_empty(self) -> None:
        result = compute_diff("existing content\n", "")
        ops = [d.op for d in result]
        assert "remove" in ops

    def test_multiline_diff(self) -> None:
        old = "line1\nline2\nline3\nline4\nline5\n"
        new = "line1\nchanged\nline3\nadded\nline4\nline5\n"
        result = compute_diff(old, new)
        adds = [d for d in result if d.op == "add"]
        removes = [d for d in result if d.op == "remove"]
        assert len(adds) >= 1
        assert len(removes) >= 1

    def test_default_labels(self) -> None:
        result = compute_diff("a\n", "b\n")
        header_content = " ".join(d.content for d in result if d.op == "header")
        assert "previous" in header_content
        assert "current" in header_content
