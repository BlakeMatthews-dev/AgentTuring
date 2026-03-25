"""Skill registry: in-memory CRUD with trust tier tracking.

Manages active skills with registration, lookup, group filtering,
and trust tier enforcement. Mutation history tracked per skill.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stronghold.types.skill import SkillDefinition

logger = logging.getLogger("stronghold.skills.registry")


class InMemorySkillRegistry:
    """In-memory skill registry. PostgreSQL version uses asyncpg.

    Skills are keyed by org_id-prefixed name for multi-tenant isolation.
    Built-in (t0) skills use the "__global__" org prefix and are visible to all.
    Thread-safe via reentrant lock for concurrent FastAPI requests.
    """

    def __init__(self) -> None:
        self._skills: dict[str, SkillDefinition] = {}
        self._versions: dict[str, list[SkillDefinition]] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _key(name: str, org_id: str = "") -> str:
        """Build org-scoped key."""
        prefix = org_id or "__global__"
        return f"{prefix}:{name}"

    def register(self, skill: SkillDefinition, org_id: str = "") -> None:
        """Register a skill. Overwrites if name already exists at SAME OR LOWER tier.

        T0 built-in skills cannot be overwritten by marketplace/forge installs.
        Built-in skills (t0) are registered globally.
        """
        effective_org = "" if skill.trust_tier == "t0" else org_id
        key = self._key(skill.name, effective_org)
        with self._lock:
            existing = self._skills.get(key)
            if (
                existing
                and existing.trust_tier in ("t0", "t1")
                and skill.trust_tier not in ("t0", "t1")
            ):
                logger.warning(
                    "Blocked: cannot overwrite %s skill '%s' with %s tier",
                    existing.trust_tier,
                    skill.name,
                    skill.trust_tier,
                )
                return
            self._skills[key] = skill
            self._versions.setdefault(key, []).append(skill)
        logger.debug("Registered skill: %s (tier=%s, org=%s)", skill.name, skill.trust_tier, org_id)

    def get(self, name: str, org_id: str = "") -> SkillDefinition | None:
        """Get a skill by name. Checks org-scoped first, then global."""
        if org_id:
            result = self._skills.get(self._key(name, org_id))
            if result:
                return result
        return self._skills.get(self._key(name, ""))

    def list_all(self, org_id: str = "") -> list[SkillDefinition]:
        """List all skills visible to an org (org-specific + global)."""
        results: dict[str, SkillDefinition] = {}
        global_prefix = "__global__:"
        org_prefix = f"{org_id}:" if org_id else ""
        for key, skill in self._skills.items():
            if key.startswith(global_prefix):
                results[skill.name] = skill
            elif org_prefix and key.startswith(org_prefix):
                results[skill.name] = skill  # Org-specific overrides global
        return list(results.values())

    def list_by_group(self, group: str, org_id: str = "") -> list[SkillDefinition]:
        """List skills matching a group (task type)."""
        return [s for s in self.list_all(org_id) if group in s.groups]

    def list_by_trust_tier(self, tier: str, org_id: str = "") -> list[SkillDefinition]:
        """List skills at a specific trust tier."""
        return [s for s in self.list_all(org_id) if s.trust_tier == tier]

    def update(self, skill: SkillDefinition, org_id: str = "") -> bool:
        """Update an existing skill. Returns False if not found."""
        with self._lock:
            key = self._key(skill.name, org_id)
            if key not in self._skills:
                key = self._key(skill.name, "")
                if key not in self._skills:
                    return False
            self._skills[key] = skill
            return True

    def delete(self, name: str, org_id: str = "") -> bool:
        """Delete a skill by name. Returns False if not found."""
        with self._lock:
            key = self._key(name, org_id)
            if key not in self._skills:
                return False
            del self._skills[key]
        logger.debug("Deleted skill: %s (org=%s)", name, org_id)
        return True

    def get_versions(self, name: str, org_id: str = "") -> list[SkillDefinition]:
        """Get all historical versions of a skill (oldest first)."""
        key = self._key(name, org_id)
        versions = self._versions.get(key)
        if versions:
            return list(versions)
        # Fall back to global
        if org_id:
            key = self._key(name, "")
            versions = self._versions.get(key)
            if versions:
                return list(versions)
        return []

    def get_version(self, name: str, version_idx: int, org_id: str = "") -> SkillDefinition | None:
        """Get a specific version by index (0-based)."""
        versions = self.get_versions(name, org_id)
        if 0 <= version_idx < len(versions):
            return versions[version_idx]
        return None

    def rollback(self, name: str, version_idx: int, org_id: str = "") -> bool:
        """Rollback a skill to a previous version. Returns False if version not found."""
        key = self._key(name, org_id)
        versions = self._versions.get(key)
        if not versions:
            if org_id:
                key = self._key(name, "")
                versions = self._versions.get(key)
            if not versions:
                return False

        if version_idx < 0 or version_idx >= len(versions):
            return False

        target = versions[version_idx]
        with self._lock:
            self._skills[key] = target
            # Append rollback as a new version entry
            versions.append(target)
        logger.info(
            "Rolled back skill '%s' to version %d (org=%s)",
            name,
            version_idx,
            org_id,
        )
        return True

    def __len__(self) -> int:
        return len(self._skills)

    def __contains__(self, name: str) -> bool:
        return any(k.endswith(f":{name}") for k in self._skills)
