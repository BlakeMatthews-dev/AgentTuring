"""Spec tests for skill loader — behavioral tests from specs/skills_loader.md.

Focuses on uncovered branches: OSError at top-level (warns) vs community (silent).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import pytest

from stronghold.skills.loader import FilesystemSkillLoader
from stronghold.types.skill import SkillDefinition
from stronghold.types.tool import ToolDefinition

_SKILL_CONTENT_TEMPLATE = """---
name: {name}
description: {name} tool.
groups: [general]
parameters:
  type: object
  properties:
    query:
      type: string
  required:
    - query
endpoint: ""
---

Use this tool.
"""


def _write_skill(path: Path, name: str) -> None:
    path.write_text(_SKILL_CONTENT_TEMPLATE.format(name=name), encoding="utf-8")


class TestLoadAllDirExistence:
    def test_returns_empty_when_dir_missing(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        loader = FilesystemSkillLoader(tmp_path / "nope")
        with caplog.at_level(logging.DEBUG, logger="stronghold.skills.loader"):
            skills = loader.load_all()
        assert skills == []
        assert any("does not exist" in r.message for r in caplog.records)


class TestLoadAllOrdering:
    def test_top_level_sorted_alphabetically(self, tmp_path: Path) -> None:
        _write_skill(tmp_path / "zeta.md", "zeta")
        _write_skill(tmp_path / "alpha.md", "alpha")
        loader = FilesystemSkillLoader(tmp_path)
        skills = loader.load_all()
        assert [s.name for s in skills] == ["alpha", "zeta"]

    def test_top_level_before_community(self, tmp_path: Path) -> None:
        _write_skill(tmp_path / "alpha.md", "alpha")
        (tmp_path / "community").mkdir()
        _write_skill(tmp_path / "community" / "beta.md", "beta")
        loader = FilesystemSkillLoader(tmp_path)
        skills = loader.load_all()
        assert [s.name for s in skills] == ["alpha", "beta"]


class TestLoadAllSymlinks:
    def test_skips_symlinks_with_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        real = tmp_path / "real.md"
        _write_skill(real, "real")
        link = tmp_path / "link.md"
        try:
            os.symlink(real, link)
        except (OSError, NotImplementedError):
            pytest.skip("Symlink creation not supported")
        with caplog.at_level(logging.WARNING, logger="stronghold.skills.loader"):
            skills = FilesystemSkillLoader(tmp_path).load_all()
        # Only the real skill loads once; symlink is skipped.
        assert len(skills) == 1
        assert skills[0].name == "real"
        assert any(
            "Skipping symlink in skills dir" in r.message for r in caplog.records
        )


class TestLoadAllTopLevelErrors:
    def test_top_level_unreadable_logs_warning(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Lines 43-45: OSError on top-level warns + skips."""
        bad = tmp_path / "bad.md"
        bad.write_text("placeholder")
        good = tmp_path / "good.md"
        _write_skill(good, "good")

        real_read_text = Path.read_text

        def fake_read_text(self: Path, *args: Any, **kwargs: Any) -> str:
            if self == bad:
                raise OSError("simulated permission denied")
            return real_read_text(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", fake_read_text)

        with caplog.at_level(logging.WARNING, logger="stronghold.skills.loader"):
            skills = FilesystemSkillLoader(tmp_path).load_all()

        names = [s.name for s in skills]
        assert "good" in names
        assert len(skills) == 1
        assert any("Cannot read skill file" in r.message for r in caplog.records)

    def test_top_level_invalid_logs_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        (tmp_path / "broken.md").write_text("not-frontmatter")
        with caplog.at_level(logging.WARNING, logger="stronghold.skills.loader"):
            skills = FilesystemSkillLoader(tmp_path).load_all()
        assert skills == []
        assert any(
            "Invalid skill file (parse failed)" in r.message for r in caplog.records
        )


class TestLoadAllCommunityErrors:
    def test_community_unreadable_silently_skipped(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Lines 61-62: OSError on community file is SILENTLY skipped.

        Contract asymmetry (documented bug/quirk): community errors lack the
        warning log that top-level errors produce. Verified, not fixed.
        """
        community = tmp_path / "community"
        community.mkdir()
        bad = community / "bad.md"
        bad.write_text("placeholder")
        good = community / "good.md"
        _write_skill(good, "good")

        real_read_text = Path.read_text

        def fake_read_text(self: Path, *args: Any, **kwargs: Any) -> str:
            if self == bad:
                raise OSError("simulated denied")
            return real_read_text(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", fake_read_text)

        with caplog.at_level(logging.WARNING, logger="stronghold.skills.loader"):
            skills = FilesystemSkillLoader(tmp_path).load_all()

        assert [s.name for s in skills] == ["good"]
        # Asymmetry: community file read-errors produce NO warning log.
        assert not any(
            "Cannot read skill file" in r.message and str(bad) in r.message
            for r in caplog.records
        )

    def test_community_parse_failure_silently_skipped(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        community = tmp_path / "community"
        community.mkdir()
        (community / "broken.md").write_text("not a skill")
        with caplog.at_level(logging.WARNING, logger="stronghold.skills.loader"):
            skills = FilesystemSkillLoader(tmp_path).load_all()
        assert skills == []
        # Community parse-failures are silently swallowed.
        assert not any("Invalid skill file" in r.message for r in caplog.records)


class TestLoadAllInfoLog:
    def test_info_log_has_correct_count(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        _write_skill(tmp_path / "aa.md", "aa")
        _write_skill(tmp_path / "bb.md", "bb")
        (tmp_path / "community").mkdir()
        _write_skill(tmp_path / "community" / "cc.md", "cc")

        with caplog.at_level(logging.INFO, logger="stronghold.skills.loader"):
            skills = FilesystemSkillLoader(tmp_path).load_all()

        assert len(skills) == 3
        assert any("Loaded 3 skills from" in r.message for r in caplog.records)


class TestMergeIntoTools:
    def _skill(self, **overrides: Any) -> SkillDefinition:
        defaults: dict[str, Any] = {
            "name": "foo",
            "description": "d",
            "groups": ("general",),
            "parameters": {"type": "object", "properties": {}},
            "endpoint": "",
            "auth_key_env": "",
        }
        defaults.update(overrides)
        return SkillDefinition(**defaults)

    def test_merge_adds_new_skill_as_tool(self, tmp_path: Path) -> None:
        loader = FilesystemSkillLoader(tmp_path)
        skills = [self._skill(name="foo")]
        existing: list[ToolDefinition] = []
        tools = loader.merge_into_tools(skills, existing)
        assert len(tools) == 1
        assert tools[0].name == "foo"
        assert existing == []
        assert len(skills) == 1

    def test_merge_skips_when_tool_exists_with_debug_log(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        loader = FilesystemSkillLoader(tmp_path)
        existing = [ToolDefinition(name="foo", description="orig")]
        skills = [self._skill(name="foo", description="new")]
        with caplog.at_level(logging.DEBUG, logger="stronghold.skills.loader"):
            tools = loader.merge_into_tools(skills, existing)
        assert len(tools) == 1
        assert tools[0].description == "orig"
        assert any(
            "Skill 'foo' skipped (tool already exists)" in r.message
            for r in caplog.records
        )

    def test_merge_dedupes_within_skills_list(self, tmp_path: Path) -> None:
        loader = FilesystemSkillLoader(tmp_path)
        skills = [
            self._skill(name="foo", description="first"),
            self._skill(name="foo", description="second"),
        ]
        tools = loader.merge_into_tools(skills, [])
        assert len(tools) == 1
        assert tools[0].description == "first"

    def test_merge_preserves_skill_fields(self, tmp_path: Path) -> None:
        loader = FilesystemSkillLoader(tmp_path)
        skill = self._skill(
            name="foo",
            description="d",
            groups=("general",),
            parameters={"type": "object", "properties": {}},
            endpoint="",
            auth_key_env="FOO_TOKEN",
        )
        tools = loader.merge_into_tools([skill], [])
        t = tools[0]
        assert t.name == "foo"
        assert t.description == "d"
        assert t.groups == ("general",)
        assert t.parameters == {"type": "object", "properties": {}}
        assert t.endpoint == ""
        assert t.auth_key_env == "FOO_TOKEN"

    def test_merge_does_not_mutate_inputs(self, tmp_path: Path) -> None:
        loader = FilesystemSkillLoader(tmp_path)
        existing = [ToolDefinition(name="builtin", description="x")]
        skills = [self._skill(name="foo")]
        original_existing_id = id(existing)
        original_existing_len = len(existing)
        tools = loader.merge_into_tools(skills, existing)
        assert id(tools) != original_existing_id
        assert len(existing) == original_existing_len
