"""Unit tests for the extracted PromptLibrary module."""

from __future__ import annotations

from stronghold.builders.pipeline.prompts import PromptLibrary
from tests.fakes import FakePromptManager


class TestRender:
    def test_single(self) -> None:
        assert PromptLibrary.render("Hello {{name}}", name="Ada") == "Hello Ada"

    def test_unmatched(self) -> None:
        assert PromptLibrary.render("{{x}}", y="1") == "{{x}}"


class TestGet:
    async def test_falls_back_to_defaults(self) -> None:
        lib = PromptLibrary(prompt_manager=FakePromptManager())
        result = await lib.get("builders.mason.write_first_test")
        assert len(result) > 0  # should get the default

    async def test_prefers_manager_over_default(self) -> None:
        pm = FakePromptManager()
        pm.seed("builders.custom", "my custom prompt")
        lib = PromptLibrary(prompt_manager=pm)
        result = await lib.get("builders.custom")
        assert result == "my custom prompt"


class TestSeedDefaults:
    async def test_seeds_into_manager(self) -> None:
        pm = FakePromptManager()
        lib = PromptLibrary(prompt_manager=pm)
        await lib.seed_defaults()
        # At least some defaults should be seeded
        result = await pm.get("builders.mason.write_first_test")
        assert len(result) > 0
