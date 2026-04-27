"""Tests for skill artifact versioning, judging, and coaching (Skill Spec)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from turing.producers.concept_skill_producers import AGENT_SKILL_SEEDS
from turing.self_model import Skill, SkillKind


def _seed_skill(srepo, self_id, name="Code Reading", kind=SkillKind.CODING) -> Skill:
    skill = Skill(
        node_id=f"skill-test-{name.replace(' ', '-')}",
        self_id=self_id,
        name=name,
        kind=kind,
        stored_level=0.1,
        last_practiced_at=datetime.now(UTC),
    )
    srepo.insert_skill(skill)
    return skill


def _insert_artifact(srepo, self_id, skill_id, version, score, judge_notes="ok", coaching=None):
    srepo.insert_skill_artifact(
        artifact_id=f"artifact-v{version}",
        self_id=self_id,
        skill_id=skill_id,
        version=version,
        artifact_text=f"test artifact v{version}",
        score=score,
        judge_notes=judge_notes,
        coaching=coaching,
    )


class TestSkillSeeding:
    def test_skill1_seeded_skill_has_agent_name(self, srepo, bootstrapped_id):
        skill = _seed_skill(srepo, bootstrapped_id)
        assert skill.name == "Code Reading"
        assert skill.kind == SkillKind.CODING
        assert skill.stored_level == 0.1

    def test_skill12_duplicate_rejected(self, srepo, bootstrapped_id):
        _seed_skill(srepo, bootstrapped_id, "Code Reading")
        existing = srepo.list_skills(bootstrapped_id)
        assert len(existing) == 1
        with pytest.raises(Exception):
            _seed_skill(srepo, bootstrapped_id, "Code Reading")

    def test_skill13_seeding_skips_when_all_present(self, srepo, bootstrapped_id):
        for seed in AGENT_SKILL_SEEDS:
            kind_map = {k.value: k for k in SkillKind}
            _seed_skill(
                srepo,
                bootstrapped_id,
                seed["name"],
                kind_map.get(seed["kind"], SkillKind.INTELLECTUAL),
            )
        assert len(srepo.list_skills(bootstrapped_id)) == len(AGENT_SKILL_SEEDS)

    def test_skill14_all_seeds_from_registry(self, srepo, bootstrapped_id):
        seed_names = {s["name"] for s in AGENT_SKILL_SEEDS}
        for name in seed_names:
            _seed_skill(srepo, bootstrapped_id, name, SkillKind.INTELLECTUAL)
        skills = srepo.list_skills(bootstrapped_id)
        assert len(skills) == len(AGENT_SKILL_SEEDS)
        for skill in skills:
            assert skill.name in seed_names


class TestArtifactVersioning:
    def test_skill2_first_artifact_sets_level(self, srepo, bootstrapped_id):
        skill = _seed_skill(srepo, bootstrapped_id)
        _insert_artifact(srepo, bootstrapped_id, skill.node_id, version=1, score=0.4)
        best = srepo.get_best_artifact(skill.node_id)
        assert best is not None
        assert best["score"] == 0.4
        skill.stored_level = best["score"]
        skill.best_version = best["version"]
        srepo.update_skill(skill)
        refreshed = srepo.get_skill(skill.node_id)
        assert refreshed.stored_level == 0.4
        assert refreshed.best_version == 1
        assert refreshed.active_coaching is None

    def test_skill3_new_best_raises_level(self, srepo, bootstrapped_id):
        skill = _seed_skill(srepo, bootstrapped_id)
        _insert_artifact(srepo, bootstrapped_id, skill.node_id, 1, 0.4)
        _insert_artifact(srepo, bootstrapped_id, skill.node_id, 2, 0.55)
        best = srepo.get_best_artifact(skill.node_id)
        assert best["score"] == 0.55
        assert best["version"] == 2
        skill.stored_level = 0.55
        skill.best_version = 2
        srepo.update_skill(skill)
        assert srepo.get_skill(skill.node_id).stored_level == 0.55

    def test_skill4_regression_keeps_best_activates_coaching(self, srepo, bootstrapped_id):
        skill = _seed_skill(srepo, bootstrapped_id)
        _insert_artifact(srepo, bootstrapped_id, skill.node_id, 1, 0.4)
        _insert_artifact(srepo, bootstrapped_id, skill.node_id, 2, 0.55)
        best = srepo.get_best_artifact(skill.node_id)
        assert best["score"] == 0.55
        coaching = "Be more specific about what the function does"
        _insert_artifact(
            srepo,
            bootstrapped_id,
            skill.node_id,
            3,
            0.3,
            judge_notes="got worse",
            coaching=coaching,
        )
        best_after = srepo.get_best_artifact(skill.node_id)
        assert best_after["score"] == 0.55
        assert best_after["version"] == 2
        skill.stored_level = 0.55
        skill.best_version = 2
        skill.active_coaching = coaching
        srepo.update_skill(skill)
        refreshed = srepo.get_skill(skill.node_id)
        assert refreshed.stored_level == 0.55
        assert refreshed.best_version == 2
        assert refreshed.active_coaching == coaching

    def test_skill6_new_best_clears_coaching(self, srepo, bootstrapped_id):
        skill = _seed_skill(srepo, bootstrapped_id)
        skill.active_coaching = "old coaching"
        srepo.update_skill(skill)
        assert srepo.get_skill(skill.node_id).active_coaching == "old coaching"
        skill.active_coaching = None
        skill.stored_level = 0.6
        skill.best_version = 3
        srepo.update_skill(skill)
        refreshed = srepo.get_skill(skill.node_id)
        assert refreshed.active_coaching is None
        assert refreshed.stored_level == 0.6

    def test_skill10_artifact_history_queryable(self, srepo, bootstrapped_id):
        skill = _seed_skill(srepo, bootstrapped_id)
        for v in range(1, 4):
            _insert_artifact(srepo, bootstrapped_id, skill.node_id, v, 0.1 * v)
        artifacts = srepo.list_skill_artifacts(skill.node_id, limit=2)
        assert len(artifacts) == 2
        assert artifacts[0]["version"] > artifacts[1]["version"]

    def test_skill11_get_best_returns_highest_score(self, srepo, bootstrapped_id):
        skill = _seed_skill(srepo, bootstrapped_id)
        _insert_artifact(srepo, bootstrapped_id, skill.node_id, 1, 0.3)
        _insert_artifact(srepo, bootstrapped_id, skill.node_id, 2, 0.7)
        _insert_artifact(srepo, bootstrapped_id, skill.node_id, 3, 0.5)
        best = srepo.get_best_artifact(skill.node_id)
        assert best["score"] == 0.7
        assert best["version"] == 2


class TestNoDecay:
    def test_skill7_no_decay_over_time(self, srepo, bootstrapped_id):
        from turing.self_model import current_level

        skill = _seed_skill(srepo, bootstrapped_id)
        skill.stored_level = 0.7
        srepo.update_skill(skill)
        future = datetime(2099, 1, 1, tzinfo=UTC)
        assert current_level(skill, future) == 0.7

    def test_skill8_fail_keeps_best(self, srepo, bootstrapped_id):
        skill = _seed_skill(srepo, bootstrapped_id)
        _insert_artifact(srepo, bootstrapped_id, skill.node_id, 1, 0.5)
        skill.stored_level = 0.5
        skill.best_version = 1
        srepo.update_skill(skill)
        _insert_artifact(srepo, bootstrapped_id, skill.node_id, 2, 0.1, coaching="try harder")
        best = srepo.get_best_artifact(skill.node_id)
        assert best["score"] == 0.5
        assert srepo.get_skill(skill.node_id).stored_level == 0.5


class TestJudgeClamping:
    def test_skill9_score_clamped_to_1(self, srepo, bootstrapped_id):
        skill = _seed_skill(srepo, bootstrapped_id)
        clamped = max(0.0, min(1.0, 1.5))
        _insert_artifact(srepo, bootstrapped_id, skill.node_id, 1, clamped)
        latest = srepo.get_latest_artifact(skill.node_id)
        assert latest["score"] == 1.0
