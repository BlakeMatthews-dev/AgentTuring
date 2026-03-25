"""Tests for skill registry: CRUD + trust tiers."""

from stronghold.skills.registry import InMemorySkillRegistry
from stronghold.types.skill import SkillDefinition


def _make_skill(name: str = "test_skill", **kwargs: object) -> SkillDefinition:
    return SkillDefinition(
        name=name,
        description=str(kwargs.get("description", "A test skill")),
        groups=tuple(kwargs.get("groups", ("general",))),  # type: ignore[arg-type]
        trust_tier=str(kwargs.get("trust_tier", "t2")),
    )


class TestRegistryCRUD:
    def test_register_and_get(self) -> None:
        registry = InMemorySkillRegistry()
        skill = _make_skill()
        registry.register(skill)
        assert registry.get("test_skill") is skill

    def test_get_nonexistent(self) -> None:
        registry = InMemorySkillRegistry()
        assert registry.get("nope") is None

    def test_list_all(self) -> None:
        registry = InMemorySkillRegistry()
        registry.register(_make_skill("a"))
        registry.register(_make_skill("b"))
        assert len(registry.list_all()) == 2

    def test_update_existing(self) -> None:
        registry = InMemorySkillRegistry()
        registry.register(_make_skill("a", description="v1"))
        updated = _make_skill("a", description="v2")
        assert registry.update(updated)
        assert registry.get("a") is not None
        assert registry.get("a").description == "v2"  # type: ignore[union-attr]

    def test_update_nonexistent(self) -> None:
        registry = InMemorySkillRegistry()
        assert not registry.update(_make_skill("nope"))

    def test_delete(self) -> None:
        registry = InMemorySkillRegistry()
        registry.register(_make_skill())
        assert registry.delete("test_skill")
        assert registry.get("test_skill") is None

    def test_delete_nonexistent(self) -> None:
        registry = InMemorySkillRegistry()
        assert not registry.delete("nope")

    def test_len(self) -> None:
        registry = InMemorySkillRegistry()
        assert len(registry) == 0
        registry.register(_make_skill("a"))
        assert len(registry) == 1

    def test_contains(self) -> None:
        registry = InMemorySkillRegistry()
        registry.register(_make_skill())
        assert "test_skill" in registry
        assert "nope" not in registry

    def test_register_overwrites(self) -> None:
        registry = InMemorySkillRegistry()
        registry.register(_make_skill("a", description="v1"))
        registry.register(_make_skill("a", description="v2"))
        assert len(registry) == 1
        assert registry.get("a").description == "v2"  # type: ignore[union-attr]


class TestTierProtection:
    """T0/T1 skills cannot be overwritten by lower-tier skills."""

    def test_t0_not_overwritten_by_t2(self) -> None:
        registry = InMemorySkillRegistry()
        registry.register(_make_skill("ha_control", trust_tier="t0"))
        registry.register(_make_skill("ha_control", trust_tier="t2", description="malicious"))
        # T0 should survive
        skill = registry.get("ha_control")
        assert skill is not None
        assert skill.trust_tier == "t0"

    def test_t1_not_overwritten_by_t3(self) -> None:
        registry = InMemorySkillRegistry()
        registry.register(_make_skill("vetted_tool", trust_tier="t1"))
        registry.register(_make_skill("vetted_tool", trust_tier="t3"))
        assert registry.get("vetted_tool").trust_tier == "t1"  # type: ignore[union-attr]

    def test_t0_can_be_updated_by_t0(self) -> None:
        registry = InMemorySkillRegistry()
        registry.register(_make_skill("builtin", trust_tier="t0", description="v1"))
        registry.register(_make_skill("builtin", trust_tier="t0", description="v2"))
        assert registry.get("builtin").description == "v2"  # type: ignore[union-attr]


class TestGroupFiltering:
    def test_list_by_group(self) -> None:
        registry = InMemorySkillRegistry()
        registry.register(_make_skill("a", groups=("general",)))
        registry.register(_make_skill("b", groups=("automation",)))
        registry.register(_make_skill("c", groups=("general", "automation")))
        general = registry.list_by_group("general")
        assert len(general) == 2
        assert {s.name for s in general} == {"a", "c"}

    def test_list_by_group_empty(self) -> None:
        registry = InMemorySkillRegistry()
        registry.register(_make_skill("a", groups=("general",)))
        assert registry.list_by_group("trading") == []


class TestTrustTierFiltering:
    def test_list_by_tier(self) -> None:
        registry = InMemorySkillRegistry()
        registry.register(_make_skill("a", trust_tier="t0"))
        registry.register(_make_skill("b", trust_tier="t2"))
        registry.register(_make_skill("c", trust_tier="t2"))
        t2_skills = registry.list_by_trust_tier("t2")
        assert len(t2_skills) == 2

    def test_list_by_tier_empty(self) -> None:
        registry = InMemorySkillRegistry()
        assert registry.list_by_trust_tier("t3") == []
