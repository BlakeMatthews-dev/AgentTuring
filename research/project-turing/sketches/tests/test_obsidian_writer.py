"""Tests for runtime/tools/obsidian.py."""

from __future__ import annotations

from pathlib import Path

from turing.runtime.tools.obsidian import ObsidianWriter, _slugify


def test_slugify_basic() -> None:
    assert _slugify("Hello World!") == "hello-world"
    assert _slugify("") == "note"
    assert _slugify("special $# chars") == "special-chars"


def test_writer_creates_dated_subdir(tmp_path: Path) -> None:
    writer = ObsidianWriter(vault_dir=tmp_path)
    path = Path(
        writer.invoke(
            title="A first note",
            content="hello body",
            tags=["test", "turing"],
            kind="note",
        )
    )
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "title: A first note" in text
    assert "kind: note" in text
    assert "tags: [test, turing]" in text
    assert "# A first note" in text
    assert "hello body" in text


def test_writer_subdir_default_used(tmp_path: Path) -> None:
    writer = ObsidianWriter(vault_dir=tmp_path)
    path = Path(writer.invoke(title="t", content="c"))
    # default subdir is "Project Turing"
    assert "Project Turing" in path.parts


def test_writer_no_subdir(tmp_path: Path) -> None:
    writer = ObsidianWriter(vault_dir=tmp_path, subdir=None)
    path = Path(writer.invoke(title="t", content="c"))
    parts = path.relative_to(tmp_path).parts
    # Without subdir, first level is the date.
    assert parts[0].count("-") == 2     # YYYY-MM-DD


def test_front_matter_overrides_merge(tmp_path: Path) -> None:
    writer = ObsidianWriter(vault_dir=tmp_path)
    path = Path(
        writer.invoke(
            title="t",
            content="c",
            front_matter={"memory_id": "abc", "weight": 0.95},
        )
    )
    text = path.read_text(encoding="utf-8")
    assert "memory_id: abc" in text
    assert "weight: 0.95" in text
