"""Coverage tests for SkillCatalog — targeting uncovered lines in catalog.py."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

from stronghold.skills.catalog import SkillCatalog, SkillCatalogEntry, _is_visible
from stronghold.types.skill import SkillDefinition


def _skill(name: str) -> SkillDefinition:
    return SkillDefinition(name=name, description=f"{name} skill")


def _entry(
    name: str, scope: str = "builtin", tenant_id: str = "", user_id: str = ""
) -> SkillCatalogEntry:
    return SkillCatalogEntry(
        definition=_skill(name), scope=scope, tenant_id=tenant_id, user_id=user_id
    )


_VALID_SKILL_MD = (
    "---\nname: greet\ndescription: Greet the user\ngroups: [chat]\n"
    "parameters:\n  type: object\n  properties:\n    name:\n      type: string\n"
    "---\nSay hello warmly.\n"
)


# --- Line 68: resolve skips entries whose name doesn't match ---

def test_resolve_skips_non_matching_names() -> None:
    """Line 68: entry.definition.name != skill_name -> continue."""
    cat = SkillCatalog()
    cat.register(_entry("alpha"))
    cat.register(_entry("beta"))
    result = cat.resolve("alpha")
    assert result is not None
    assert result.definition.name == "alpha"


# --- Line 87: list_skills skips invisible entries ---

def test_list_skills_skips_invisible_tenant_entry() -> None:
    """Line 87: _is_visible returns False for wrong tenant."""
    cat = SkillCatalog()
    cat.register(_entry("secret", scope="tenant", tenant_id="acme"))
    cat.register(_entry("public", scope="builtin"))
    skills = cat.list_skills(tenant_id="other-corp")
    names = [s.definition.name for s in skills]
    assert "secret" not in names
    assert "public" in names


# --- Lines 109-110: load_directory skips files where parse returns None ---

def test_load_directory_skips_unparseable_file() -> None:
    """Lines 109-110: parse_skill_file returns None -> warning + continue."""
    tmp = tempfile.mkdtemp()
    bad_file = Path(tmp) / "bad.md"
    bad_file.write_text("This is not a valid skill file — no frontmatter.")
    cat = SkillCatalog()
    count = cat.load_directory(tmp)
    assert count == 0


# --- Lines 120-121: load_directory catches exceptions from malformed files ---

def test_load_directory_catches_exception_on_broken_yaml() -> None:
    """Lines 120-121: exception during parse -> warning + continue."""
    tmp = tempfile.mkdtemp()
    # Create a file that has frontmatter delimiters but invalid YAML
    broken = Path(tmp) / "broken.md"
    broken.write_text("---\n: :\n  - [\n---\nBody.\n")
    # Also a valid file so we verify count
    good = Path(tmp) / "greet.md"
    good.write_text(_VALID_SKILL_MD)
    cat = SkillCatalog()
    count = cat.load_directory(tmp)
    assert count == 1  # only the good one loaded


# --- Line 127: start_watching returns early if watcher already running ---

def test_start_watching_noop_if_already_running() -> None:
    """Line 127: if watcher_thread alive, return early."""
    tmp = tempfile.mkdtemp()
    cat = SkillCatalog()
    cat.start_watching(tmp, poll_interval=0.1)
    try:
        first_thread = cat._watcher_thread
        assert first_thread is not None
        # Start again — should be a no-op
        cat.start_watching(tmp, poll_interval=0.1)
        assert cat._watcher_thread is first_thread  # same thread
    finally:
        cat.stop_watching()


# --- Lines 146-147: _watch_loop catches exceptions in _check_for_changes ---

def test_watch_loop_handles_exception_in_check() -> None:
    """Lines 146-147: exception in _check_for_changes is caught."""
    tmp = tempfile.mkdtemp()
    cat = SkillCatalog()

    original_check = cat._check_for_changes
    call_count = 0

    def broken_check(directory: Path) -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("simulated error")
        original_check(directory)

    cat._check_for_changes = broken_check  # type: ignore[assignment]
    cat.start_watching(tmp, poll_interval=0.05)
    try:
        time.sleep(0.3)
        # Should not crash — watcher continues running
        assert cat._watcher_thread is not None
        assert cat._watcher_thread.is_alive()
    finally:
        cat.stop_watching()


# --- Line 152: _check_for_changes returns if directory doesn't exist ---

def test_check_for_changes_nonexistent_dir() -> None:
    """Line 152: non-existent directory -> early return."""
    cat = SkillCatalog()
    # Should not raise
    cat._check_for_changes(Path("/nonexistent/dir/that/does/not/exist"))


# --- Line 162: _check_for_changes reloads modified file ---

def test_check_for_changes_reloads_modified_file() -> None:
    """Line 162: skill_def is not None -> replace + re-register."""
    tmp = tempfile.mkdtemp()
    skill_file = Path(tmp) / "greet.md"
    skill_file.write_text(_VALID_SKILL_MD)

    cat = SkillCatalog()
    count = cat.load_directory(tmp)
    assert count == 1

    # Modify the file (bump mtime)
    time.sleep(0.05)
    skill_file.write_text(
        "---\nname: greet\ndescription: Updated greeting\ngroups: [chat]\n"
        "parameters:\n  type: object\n  properties:\n    name:\n      type: string\n"
        "---\nUpdated body.\n"
    )

    cat._check_for_changes(Path(tmp))
    result = cat.resolve("greet")
    assert result is not None
    assert result.definition.description == "Updated greeting"


# --- Lines 173-174: _check_for_changes catches exception during reload ---

def test_check_for_changes_catches_reload_exception() -> None:
    """Lines 173-174: exception during file read/parse -> warning, continue."""
    tmp = tempfile.mkdtemp()
    skill_file = Path(tmp) / "greet.md"
    skill_file.write_text(_VALID_SKILL_MD)

    cat = SkillCatalog()
    cat.load_directory(tmp)

    # Make the file unreadable by replacing read_text to raise
    time.sleep(0.05)
    # Write something that will force a new mtime but cause parse to fail
    skill_file.write_text("---\n: invalid yaml [[\n---\nBody.\n")

    # Should not raise
    cat._check_for_changes(Path(tmp))


# --- _is_visible edge cases ---

def test_is_visible_tenant_with_empty_tenant_id() -> None:
    """_is_visible: tenant-scoped entry not visible when tenant_id is empty."""
    entry = _entry("tool", scope="tenant", tenant_id="acme")
    assert _is_visible(entry, tenant_id="", user_id="") is False


def test_is_visible_user_with_empty_user_id() -> None:
    """_is_visible: user-scoped entry not visible when user_id is empty."""
    entry = _entry("tool", scope="user", user_id="alice")
    assert _is_visible(entry, tenant_id="", user_id="") is False
