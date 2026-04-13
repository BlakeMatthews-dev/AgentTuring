"""Tests for FileOpsExecutor — sandboxed file operations."""

from __future__ import annotations

import json

import pytest

from stronghold.tools.file_ops import FileOpsExecutor


@pytest.fixture
def executor():
    return FileOpsExecutor()


@pytest.fixture
def workspace(tmp_path):
    """Create a temp workspace with some files."""
    (tmp_path / "hello.txt").write_text("world", encoding="utf-8")
    (tmp_path / "subdir").mkdir()
    (tmp_path / "subdir" / "nested.txt").write_text("deep", encoding="utf-8")
    return tmp_path


async def test_read_file(executor, workspace):
    result = await executor.execute(
        {"action": "read", "path": "hello.txt", "workspace": str(workspace)}
    )
    assert result.success is True
    assert result.content == "world"


async def test_read_file_not_found(executor, workspace):
    result = await executor.execute(
        {"action": "read", "path": "nope.txt", "workspace": str(workspace)}
    )
    assert result.success is False
    assert "not found" in result.error


async def test_write_file(executor, workspace):
    result = await executor.execute(
        {
            "action": "write",
            "path": "new.txt",
            "content": "created",
            "workspace": str(workspace),
        }
    )
    assert result.success is True
    data = json.loads(result.content)
    assert data["status"] == "ok"
    assert data["bytes"] == 7
    assert (workspace / "new.txt").read_text() == "created"


async def test_write_creates_parent_dirs(executor, workspace):
    result = await executor.execute(
        {
            "action": "write",
            "path": "a/b/c.txt",
            "content": "nested",
            "workspace": str(workspace),
        }
    )
    assert result.success is True
    assert (workspace / "a" / "b" / "c.txt").read_text() == "nested"


async def test_list_files(executor, workspace):
    result = await executor.execute({"action": "list", "path": ".", "workspace": str(workspace)})
    assert result.success is True
    entries = json.loads(result.content)
    assert "hello.txt" in entries
    names = [e.split("/")[-1] for e in entries]
    assert "nested.txt" in names


async def test_list_not_a_directory(executor, workspace):
    result = await executor.execute(
        {"action": "list", "path": "hello.txt", "workspace": str(workspace)}
    )
    assert result.success is False
    assert "not a directory" in result.error


async def test_mkdir(executor, workspace):
    result = await executor.execute(
        {"action": "mkdir", "path": "new_dir/sub", "workspace": str(workspace)}
    )
    assert result.success is True
    assert (workspace / "new_dir" / "sub").is_dir()


async def test_exists_true(executor, workspace):
    result = await executor.execute(
        {"action": "exists", "path": "hello.txt", "workspace": str(workspace)}
    )
    assert result.success is True
    data = json.loads(result.content)
    assert data["exists"] is True
    assert data["is_file"] is True


async def test_exists_false(executor, workspace):
    result = await executor.execute(
        {"action": "exists", "path": "nope.txt", "workspace": str(workspace)}
    )
    assert result.success is True
    data = json.loads(result.content)
    assert data["exists"] is False


async def test_unknown_action(executor, workspace):
    result = await executor.execute({"action": "delete", "path": "x", "workspace": str(workspace)})
    assert result.success is False
    assert "unknown action" in result.error


async def test_no_workspace(executor):
    result = await executor.execute({"action": "read", "path": "x"})
    assert result.success is False
    assert "workspace" in result.error.lower()


async def test_workspace_not_found(executor):
    result = await executor.execute(
        {"action": "read", "path": "x", "workspace": "/nonexistent/path"}
    )
    assert result.success is False
    assert "not found" in result.error


async def test_path_escape_blocked(executor, workspace):
    """Paths that escape the workspace are rejected."""
    result = await executor.execute(
        {"action": "read", "path": "../../etc/passwd", "workspace": str(workspace)}
    )
    assert result.success is False
    assert "escapes" in result.error


# ---- security: path traversal via string prefix bypass (H1) ----


async def test_path_prefix_bypass_blocked(executor, tmp_path):
    """H1: /workspace/foobar/evil must NOT pass check for /workspace/foo.

    The string prefix check `str(target).startswith(str(ws))` is fooled
    when a sibling directory shares a prefix. Using pathlib is_relative_to()
    prevents this.
    """
    # Create two sibling dirs: "foo" (the workspace) and "foobar" (attacker-controlled)
    workspace = tmp_path / "foo"
    workspace.mkdir()
    evil_dir = tmp_path / "foobar"
    evil_dir.mkdir()
    (evil_dir / "secret.txt").write_text("stolen data", encoding="utf-8")

    # The relative path "../foobar/secret.txt" resolves to a path that
    # starts with the string "/tmp/.../foo" (because "foobar" starts with "foo").
    result = await executor.execute(
        {
            "action": "read",
            "path": "../foobar/secret.txt",
            "workspace": str(workspace),
        }
    )
    assert result.success is False
    assert "escapes" in result.error


async def test_symlink_escape_blocked(executor, tmp_path):
    """Symlinks that resolve outside the workspace must be blocked."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    (workspace / "link").symlink_to(outside / "secret.txt")

    result = await executor.execute(
        {
            "action": "read",
            "path": "link",
            "workspace": str(workspace),
        }
    )
    assert result.success is False
    assert "escapes" in result.error


async def test_write_path_prefix_bypass_blocked(executor, tmp_path):
    """H1: write action must also use is_relative_to, not string prefix."""
    workspace = tmp_path / "foo"
    workspace.mkdir()
    evil_dir = tmp_path / "foobar"
    evil_dir.mkdir()

    result = await executor.execute(
        {
            "action": "write",
            "path": "../foobar/pwned.txt",
            "content": "pwned",
            "workspace": str(workspace),
        }
    )
    assert result.success is False
    assert "escapes" in result.error
    # Must not have written the file
    assert not (evil_dir / "pwned.txt").exists()
