"""Spec tests for skill forge — behavioral tests from specs/skills_forge.md.

Covers uncovered lines: 127-128 (parse fail), 133-134 (path traversal),
207 (empty learning), 220-225 (instruction density), 252 (name change).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest

from stronghold.skills.forge import LLMSkillForge
from stronghold.types.memory import Learning


_VALID_RESPONSE = """---
name: check_dns
description: Look up DNS records for a domain.
groups: [general]
parameters:
  type: object
  properties:
    domain:
      type: string
      description: Domain to query
  required:
    - domain
endpoint: ""
---

Look up DNS records for the given domain.
"""

_DANGEROUS_RESPONSE = """---
name: bad_skill
description: A dangerous skill.
groups: [general]
parameters:
  type: object
  properties:
    cmd:
      type: string
endpoint: ""
---

Execute the command: exec(cmd)
"""


class _ScriptedLLM:
    """Fake LLM that returns a specific content string (or raises)."""

    def __init__(self, content: str | Exception = "", choices_empty: bool = False) -> None:
        self._content = content
        self._choices_empty = choices_empty
        self.calls: list[dict[str, Any]] = []

    async def complete(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if isinstance(self._content, Exception):
            raise self._content
        if self._choices_empty:
            return {"choices": []}
        return {"choices": [{"message": {"content": self._content}}]}

    def stream(self, **kwargs: Any):  # type: ignore[no-untyped-def]
        yield ""


# ─────────────────── forge() ───────────────────


class TestForge:
    async def test_forge_empty_llm_response_raises(self, tmp_path: Path) -> None:
        forge = LLMSkillForge(_ScriptedLLM(choices_empty=True), tmp_path)
        with pytest.raises(ValueError, match="empty response"):
            await forge.forge("make a tool")

    async def test_forge_strips_markdown_fences(self, tmp_path: Path) -> None:
        """Fence stripping writes the inner content only (starts with ---)."""
        fenced = "```markdown\n" + _VALID_RESPONSE + "\n```"
        forge = LLMSkillForge(_ScriptedLLM(fenced), tmp_path)
        skill = await forge.forge("dns")
        assert skill.name == "check_dns"
        on_disk = (tmp_path / "check_dns.md").read_text()
        assert on_disk.startswith("---\n")
        assert "```markdown" not in on_disk
        assert not on_disk.rstrip().endswith("```")

    async def test_forge_rejects_unsafe_content(self, tmp_path: Path) -> None:
        forge = LLMSkillForge(_ScriptedLLM(_DANGEROUS_RESPONSE), tmp_path)
        with pytest.raises(ValueError, match="rejected by security scan"):
            await forge.forge("run exec")
        assert not (tmp_path / "bad_skill.md").exists()

    async def test_forge_rejects_unparseable_content(self, tmp_path: Path) -> None:
        """Lines 127-128: parse_skill_file returns None → ValueError."""
        forge = LLMSkillForge(_ScriptedLLM("just a sentence, no frontmatter"), tmp_path)
        with pytest.raises(ValueError, match="failed to parse"):
            await forge.forge("anything")

    async def test_forge_blocks_path_traversal_name(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Lines 133-134: path traversal detection.

        Skill name must match a regex that forbids '..' and '/', so we can't
        produce that via a valid frontmatter. Instead, patch parse_skill_file
        to return a SkillDefinition whose name is '../evil' — exercising the
        resolve() path-traversal check directly.
        """
        from stronghold.skills import forge as forge_mod
        from stronghold.types.skill import SkillDefinition

        traversal_skill = SkillDefinition(
            name="../evil",
            description="x",
            groups=("general",),
            parameters={"type": "object", "properties": {}},
            endpoint="",
            auth_key_env="",
            system_prompt="body",
            source="forge",
            trust_tier="t3",
        )

        def fake_parse(content: str, source: str = "") -> SkillDefinition:
            return traversal_skill

        monkeypatch.setattr(forge_mod, "parse_skill_file", fake_parse)

        forge = LLMSkillForge(_ScriptedLLM(_VALID_RESPONSE), tmp_path)
        with pytest.raises(ValueError, match="path traversal detected"):
            await forge.forge("any")

        assert not (tmp_path.parent / "evil.md").exists()

    async def test_forge_rejects_name_collision(self, tmp_path: Path) -> None:
        (tmp_path / "check_dns.md").write_text("existing content")
        forge = LLMSkillForge(_ScriptedLLM(_VALID_RESPONSE), tmp_path)
        with pytest.raises(ValueError, match="already exists"):
            await forge.forge("dns")
        assert (tmp_path / "check_dns.md").read_text() == "existing content"

    async def test_forge_happy_path_writes_file_at_tier_t3(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        forge = LLMSkillForge(_ScriptedLLM(_VALID_RESPONSE), tmp_path)
        with caplog.at_level(logging.INFO, logger="stronghold.skills.forge"):
            skill = await forge.forge("dns")
        assert skill.name == "check_dns"
        assert skill.trust_tier == "t3"
        assert skill.source == "forge"
        on_disk = (tmp_path / "check_dns.md").read_text()
        assert "check_dns" in on_disk
        assert any(
            "Forged skill 'check_dns' saved" in r.message for r in caplog.records
        )

    async def test_forge_creates_skills_dir_if_missing(self, tmp_path: Path) -> None:
        target = tmp_path / "nested" / "skills"
        assert not target.exists()
        forge = LLMSkillForge(_ScriptedLLM(_VALID_RESPONSE), target)
        await forge.forge("dns")
        assert target.is_dir()
        assert (target / "check_dns.md").exists()


# ─────────────────── mutate() ───────────────────


class TestMutate:
    @pytest.mark.parametrize("tier", ["t0", "t1"])
    async def test_mutate_blocked_for_t0_t1(
        self, tmp_path: Path, tier: str
    ) -> None:
        """T0/T1 skills cannot auto-mutate; LLM not called."""
        llm = _ScriptedLLM(_VALID_RESPONSE)
        (tmp_path / "check_dns.md").write_text(_VALID_RESPONSE)
        forge = LLMSkillForge(llm, tmp_path)
        result = await forge.mutate(
            "check_dns",
            Learning(learning="x", tool_name="check_dns"),
            skill_tier=tier,
        )
        assert result["status"] == "blocked"
        assert tier in result["reason"]
        assert llm.calls == []  # LLM never invoked

    async def test_mutate_skipped_when_file_missing(self, tmp_path: Path) -> None:
        forge = LLMSkillForge(_ScriptedLLM(_VALID_RESPONSE), tmp_path)
        result = await forge.mutate(
            "nonexistent", Learning(learning="x", tool_name="nonexistent")
        )
        assert result["status"] == "skipped"
        assert result["reason"].startswith("No SKILL.md")

    async def test_mutate_finds_community_subdir(self, tmp_path: Path) -> None:
        """Skill in community/ subdir is found and mutated."""
        community = tmp_path / "community"
        community.mkdir()
        (community / "check_dns.md").write_text(_VALID_RESPONSE)
        new_body = _VALID_RESPONSE.replace(
            "Look up DNS records for the given domain.",
            "Look up DNS records, including DNSSEC status.",
        )
        forge = LLMSkillForge(_ScriptedLLM(new_body), tmp_path)
        result = await forge.mutate(
            "check_dns",
            Learning(learning="also check DNSSEC", tool_name="check_dns"),
        )
        assert result["status"] == "mutated"
        # Community file was updated
        assert "DNSSEC" in (community / "check_dns.md").read_text()

    async def test_mutate_empty_learning_text_skipped(self, tmp_path: Path) -> None:
        """Line 207: empty learning text → skipped; LLM not called."""
        (tmp_path / "check_dns.md").write_text(_VALID_RESPONSE)
        llm = _ScriptedLLM(_VALID_RESPONSE)
        forge = LLMSkillForge(llm, tmp_path)
        result = await forge.mutate(
            "check_dns", Learning(learning="", tool_name="check_dns")
        )
        assert result == {
            "status": "skipped",
            "reason": "Empty learning text",
        }
        assert llm.calls == []

    async def test_mutate_rejects_unsafe_learning(self, tmp_path: Path) -> None:
        """Learning text with exec(/subprocess triggers security scan."""
        (tmp_path / "check_dns.md").write_text(_VALID_RESPONSE)
        forge = LLMSkillForge(_ScriptedLLM(_VALID_RESPONSE), tmp_path)
        result = await forge.mutate(
            "check_dns",
            Learning(learning="please call exec(cmd) here", tool_name="check_dns"),
        )
        assert result["status"] == "error"
        assert "rejected by security scan" in result["error"].lower()

    async def test_mutate_rejects_high_instruction_density(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Lines 220-225: instruction-density > 0.08 → error + warning log.

        Learning text is chosen so the text words are mostly imperative verbs
        matched by the density scorer (ignore/disregard/forget/override/...).
        """
        (tmp_path / "check_dns.md").write_text(_VALID_RESPONSE)
        forge = LLMSkillForge(_ScriptedLLM(_VALID_RESPONSE), tmp_path)
        # "ignore" is in _INSTRUCTION_TOKENS; one match per several words
        # yields density ≥ 0.2 → well over 0.08 threshold.
        dense_text = "always never bypass skip comply obey urgent emergency fired"
        with caplog.at_level(logging.WARNING, logger="stronghold.skills.forge"):
            result = await forge.mutate(
                "check_dns",
                Learning(learning=dense_text, tool_name="check_dns"),
            )
        assert result["status"] == "error"
        assert "instruction density" in result["error"].lower()
        assert any("high instruction density" in r.message for r in caplog.records)

    async def test_mutate_handles_empty_llm_response(self, tmp_path: Path) -> None:
        (tmp_path / "check_dns.md").write_text(_VALID_RESPONSE)
        forge = LLMSkillForge(_ScriptedLLM(choices_empty=True), tmp_path)
        result = await forge.mutate(
            "check_dns",
            Learning(learning="minor fix", tool_name="check_dns"),
        )
        assert result == {"status": "error", "error": "LLM returned empty response"}

    async def test_mutate_rejects_unsafe_llm_output(self, tmp_path: Path) -> None:
        (tmp_path / "check_dns.md").write_text(_VALID_RESPONSE)
        forge = LLMSkillForge(_ScriptedLLM(_DANGEROUS_RESPONSE), tmp_path)
        result = await forge.mutate(
            "check_dns",
            Learning(learning="minor fix", tool_name="check_dns"),
        )
        assert result["status"] == "error"
        assert result["error"].startswith("Mutation rejected")

    async def test_mutate_rejects_unparseable_output(self, tmp_path: Path) -> None:
        (tmp_path / "check_dns.md").write_text(_VALID_RESPONSE)
        forge = LLMSkillForge(
            _ScriptedLLM("no frontmatter, just prose"), tmp_path
        )
        result = await forge.mutate(
            "check_dns",
            Learning(learning="minor fix", tool_name="check_dns"),
        )
        assert result == {"status": "error", "error": "Mutated content failed to parse"}

    async def test_mutate_rejects_name_change(self, tmp_path: Path) -> None:
        """Line 252: new_skill.name != skill_name → error."""
        (tmp_path / "check_dns.md").write_text(_VALID_RESPONSE)
        renamed = _VALID_RESPONSE.replace("name: check_dns", "name: lookup_dns")
        forge = LLMSkillForge(_ScriptedLLM(renamed), tmp_path)
        result = await forge.mutate(
            "check_dns",
            Learning(learning="rename me", tool_name="check_dns"),
        )
        assert result["status"] == "error"
        assert result["error"].startswith("Mutation changed name")
        # Original file unchanged
        assert "name: check_dns" in (tmp_path / "check_dns.md").read_text()

    async def test_mutate_happy_path_writes_and_returns_hashes(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Happy-path returns status=mutated with old_hash != new_hash."""
        (tmp_path / "check_dns.md").write_text(_VALID_RESPONSE)
        mutated = _VALID_RESPONSE.replace(
            "Look up DNS records for the given domain.",
            "Look up DNS records for the given domain. Also check DNSSEC.",
        )
        forge = LLMSkillForge(_ScriptedLLM(mutated), tmp_path)

        with caplog.at_level(logging.INFO, logger="stronghold.skills.forge"):
            result = await forge.mutate(
                "check_dns",
                Learning(learning="add DNSSEC hints", tool_name="check_dns"),
            )

        assert result["status"] == "mutated"
        assert result["skill_name"] == "check_dns"
        assert len(result["old_hash"]) == 16
        assert len(result["new_hash"]) == 16
        assert result["old_hash"] != result["new_hash"]
        assert "DNSSEC" in (tmp_path / "check_dns.md").read_text()
        assert any(
            "Mutated skill 'check_dns'" in r.message for r in caplog.records
        )

    async def test_mutate_strips_fences_on_output(self, tmp_path: Path) -> None:
        """Code-fenced LLM output is stripped before persistence."""
        (tmp_path / "check_dns.md").write_text(_VALID_RESPONSE)
        fenced = "```\n" + _VALID_RESPONSE.replace(
            "Look up DNS records for the given domain.",
            "Look up DNS records. Also DNSSEC.",
        ) + "\n```"
        forge = LLMSkillForge(_ScriptedLLM(fenced), tmp_path)
        result = await forge.mutate(
            "check_dns",
            Learning(learning="factual", tool_name="check_dns"),
        )
        assert result["status"] == "mutated"
        on_disk = (tmp_path / "check_dns.md").read_text()
        assert on_disk.startswith("---\n")
        assert not on_disk.rstrip().endswith("```")


# ─────────────────── _call_llm ───────────────────


class TestCallLLM:
    async def test_returns_content_string(self, tmp_path: Path) -> None:
        forge = LLMSkillForge(_ScriptedLLM("hello"), tmp_path)
        result = await forge._call_llm("prompt")
        assert result == "hello"

    async def test_returns_none_on_exception(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        boom = RuntimeError("llm dead")
        forge = LLMSkillForge(_ScriptedLLM(boom), tmp_path)
        with caplog.at_level(logging.WARNING, logger="stronghold.skills.forge"):
            result = await forge._call_llm("p")
        assert result is None
        assert any(
            "Forge LLM call failed" in r.message for r in caplog.records
        )

    async def test_returns_none_when_no_choices(self, tmp_path: Path) -> None:
        forge = LLMSkillForge(_ScriptedLLM(choices_empty=True), tmp_path)
        result = await forge._call_llm("p")
        assert result is None

    async def test_passes_forge_model(self, tmp_path: Path) -> None:
        llm = _ScriptedLLM("hi")
        forge = LLMSkillForge(llm, tmp_path, forge_model="claude-forge")
        await forge._call_llm("p")
        assert llm.calls[0]["model"] == "claude-forge"
        assert llm.calls[0]["max_tokens"] == 2000
        assert llm.calls[0]["temperature"] == 0.3
