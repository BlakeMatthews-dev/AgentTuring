"""Skill Forge: LLM-generated skill creation and mutation.

Creates new SKILL.md files from natural language requests, and mutates
existing skills by baking promoted learnings into system prompts.

Forged skills start at T3 (sandboxed). All content is security-scanned.
Uses LLMClient protocol — no direct HTTP calls.
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path  # noqa: TC003
from typing import TYPE_CHECKING, Any

from stronghold.skills.parser import parse_skill_file, security_scan
from stronghold.types.skill import SkillDefinition

if TYPE_CHECKING:
    from stronghold.protocols.llm import LLMClient
    from stronghold.types.memory import Learning

logger = logging.getLogger("stronghold.skills.forge")

_FORGE_PROMPT = """You are a Skill Forge. You create new tool skills for an AI agent platform.

A skill is a markdown file with YAML frontmatter:

```markdown
---
name: skill_name
description: >
  One paragraph describing what this tool does and when to use it.
groups: [general]
parameters:
  type: object
  properties:
    param_name:
      type: string
      description: What this parameter is for
  required:
    - param_name
endpoint: ""
---

System prompt instructions go here. Explain how to use the tool,
what it returns, edge cases, tips, etc.
```

Rules:
- name must be snake_case, unique, descriptive (2-50 chars)
- description must clearly explain WHEN to use this tool
- parameters must use JSON Schema format
- groups should be one of: general, automation, trading, code, creative, search
- endpoint is empty string for tools handled by the platform
- System prompt should be practical instructions
- Do NOT include secrets, API keys, or credentials
- Do NOT include exec(), eval(), subprocess, or os.system

The user's request: {request}

Generate the complete SKILL.md file content. Output ONLY the file content."""

_MUTATE_PROMPT = """You are refining an existing AI skill based on a learned correction.

Current SKILL.md content:
```
{current_content}
```

The following correction was learned from repeated use:
{learning_text}

Update the skill's system prompt (the markdown body after the YAML frontmatter) to incorporate
this correction as permanent knowledge. The LLM should apply this correction automatically.

Rules:
- Keep the YAML frontmatter EXACTLY the same (name, description, parameters, groups, endpoint)
- Only modify the system prompt body (text after the --- frontmatter closing)
- Add the correction naturally — integrate it, don't just append
- Keep the same tone and structure
- Do NOT remove existing instructions
- Do NOT add secrets, exec(), eval(), or dangerous patterns

Output ONLY the complete updated SKILL.md file content."""


class LLMSkillForge:
    """Creates and mutates skills via LLM. Implements SkillForge protocol."""

    def __init__(
        self,
        llm: LLMClient,
        skills_dir: Path,
        forge_model: str = "auto",
    ) -> None:
        self._llm = llm
        self._skills_dir = skills_dir
        self._forge_model = forge_model

    async def forge(self, request: str) -> SkillDefinition:
        """Generate a new skill from a natural language request.

        Raises ValueError if generation fails or content is unsafe.
        """
        prompt = _FORGE_PROMPT.format(request=request)
        content = await self._call_llm(prompt)
        if not content:
            msg = "LLM returned empty response for skill forge request"
            raise ValueError(msg)

        # Strip markdown code fences if present
        content = re.sub(r"^```\w*\n", "", content)
        content = re.sub(r"\n```\s*$", "", content)

        # Security scan
        safe, findings = security_scan(content)
        if not safe:
            msg = f"Forged skill rejected by security scan: {', '.join(findings)}"
            raise ValueError(msg)

        # Parse
        skill = parse_skill_file(content, source="forge")
        if skill is None:
            msg = "Forged skill content failed to parse"
            raise ValueError(msg)

        # Path traversal defense
        filepath = self._skills_dir / f"{skill.name}.md"
        if not filepath.resolve().is_relative_to(self._skills_dir.resolve()):
            msg = f"Invalid skill name (path traversal detected): {skill.name}"
            raise ValueError(msg)

        # Check name collision
        if filepath.exists():
            msg = f"Skill '{skill.name}' already exists at {filepath}"
            raise ValueError(msg)

        # Override trust tier — forged skills are T3 (sandboxed)
        skill = SkillDefinition(
            name=skill.name,
            description=skill.description,
            groups=skill.groups,
            parameters=skill.parameters,
            endpoint=skill.endpoint,
            auth_key_env=skill.auth_key_env,
            system_prompt=skill.system_prompt,
            source="forge",
            trust_tier="t3",
        )

        # Save to disk
        self._skills_dir.mkdir(parents=True, exist_ok=True)
        filepath.write_text(content, encoding="utf-8")
        logger.info("Forged skill '%s' saved to %s", skill.name, filepath)

        return skill

    async def mutate(
        self,
        skill_name: str,
        learning: Learning,
        *,
        skill_tier: str = "",
    ) -> dict[str, Any]:
        """Mutate an existing skill by baking a learning into its system prompt.

        T0 (built-in) and T1 (operator-vetted) skills CANNOT be auto-mutated.
        Only T2+ skills support learning-driven mutation.

        Returns: {"status": "mutated"|"skipped"|"error"|"blocked", ...}
        """
        # Tier guard: T0/T1 skills are immutable via auto-mutation
        if skill_tier in ("t0", "t1"):
            return {
                "status": "blocked",
                "reason": f"Cannot auto-mutate {skill_tier} skill '{skill_name}'. "
                "Only T2+ skills support learning-driven mutation.",
            }

        # Find the skill file
        filepath = self._skills_dir / f"{skill_name}.md"
        if not filepath.exists():
            filepath = self._skills_dir / "community" / f"{skill_name}.md"
            if not filepath.exists():
                return {"status": "skipped", "reason": f"No SKILL.md for '{skill_name}'"}

        current_content = filepath.read_text(encoding="utf-8")
        old_hash = hashlib.sha256(current_content.encode()).hexdigest()[:16]

        learning_text = learning.learning if hasattr(learning, "learning") else str(learning)
        if not learning_text:
            return {"status": "skipped", "reason": "Empty learning text"}

        # Security: scan the learning text BEFORE passing to mutation LLM.
        # Prevents prompt injection via crafted learnings.
        # Two-layer check: (1) Warden patterns, (2) instruction density
        scan_wrapper = (
            "---\nname: _scan\ndescription: _scan\n"
            "parameters:\n  type: object\n  properties: {}\n"
            f"---\n{learning_text}"
        )
        safe, findings = security_scan(scan_wrapper)
        if not safe:
            return {
                "status": "error",
                "error": f"Learning text rejected by security scan: {', '.join(findings)}",
            }

        # Stricter instruction density check for mutations (0.08 vs 0.15 global).
        # Legitimate learnings are factual corrections, not instruction-heavy.
        from stronghold.security.warden.heuristics import (  # noqa: PLC0415
            score_instruction_density,
        )

        density = score_instruction_density(learning_text)
        if density > 0.08:
            logger.warning(
                "Skill mutation blocked: high instruction density (%.2f) in learning for '%s'",
                density,
                skill_name,
            )
            return {
                "status": "error",
                "error": f"Learning text has suspicious instruction density ({density:.2f}). "
                "Legitimate corrections should be factual, not instruction-heavy.",
            }

        # Generate mutated content via LLM
        prompt = _MUTATE_PROMPT.format(
            current_content=current_content,
            learning_text=learning_text,
        )
        new_content = await self._call_llm(prompt)
        if not new_content:
            return {"status": "error", "error": "LLM returned empty response"}

        # Strip code fences
        new_content = re.sub(r"^```\w*\n", "", new_content)
        new_content = re.sub(r"\n```\s*$", "", new_content)

        # Security scan
        safe, findings = security_scan(new_content)
        if not safe:
            return {"status": "error", "error": f"Mutation rejected: {', '.join(findings)}"}

        # Parse and verify name preserved
        new_skill = parse_skill_file(new_content)
        if new_skill is None:
            return {"status": "error", "error": "Mutated content failed to parse"}
        if new_skill.name != skill_name:
            return {"status": "error", "error": f"Mutation changed name: {new_skill.name}"}

        new_hash = hashlib.sha256(new_content.encode()).hexdigest()[:16]

        # Write mutated skill
        filepath.write_text(new_content, encoding="utf-8")
        logger.info(
            "Mutated skill '%s' (%s → %s)",
            skill_name,
            old_hash,
            new_hash,
        )

        return {
            "status": "mutated",
            "skill_name": skill_name,
            "old_hash": old_hash,
            "new_hash": new_hash,
        }

    async def _call_llm(self, prompt: str) -> str | None:
        """Call LLM and extract text content from response."""
        try:
            result: dict[str, Any] = await self._llm.complete(
                messages=[{"role": "user", "content": prompt}],
                model=self._forge_model,
                max_tokens=2000,
                temperature=0.3,
            )
            choices = result.get("choices", [])
            if choices:
                return str(choices[0].get("message", {}).get("content", ""))
        except Exception as e:
            logger.warning("Forge LLM call failed: %s", e)
        return None
