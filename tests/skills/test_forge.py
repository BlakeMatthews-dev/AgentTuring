"""Tests for skill forge: LLM-generated skills + mutation."""

from pathlib import Path
from typing import Any

import pytest

from stronghold.skills.forge import LLMSkillForge
from stronghold.types.memory import Learning

_VALID_SKILL_RESPONSE = """---
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

Look up DNS records for the given domain. Return A, AAAA, MX, and CNAME records.
"""

_DANGEROUS_SKILL_RESPONSE = """---
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


class FakeForgeClient:
    """Fake LLM that returns canned skill content."""

    def __init__(self, response: str = _VALID_SKILL_RESPONSE) -> None:
        self._response = response

    async def complete(self, **kwargs: Any) -> dict[str, Any]:
        return {"choices": [{"message": {"content": self._response}}]}

    def stream(self, **kwargs: Any):  # type: ignore[no-untyped-def]
        yield ""


class EmptyLLMClient:
    """Returns empty content."""

    async def complete(self, **kwargs: Any) -> dict[str, Any]:
        return {"choices": [{"message": {"content": ""}}]}

    def stream(self, **kwargs: Any):  # type: ignore[no-untyped-def]
        yield ""


class TestForgeSkill:
    @pytest.mark.asyncio
    async def test_forges_valid_skill(self, tmp_path: Path) -> None:
        forge = LLMSkillForge(FakeForgeClient(), tmp_path)
        skill = await forge.forge("Create a DNS lookup tool")
        assert skill.name == "check_dns"
        assert skill.trust_tier == "t3"  # Forged skills are T3
        assert (tmp_path / "check_dns.md").exists()

    @pytest.mark.asyncio
    async def test_rejects_dangerous_content(self, tmp_path: Path) -> None:
        forge = LLMSkillForge(FakeForgeClient(_DANGEROUS_SKILL_RESPONSE), tmp_path)
        with pytest.raises(ValueError, match="security scan"):
            await forge.forge("Create a command executor")

    @pytest.mark.asyncio
    async def test_rejects_empty_response(self, tmp_path: Path) -> None:
        forge = LLMSkillForge(EmptyLLMClient(), tmp_path)
        with pytest.raises(ValueError, match="empty response"):
            await forge.forge("anything")

    @pytest.mark.asyncio
    async def test_rejects_name_collision(self, tmp_path: Path) -> None:
        (tmp_path / "check_dns.md").write_text("existing")
        forge = LLMSkillForge(FakeForgeClient(), tmp_path)
        with pytest.raises(ValueError, match="already exists"):
            await forge.forge("Create DNS tool")

    @pytest.mark.asyncio
    async def test_strips_code_fences(self, tmp_path: Path) -> None:
        fenced = "```markdown\n" + _VALID_SKILL_RESPONSE + "\n```"
        forge = LLMSkillForge(FakeForgeClient(fenced), tmp_path)
        skill = await forge.forge("DNS tool")
        assert skill.name == "check_dns"


class TestMutateSkill:
    @pytest.mark.asyncio
    async def test_mutates_existing_skill(self, tmp_path: Path) -> None:
        # Write initial skill
        (tmp_path / "check_dns.md").write_text(_VALID_SKILL_RESPONSE)

        # Mutated response has same name + updated body
        mutated = _VALID_SKILL_RESPONSE.replace(
            "Return A, AAAA, MX, and CNAME records.",
            "Return A, AAAA, MX, and CNAME records. Also check for DNSSEC.",
        )
        forge = LLMSkillForge(FakeForgeClient(mutated), tmp_path)
        learning = Learning(
            learning="DNS queries should also check DNSSEC status",
            tool_name="check_dns",
        )
        result = await forge.mutate("check_dns", learning)
        assert result["status"] == "mutated"
        assert result["old_hash"] != result["new_hash"]

    @pytest.mark.asyncio
    async def test_mutation_missing_skill_skips(self, tmp_path: Path) -> None:
        forge = LLMSkillForge(FakeForgeClient(), tmp_path)
        learning = Learning(learning="test", tool_name="nonexistent")
        result = await forge.mutate("nonexistent", learning)
        assert result["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_mutation_empty_learning_skips(self, tmp_path: Path) -> None:
        (tmp_path / "check_dns.md").write_text(_VALID_SKILL_RESPONSE)
        forge = LLMSkillForge(FakeForgeClient(), tmp_path)
        learning = Learning(learning="", tool_name="check_dns")
        result = await forge.mutate("check_dns", learning)
        assert result["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_mutation_security_rejection(self, tmp_path: Path) -> None:
        (tmp_path / "check_dns.md").write_text(_VALID_SKILL_RESPONSE)
        forge = LLMSkillForge(FakeForgeClient(_DANGEROUS_SKILL_RESPONSE), tmp_path)
        learning = Learning(learning="add exec", tool_name="check_dns")
        result = await forge.mutate("check_dns", learning)
        assert result["status"] == "error"
        assert "rejected" in result.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_mutation_blocked_for_t0_skill(self, tmp_path: Path) -> None:
        """T0 built-in skills cannot be auto-mutated."""
        (tmp_path / "check_dns.md").write_text(_VALID_SKILL_RESPONSE)
        forge = LLMSkillForge(FakeForgeClient(), tmp_path)
        learning = Learning(learning="improvement", tool_name="check_dns")
        result = await forge.mutate("check_dns", learning, skill_tier="t0")
        assert result["status"] == "blocked"
        assert "t0" in result.get("reason", "").lower()

    @pytest.mark.asyncio
    async def test_mutation_blocked_for_t1_skill(self, tmp_path: Path) -> None:
        """T1 operator-vetted skills cannot be auto-mutated."""
        (tmp_path / "check_dns.md").write_text(_VALID_SKILL_RESPONSE)
        forge = LLMSkillForge(FakeForgeClient(), tmp_path)
        learning = Learning(learning="improvement", tool_name="check_dns")
        result = await forge.mutate("check_dns", learning, skill_tier="t1")
        assert result["status"] == "blocked"

    @pytest.mark.asyncio
    async def test_mutation_allowed_for_t2_skill(self, tmp_path: Path) -> None:
        """T2+ skills CAN be auto-mutated."""
        (tmp_path / "check_dns.md").write_text(_VALID_SKILL_RESPONSE)
        mutated = _VALID_SKILL_RESPONSE.replace("Return A,", "Return A and DNSSEC,")
        forge = LLMSkillForge(FakeForgeClient(mutated), tmp_path)
        learning = Learning(learning="add DNSSEC", tool_name="check_dns")
        result = await forge.mutate("check_dns", learning, skill_tier="t2")
        assert result["status"] == "mutated"

    @pytest.mark.asyncio
    async def test_mutation_name_change_rejected(self, tmp_path: Path) -> None:
        (tmp_path / "check_dns.md").write_text(_VALID_SKILL_RESPONSE)
        # LLM returns a skill with a different name
        renamed = _VALID_SKILL_RESPONSE.replace("check_dns", "lookup_dns")
        forge = LLMSkillForge(FakeForgeClient(renamed), tmp_path)
        learning = Learning(learning="rename", tool_name="check_dns")
        result = await forge.mutate("check_dns", learning)
        assert result["status"] == "error"
        assert "changed name" in result.get("error", "").lower()
