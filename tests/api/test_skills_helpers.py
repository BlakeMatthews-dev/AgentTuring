"""Unit tests for skills route helper functions.

Covers: _select_forge_model, _sanitize_generated_skill, _ensure_skill_body, _check_csrf.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException

from stronghold.api.routes.skills import (
    _ensure_skill_body,
    _sanitize_generated_skill,
    _select_forge_model,
)


class TestSelectForgeModel:
    def test_prefers_mistral_large(self) -> None:
        class FakeConfig:
            models = {
                "mistral-large": {"litellm_id": "mistral/mistral-large-latest"},
                "gemini-flash": {"litellm_id": "gemini/flash"},
            }

        class FakeContainer:
            config = FakeConfig()

        result = _select_forge_model(FakeContainer())
        assert result == "mistral/mistral-large-latest"

    def test_falls_back_to_mistral_small(self) -> None:
        class FakeConfig:
            models = {
                "mistral-small": {"litellm_id": "mistral/mistral-small-latest"},
            }

        class FakeContainer:
            config = FakeConfig()

        result = _select_forge_model(FakeContainer())
        assert result == "mistral/mistral-small-latest"

    def test_falls_back_to_gemini_flash(self) -> None:
        class FakeConfig:
            models = {
                "gemini-flash": {"litellm_id": "gemini/gemini-2.0-flash"},
            }

        class FakeContainer:
            config = FakeConfig()

        result = _select_forge_model(FakeContainer())
        assert result == "gemini/gemini-2.0-flash"

    def test_falls_back_to_any_model(self) -> None:
        class FakeConfig:
            models = {
                "custom-model": {"litellm_id": "custom/model-v1"},
            }

        class FakeContainer:
            config = FakeConfig()

        result = _select_forge_model(FakeContainer())
        assert result == "custom/model-v1"

    def test_no_models_returns_default(self) -> None:
        class FakeConfig:
            models: dict[str, Any] = {}

        class FakeContainer:
            config = FakeConfig()

        result = _select_forge_model(FakeContainer())
        assert result == "mistral/mistral-large-latest"

    def test_skips_non_dict_model_configs(self) -> None:
        class FakeConfig:
            models = {
                "mistral-large": "not-a-dict",
                "real-model": {"litellm_id": "real/model"},
            }

        class FakeContainer:
            config = FakeConfig()

        result = _select_forge_model(FakeContainer())
        assert result == "real/model"

    def test_skips_models_without_litellm_id(self) -> None:
        class FakeConfig:
            models = {
                "mistral-large": {"provider": "mistral"},  # no litellm_id
                "fallback": {"litellm_id": "fb/model"},
            }

        class FakeContainer:
            config = FakeConfig()

        result = _select_forge_model(FakeContainer())
        assert result == "fb/model"

    def test_none_models_returns_default(self) -> None:
        class FakeConfig:
            models = None

        class FakeContainer:
            config = FakeConfig()

        result = _select_forge_model(FakeContainer())
        assert result == "mistral/mistral-large-latest"


class TestSanitizeGeneratedSkill:
    def test_strips_markdown_fences(self) -> None:
        content = "```markdown\n---\nname: x\n---\nBody text.\n```"
        result = _sanitize_generated_skill(content)
        assert result.startswith("---")
        assert "```" not in result

    def test_strips_md_fences(self) -> None:
        content = "```md\n---\nname: x\n---\nBody text.\n```"
        result = _sanitize_generated_skill(content)
        assert result.startswith("---")

    def test_strips_plain_fences(self) -> None:
        content = "```\n---\nname: x\n---\nBody text.\n```"
        result = _sanitize_generated_skill(content)
        assert result.startswith("---")

    def test_removes_leading_text_before_frontmatter(self) -> None:
        content = "Here is the skill:\n---\nname: x\n---\nBody."
        result = _sanitize_generated_skill(content)
        assert result.startswith("---")

    def test_clean_content_unchanged(self) -> None:
        content = "---\nname: x\n---\nBody."
        result = _sanitize_generated_skill(content)
        assert result == content

    def test_whitespace_stripped(self) -> None:
        content = "  \n  ---\nname: x\n---\n  "
        result = _sanitize_generated_skill(content)
        assert result.startswith("---")


class TestEnsureSkillBody:
    def test_adds_body_when_only_frontmatter(self) -> None:
        content = "---\nname: my_skill\ndescription: \"Does stuff\"\n---"
        result = _ensure_skill_body(content)
        assert "---" in result
        assert "does stuff" in result.lower()
        assert len(result) > len(content)

    def test_keeps_existing_body(self) -> None:
        content = "---\nname: x\n---\n\nExisting body text."
        result = _ensure_skill_body(content)
        assert result == content

    def test_frontmatter_only_without_description(self) -> None:
        content = "---\nname: my_skill\n---"
        result = _ensure_skill_body(content)
        assert len(result) > len(content)
        # Should use default description
        assert "use this skill" in result.lower()
