"""Skill parser: YAML frontmatter + markdown body → SkillDefinition.

Format (same as Conductor/OpenClaw):
```
---
name: skill_name
description: What this tool does
groups: [general, automation]
parameters:
  type: object
  properties:
    param:
      type: string
  required: [param]
endpoint: ""
auth_key_env: ""
---

System prompt instructions (markdown body).
```
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

import yaml

from stronghold.types.skill import SkillDefinition

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)", re.DOTALL)
_VALID_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,50}$")
MAX_SKILL_BODY_LENGTH = 50000  # 50KB max system prompt body

# Unicode directional override codepoints (used to hide malicious content)
_DIRECTIONAL_CHARS = frozenset(
    {
        0x200E,
        0x200F,  # LRM, RLM
        0x202A,
        0x202B,
        0x202C,
        0x202D,
        0x202E,  # LRE, RLE, PDF, LRO, RLO
        0x2066,
        0x2067,
        0x2068,
        0x2069,  # LRI, RLI, FSI, PDI
    }
)

# Security patterns — auto-reject if found in skill body
_CRITICAL_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("code_execution", re.compile(r"\bexec\s*\(", re.I)),
    ("code_execution", re.compile(r"\beval\s*\(", re.I)),
    ("code_execution", re.compile(r"\bsubprocess\b", re.I)),
    ("code_execution", re.compile(r"\bos\.system\b", re.I)),
    ("code_execution", re.compile(r"\b__import__\b", re.I)),
    ("code_execution", re.compile(r"\bcompile\s*\(", re.I)),
    ("code_execution", re.compile(r"\bimportlib\b", re.I)),
    ("code_execution", re.compile(r"\b__builtins__\b", re.I)),
    ("code_execution", re.compile(r"\bglobals\s*\(\s*\)", re.I)),
    (
        "credential_leak",
        re.compile(
            r"""(?:api[_-]?key|secret|password|token)\s*[=:]\s*["'][^"']{8,}["']""",
            re.I,
        ),
    ),
    (
        "prompt_injection",
        re.compile(
            r"\b(?:ignore previous|disregard|forget your|you are now|new instructions|override)\b",
            re.I,
        ),
    ),
]

# Warning patterns — logged but allowed
_WARNING_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("external_url", re.compile(r"https?://(?!github\.com|raw\.githubusercontent)")),
    ("shell_command", re.compile(r"\b(?:curl|wget|fetch)\b", re.I)),
    ("destructive_op", re.compile(r"\b(?:rm -rf|rmdir|unlink)\b", re.I)),
]


def parse_skill_file(content: str, source: str = "") -> SkillDefinition | None:
    """Parse SKILL.md content into a SkillDefinition.

    Returns None if the content is invalid (bad YAML, missing fields, etc.).
    """
    match = _FRONTMATTER_RE.match(content)
    if not match:
        return None

    try:
        frontmatter: dict[str, Any] = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return None

    if not isinstance(frontmatter, dict):
        return None

    # Required fields
    name = frontmatter.get("name")
    if not name or not isinstance(name, str):
        return None

    description = frontmatter.get("description", "")
    if not description:
        return None

    parameters = frontmatter.get("parameters")
    if not parameters or not isinstance(parameters, dict):
        return None

    # Validate name
    if not _VALID_NAME_RE.match(name):
        return None

    # Extract optional fields
    groups_raw = frontmatter.get("groups", [])
    groups = tuple(str(g) for g in groups_raw) if isinstance(groups_raw, list) else ()

    body = match.group(2).strip()

    # M4: Strip Unicode directional override characters from body.
    # These can visually hide malicious instructions in the system prompt.
    body = "".join(ch for ch in body if ord(ch) not in _DIRECTIONAL_CHARS)

    # Limit body size to prevent context window stuffing
    if len(body) > MAX_SKILL_BODY_LENGTH:
        return None

    return SkillDefinition(
        name=name,
        description=str(description)[:500],
        groups=groups,
        parameters=parameters,
        endpoint=str(frontmatter.get("endpoint", "")),
        auth_key_env=str(frontmatter.get("auth_key_env", "")),
        system_prompt=body,
        source=source,
        trust_tier=str(frontmatter.get("trust_tier", "t2")),
    )


def validate_skill_name(name: str) -> bool:
    """Check if a skill name is valid (snake_case, 2-51 chars)."""
    return bool(_VALID_NAME_RE.match(name))


def security_scan(content: str) -> tuple[bool, list[str]]:
    """Scan skill body for dangerous patterns.

    Returns (safe, findings). safe=False if any critical pattern found.
    Warnings are returned in findings but don't fail the scan.

    Applies Unicode NFKD normalization before scanning to prevent
    bypass via Cyrillic lookalikes, zero-width joiners, etc.
    """
    findings: list[str] = []
    safe = True

    # Check body only (after frontmatter)
    match = _FRONTMATTER_RE.match(content)
    body = match.group(2) if match else content

    # Normalize Unicode to prevent bypass (Cyrillic 'е' → Latin 'e', etc.)
    body_normalized = unicodedata.normalize("NFKD", body)

    # Check for RTL/LTR override markers
    if any(ord(c) in _DIRECTIONAL_CHARS for c in body):
        findings.append("CRITICAL:unicode_directional_markers")
        safe = False

    for category, pattern in _CRITICAL_PATTERNS:
        if pattern.search(body_normalized):
            findings.append(f"CRITICAL:{category}")
            safe = False

    for category, pattern in _WARNING_PATTERNS:
        if pattern.search(body_normalized):
            findings.append(f"WARNING:{category}")

    return safe, findings
