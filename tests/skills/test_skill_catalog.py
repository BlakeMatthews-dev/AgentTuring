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
    cat.start_watching(tmp, poll_interval=0.05)
    try:
        skill_file = Path(tmp) / "hello.md"
        skill_file.write_text(
            "---\nname: hello\ndescription: Say hello\ngroups: [chat]\nparameters:\n  type: object\n  properties:\n    target:\n      type: string\n---\nHello!\n"
        )
        # Poll until watcher picks it up (max 2s, not a fixed sleep)
        result = None
        for _ in range(40):
            result = cat.resolve("hello")
            if result is not None:
                break
            time.sleep(0.05)
        assert result is not None, "Watcher did not detect new file within 2s"
        assert result.definition.name == "hello"
    finally:
        cat.stop_watching()
