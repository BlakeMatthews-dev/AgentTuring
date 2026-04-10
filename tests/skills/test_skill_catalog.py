"""Tests for SkillCatalog (ADR-K8S-022)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from stronghold.skills.catalog import SkillCatalog, SkillCatalogEntry
from stronghold.types.skill import SkillDefinition


def _skill(name: str) -> SkillDefinition:
    return SkillDefinition(name=name, description=f"{name} skill")


def _entry(name: str, scope: str = "builtin", tenant_id: str = "", user_id: str = "") -> SkillCatalogEntry:
    return SkillCatalogEntry(
        definition=_skill(name), scope=scope, tenant_id=tenant_id, user_id=user_id,
    )


def test_register_and_resolve_builtin() -> None:
    cat = SkillCatalog()
    cat.register(_entry("summarize"))
    result = cat.resolve("summarize")
    assert result is not None
    assert result.definition.name == "summarize"


def test_resolve_unknown_returns_none() -> None:
    cat = SkillCatalog()
    assert cat.resolve("nonexistent") is None


def test_tenant_override_shadows_builtin() -> None:
    cat = SkillCatalog()
    cat.register(_entry("translate", scope="builtin"))
    cat.register(_entry("translate", scope="tenant", tenant_id="acme"))
    result = cat.resolve("translate", tenant_id="acme")
    assert result is not None
    assert result.scope == "tenant"


def test_user_override_shadows_tenant() -> None:
    cat = SkillCatalog()
    cat.register(_entry("translate", scope="builtin"))
    cat.register(_entry("translate", scope="tenant", tenant_id="acme"))
    cat.register(_entry("translate", scope="user", user_id="alice"))
    result = cat.resolve("translate", user_id="alice")
    assert result is not None
    assert result.scope == "user"


def test_list_skills_cascaded_dedup() -> None:
    cat = SkillCatalog()
    cat.register(_entry("summarize", scope="builtin"))
    cat.register(_entry("translate", scope="builtin"))
    cat.register(_entry("translate", scope="tenant", tenant_id="acme"))
    skills = cat.list_skills(tenant_id="acme")
    names = [s.definition.name for s in skills]
    assert sorted(names) == ["summarize", "translate"]
    translate = next(s for s in skills if s.definition.name == "translate")
    assert translate.scope == "tenant"


def test_tenant_skill_not_visible_to_other_tenant() -> None:
    cat = SkillCatalog()
    cat.register(_entry("secret", scope="tenant", tenant_id="acme"))
    result = cat.resolve("secret", tenant_id="other-corp")
    assert result is None


def test_load_directory() -> None:
    tmp = tempfile.mkdtemp()
    skill_file = Path(tmp) / "greet.md"
    skill_file.write_text(
        "---\nname: greet\ndescription: Greet the user\ngroups: [chat]\nparameters:\n  type: object\n  properties:\n    name:\n      type: string\n---\nSay hello warmly.\n"
    )
    cat = SkillCatalog()
    count = cat.load_directory(tmp)
    assert count == 1
    result = cat.resolve("greet")
    assert result is not None
    assert result.definition.name == "greet"


def test_load_directory_nonexistent() -> None:
    cat = SkillCatalog()
    assert cat.load_directory("/nonexistent/path") == 0


def test_filesystem_watcher_detects_new_file() -> None:
    import time

    tmp = tempfile.mkdtemp()
    cat = SkillCatalog()
    cat.start_watching(tmp, poll_interval=0.1)
    try:
        # Write a skill file
        skill_file = Path(tmp) / "hello.md"
        skill_file.write_text(
            "---\nname: hello\ndescription: Say hello\ngroups: [chat]\nparameters:\n  type: object\n  properties:\n    target:\n      type: string\n---\nHello!\n"
        )
        # Give watcher time to detect
        time.sleep(0.5)
        result = cat.resolve("hello")
        assert result is not None
        assert result.definition.name == "hello"
    finally:
        cat.stop_watching()


# ── Coverage gap tests ──────────────────────────────────────────────


def test_load_directory_skips_invalid_yaml() -> None:
    """Invalid skill files are logged and skipped, not fatal."""
    import tempfile
    tmp = tempfile.mkdtemp()
    # Missing required fields
    (Path(tmp) / "bad.md").write_text("not a skill file at all")
    # Valid skill alongside
    (Path(tmp) / "good.md").write_text(
        "---\nname: good\ndescription: valid\ngroups: [chat]\n"
        "parameters:\n  type: object\n  properties: {}\n---\nOK\n"
    )
    cat = SkillCatalog()
    count = cat.load_directory(tmp)
    assert count == 1  # only the good one
    assert cat.resolve("good") is not None
    assert cat.resolve("bad") is None


def test_load_directory_handles_read_exception() -> None:
    """Files that raise on read are skipped, not fatal."""
    import tempfile
    tmp = tempfile.mkdtemp()
    (Path(tmp) / "ok.md").write_text(
        "---\nname: ok\ndescription: ok\ngroups: [chat]\n"
        "parameters:\n  type: object\n  properties: {}\n---\nok\n"
    )
    # Non-readable file — simulate by making it a directory with .md extension
    (Path(tmp) / "broken.md").mkdir()
    cat = SkillCatalog()
    # Should not raise
    count = cat.load_directory(tmp)
    assert count == 1


def test_start_watching_idempotent() -> None:
    """Calling start_watching twice should not spawn a second thread."""
    import tempfile
    tmp = tempfile.mkdtemp()
    cat = SkillCatalog()
    cat.start_watching(tmp, poll_interval=0.1)
    thread1 = cat._watcher_thread
    cat.start_watching(tmp, poll_interval=0.1)  # Should be no-op
    thread2 = cat._watcher_thread
    assert thread1 is thread2
    cat.stop_watching()


def test_stop_watching_without_start_is_noop() -> None:
    cat = SkillCatalog()
    cat.stop_watching()  # should not raise


def test_watcher_nonexistent_dir_does_not_crash() -> None:
    """Watcher pointed at a missing dir should log and continue."""
    cat = SkillCatalog()
    cat.start_watching("/nonexistent/skill/path", poll_interval=0.05)
    import time
    time.sleep(0.15)
    cat.stop_watching()
    # No crash is the assertion


def test_watcher_updates_existing_skill() -> None:
    """Modifying a skill file on disk should reload it in the catalog."""
    import tempfile
    import time
    tmp = tempfile.mkdtemp()
    skill_file = Path(tmp) / "ping.md"
    skill_file.write_text(
        "---\nname: ping\ndescription: v1\ngroups: [chat]\n"
        "parameters:\n  type: object\n  properties: {}\n---\nv1\n"
    )
    cat = SkillCatalog()
    cat.load_directory(tmp)
    v1 = cat.resolve("ping")
    assert v1 is not None
    assert v1.definition.description == "v1"

    cat.start_watching(tmp, poll_interval=0.05)
    try:
        # Wait past mtime granularity
        time.sleep(1.1)
        skill_file.write_text(
            "---\nname: ping\ndescription: v2\ngroups: [chat]\n"
            "parameters:\n  type: object\n  properties: {}\n---\nv2\n"
        )
        # Poll until watcher detects
        for _ in range(40):
            v = cat.resolve("ping")
            if v is not None and v.definition.description == "v2":
                break
            time.sleep(0.05)
        final = cat.resolve("ping")
        assert final is not None
        assert final.definition.description == "v2"
    finally:
        cat.stop_watching()
