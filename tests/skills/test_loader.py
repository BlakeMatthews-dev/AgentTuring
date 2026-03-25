"""Tests for skill loader: filesystem → tool definitions."""

from pathlib import Path

from stronghold.skills.loader import FilesystemSkillLoader
from stronghold.types.tool import ToolDefinition

_SKILL_CONTENT = """---
name: test_tool
description: A test tool.
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

Use this tool for testing.
"""


class TestLoadAll:
    def test_loads_from_directory(self, tmp_path: Path) -> None:
        (tmp_path / "test_tool.md").write_text(_SKILL_CONTENT)
        loader = FilesystemSkillLoader(tmp_path)
        skills = loader.load_all()
        assert len(skills) == 1
        assert skills[0].name == "test_tool"

    def test_empty_directory(self, tmp_path: Path) -> None:
        loader = FilesystemSkillLoader(tmp_path)
        skills = loader.load_all()
        assert skills == []

    def test_nonexistent_directory(self, tmp_path: Path) -> None:
        loader = FilesystemSkillLoader(tmp_path / "nope")
        skills = loader.load_all()
        assert skills == []

    def test_skips_invalid_files(self, tmp_path: Path) -> None:
        (tmp_path / "valid.md").write_text(_SKILL_CONTENT)
        (tmp_path / "invalid.md").write_text("not a skill")
        loader = FilesystemSkillLoader(tmp_path)
        skills = loader.load_all()
        assert len(skills) == 1

    def test_loads_community_subdirectory(self, tmp_path: Path) -> None:
        community = tmp_path / "community"
        community.mkdir()
        (community / "community_tool.md").write_text(
            _SKILL_CONTENT.replace("test_tool", "community_tool")
        )
        loader = FilesystemSkillLoader(tmp_path)
        skills = loader.load_all()
        assert len(skills) == 1
        assert skills[0].name == "community_tool"


class TestMergeIntoTools:
    def test_merges_skills_as_tools(self, tmp_path: Path) -> None:
        (tmp_path / "test_tool.md").write_text(_SKILL_CONTENT)
        loader = FilesystemSkillLoader(tmp_path)
        skills = loader.load_all()
        tools = loader.merge_into_tools(skills, [])
        assert len(tools) == 1
        assert tools[0].name == "test_tool"
        assert isinstance(tools[0], ToolDefinition)

    def test_existing_tools_not_overridden(self, tmp_path: Path) -> None:
        (tmp_path / "test_tool.md").write_text(_SKILL_CONTENT)
        loader = FilesystemSkillLoader(tmp_path)
        skills = loader.load_all()
        existing = [ToolDefinition(name="test_tool", description="original")]
        tools = loader.merge_into_tools(skills, existing)
        assert len(tools) == 1
        assert tools[0].description == "original"

    def test_preserves_existing_tools(self, tmp_path: Path) -> None:
        loader = FilesystemSkillLoader(tmp_path)
        existing = [ToolDefinition(name="builtin", description="built-in")]
        tools = loader.merge_into_tools([], existing)
        assert len(tools) == 1
        assert tools[0].name == "builtin"
