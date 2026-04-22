"""Tests for tournament, canary, and learning approval modules."""

from __future__ import annotations

import time

from stronghold.agents.tournament import (
    AgentRating,
    BattleRecord,
    Tournament,
    _DEFAULT_ELO,
    _K_FACTOR,
    _MIN_BATTLES,
    _PROMOTION_THRESHOLD,
)
from stronghold.memory.learnings.approval import LearningApprovalGate
from stronghold.skills.canary import (
    CanaryDeployment,
    CanaryManager,
    CanaryStage,
    _STAGE_TRAFFIC,
)


# ── Tournament: BattleRecord & AgentRating dataclasses ──────────────


class TestBattleRecord:
    def test_defaults(self) -> None:
        rec = BattleRecord()
        assert rec.id == 0
        assert rec.intent == ""
        assert rec.agent_a == ""
        assert rec.agent_b == ""
        assert rec.winner == ""
        assert rec.score_a == 0.0
        assert rec.score_b == 0.0
        assert rec.judge_model == ""
        assert rec.org_id == ""
        # timestamp defaults to a real Unix epoch value close to "now"
        # (within 60s). This catches a regression where the default
        # becomes 0.0 or None.
        assert rec.timestamp > 0
        assert abs(time.time() - rec.timestamp) < 60


class TestAgentRating:
    def test_total_battles(self) -> None:
        rating = AgentRating(agent="a", intent="x", wins=3, losses=2, draws=1)
        assert rating.total_battles == 6

    def test_win_rate_zero_battles(self) -> None:
        rating = AgentRating(agent="a", intent="x")
        assert rating.win_rate == 0.0

    def test_win_rate_with_results(self) -> None:
        rating = AgentRating(agent="a", intent="x", wins=3, losses=1, draws=2)
        # win_rate = (3 + 0.5*2) / 6 = 4/6
        expected = (3 + 0.5 * 2) / 6
        assert abs(rating.win_rate - expected) < 1e-9


# ── Tournament: core logic ──────────────────────────────────────────


class TestTournament:
    def test_record_battle_a_wins(self) -> None:
        t = Tournament()
        rec = t.record_battle("code", "alpha", "beta", 0.9, 0.3)
        assert rec.winner == "alpha"
        assert rec.id == 1

    def test_record_battle_b_wins(self) -> None:
        t = Tournament()
        rec = t.record_battle("code", "alpha", "beta", 0.2, 0.8)
        assert rec.winner == "beta"

    def test_record_battle_draw(self) -> None:
        t = Tournament()
        rec = t.record_battle("code", "alpha", "beta", 0.5, 0.5)
        assert rec.winner == "draw"

    def test_elo_updates_on_win(self) -> None:
        t = Tournament()
        t.record_battle("code", "alpha", "beta", 0.9, 0.1)
        ra = t._get_rating("alpha", "code")
        rb = t._get_rating("beta", "code")
        # Winner's Elo should increase, loser's should decrease
        assert ra.elo > _DEFAULT_ELO
        assert rb.elo < _DEFAULT_ELO
        assert ra.wins == 1
        assert rb.losses == 1

    def test_elo_updates_on_draw(self) -> None:
        t = Tournament()
        t.record_battle("code", "alpha", "beta", 0.5, 0.5)
        ra = t._get_rating("alpha", "code")
        rb = t._get_rating("beta", "code")
        # Both start at same Elo, draw should keep them equal
        assert abs(ra.elo - _DEFAULT_ELO) < 1e-9
        assert abs(rb.elo - _DEFAULT_ELO) < 1e-9
        assert ra.draws == 1
        assert rb.draws == 1

    def test_battle_ids_increment(self) -> None:
        t = Tournament()
        r1 = t.record_battle("code", "a", "b", 1.0, 0.0)
        r2 = t.record_battle("code", "a", "b", 0.0, 1.0)
        assert r1.id == 1
        assert r2.id == 2

    def test_fifo_eviction(self) -> None:
        t = Tournament()
        t._max_battles = 3
        for i in range(5):
            t.record_battle("code", "a", "b", 1.0, 0.0)
        assert len(t._battles) == 3
        # Oldest should have been evicted; remaining IDs are 3, 4, 5
        assert t._battles[0].id == 3

    def test_judge_model_and_org_id_stored(self) -> None:
        t = Tournament()
        rec = t.record_battle(
            "code", "alpha", "beta", 0.9, 0.1,
            judge_model="gpt-4", org_id="org-1",
        )
        assert rec.judge_model == "gpt-4"
        assert rec.org_id == "org-1"

    def test_get_leaderboard(self) -> None:
        t = Tournament()
        # alpha wins 3 times
        for _ in range(3):
            t.record_battle("code", "alpha", "beta", 0.9, 0.1)
        board = t.get_leaderboard("code")
        assert len(board) == 2
        assert board[0]["agent"] == "alpha"
        assert board[0]["wins"] == 3
        assert board[1]["agent"] == "beta"
        assert board[1]["losses"] == 3

    def test_get_leaderboard_filters_intent(self) -> None:
        t = Tournament()
        t.record_battle("code", "alpha", "beta", 0.9, 0.1)
        t.record_battle("chat", "gamma", "delta", 0.8, 0.2)
        board = t.get_leaderboard("chat")
        agents = {entry["agent"] for entry in board}
        assert agents == {"gamma", "delta"}

    def test_get_leaderboard_filters_org(self) -> None:
        t = Tournament()
        t.record_battle("code", "alpha", "beta", 0.9, 0.1, org_id="org-1")
        t.record_battle("code", "gamma", "delta", 0.8, 0.2, org_id="org-2")
        board = t.get_leaderboard("code", org_id="org-1")
        agents = {entry["agent"] for entry in board}
        assert agents == {"alpha", "beta"}

    def test_check_promotions_no_battles(self) -> None:
        t = Tournament()
        result = t.check_promotions("code", "incumbent")
        assert result is None

    def test_check_promotions_not_enough_battles(self) -> None:
        t = Tournament()
        # Record fewer than _MIN_BATTLES for challenger
        for _ in range(_MIN_BATTLES - 1):
            t.record_battle("code", "challenger", "incumbent", 1.0, 0.0)
        result = t.check_promotions("code", "incumbent")
        assert result is None

    def test_check_promotions_sufficient_margin(self) -> None:
        t = Tournament()
        # Give the challenger enough wins to build an Elo margin
        for _ in range(_MIN_BATTLES + 5):
            t.record_battle("code", "challenger", "incumbent", 1.0, 0.0)
        # Check challenger Elo is well above incumbent
        rc = t._get_rating("challenger", "code")
        ri = t._get_rating("incumbent", "code")
        assert rc.elo - ri.elo >= _PROMOTION_THRESHOLD
        result = t.check_promotions("code", "incumbent")
        assert result == "challenger"

    def test_check_promotions_margin_too_small(self) -> None:
        t = Tournament()
        # Mix wins so margin stays small
        for i in range(_MIN_BATTLES + 2):
            if i % 2 == 0:
                t.record_battle("code", "challenger", "incumbent", 0.6, 0.4)
            else:
                t.record_battle("code", "incumbent", "challenger", 0.6, 0.4)
        result = t.check_promotions("code", "incumbent")
        assert result is None

    def test_check_promotions_picks_best_challenger(self) -> None:
        t = Tournament()
        # Two challengers: one strong, one moderate
        for _ in range(_MIN_BATTLES + 5):
            t.record_battle("code", "strong", "incumbent", 1.0, 0.0)
        for _ in range(_MIN_BATTLES + 5):
            t.record_battle("code", "moderate", "incumbent", 0.7, 0.3)
        result = t.check_promotions("code", "incumbent")
        # "strong" should have highest Elo margin
        assert result == "strong"

    def test_check_promotions_filters_by_org(self) -> None:
        t = Tournament()
        for _ in range(_MIN_BATTLES + 5):
            t.record_battle("code", "challenger", "incumbent", 1.0, 0.0, org_id="org-1")
        # Different org should not see the challenger
        result = t.check_promotions("code", "incumbent", org_id="org-2")
        assert result is None

    # ── get_battle_history (lines 210-218) ──────────────────────────

    def test_get_battle_history_no_filters(self) -> None:
        t = Tournament()
        t.record_battle("code", "a", "b", 0.9, 0.1)
        t.record_battle("chat", "c", "d", 0.5, 0.5)
        history = t.get_battle_history()
        assert len(history) == 2

    def test_get_battle_history_filter_by_agent(self) -> None:
        t = Tournament()
        t.record_battle("code", "a", "b", 0.9, 0.1)
        t.record_battle("code", "c", "d", 0.8, 0.2)
        history = t.get_battle_history(agent="a")
        assert len(history) == 1
        assert history[0]["agent_a"] == "a"

    def test_get_battle_history_filter_by_intent(self) -> None:
        t = Tournament()
        t.record_battle("code", "a", "b", 0.9, 0.1)
        t.record_battle("chat", "a", "b", 0.5, 0.5)
        history = t.get_battle_history(intent="chat")
        assert len(history) == 1
        assert history[0]["intent"] == "chat"

    def test_get_battle_history_filter_by_org(self) -> None:
        t = Tournament()
        t.record_battle("code", "a", "b", 0.9, 0.1, org_id="org-1")
        t.record_battle("code", "a", "b", 0.8, 0.2, org_id="org-2")
        history = t.get_battle_history(org_id="org-1")
        assert len(history) == 1

    def test_get_battle_history_combined_filters(self) -> None:
        t = Tournament()
        t.record_battle("code", "a", "b", 0.9, 0.1, org_id="org-1")
        t.record_battle("chat", "a", "b", 0.5, 0.5, org_id="org-1")
        t.record_battle("code", "c", "d", 0.7, 0.3, org_id="org-1")
        history = t.get_battle_history(agent="a", intent="code", org_id="org-1")
        assert len(history) == 1
        assert history[0]["agent_a"] == "a"

    def test_get_battle_history_limit(self) -> None:
        t = Tournament()
        for _ in range(10):
            t.record_battle("code", "a", "b", 0.9, 0.1)
        history = t.get_battle_history(limit=3)
        assert len(history) == 3
        # Should return the last 3 (most recent)
        assert history[-1]["id"] == 10

    def test_get_battle_history_dict_keys(self) -> None:
        t = Tournament()
        t.record_battle("code", "a", "b", 0.9, 0.1, judge_model="gpt-4")
        history = t.get_battle_history()
        entry = history[0]
        expected_keys = {
            "id", "intent", "agent_a", "agent_b",
            "winner", "score_a", "score_b", "judge_model", "timestamp",
        }
        assert set(entry.keys()) == expected_keys

    def test_get_stats(self) -> None:
        t = Tournament()
        t.record_battle("code", "a", "b", 0.9, 0.1)
        t.record_battle("chat", "c", "d", 0.5, 0.5)
        stats = t.get_stats()
        assert stats["total_battles"] == 2
        assert stats["total_ratings"] == 4  # a, b on code + c, d on chat
        assert stats["intents_tracked"] == 2

    def test_get_stats_empty(self) -> None:
        t = Tournament()
        stats = t.get_stats()
        assert stats["total_battles"] == 0
        assert stats["total_ratings"] == 0
        assert stats["intents_tracked"] == 0

    def test_leaderboard_entry_keys(self) -> None:
        t = Tournament()
        t.record_battle("code", "a", "b", 0.9, 0.1)
        board = t.get_leaderboard("code")
        entry = board[0]
        expected_keys = {"agent", "elo", "wins", "losses", "draws", "total", "win_rate"}
        assert set(entry.keys()) == expected_keys

    def test_elo_symmetry(self) -> None:
        """Total Elo change across both agents should sum to zero."""
        t = Tournament()
        t.record_battle("code", "alpha", "beta", 0.9, 0.1)
        ra = t._get_rating("alpha", "code")
        rb = t._get_rating("beta", "code")
        total_delta = (ra.elo - _DEFAULT_ELO) + (rb.elo - _DEFAULT_ELO)
        assert abs(total_delta) < 1e-9


# ── Canary: CanaryDeployment dataclass ──────────────────────────────


class TestCanaryDeployment:
    def test_error_rate_zero_requests(self) -> None:
        d = CanaryDeployment(skill_name="s")
        assert d.error_rate == 0.0

    def test_error_rate_computed(self) -> None:
        d = CanaryDeployment(skill_name="s", total_requests=10, errors=3)
        assert abs(d.error_rate - 0.3) < 1e-9

    def test_traffic_pct_canary(self) -> None:
        d = CanaryDeployment(skill_name="s", stage=CanaryStage.CANARY)
        assert d.traffic_pct == _STAGE_TRAFFIC[CanaryStage.CANARY]

    def test_traffic_pct_full(self) -> None:
        d = CanaryDeployment(skill_name="s", stage=CanaryStage.FULL)
        assert d.traffic_pct == 1.0


# ── Canary: CanaryManager ──────────────────────────────────────────


class TestCanaryManager:
    def test_start_canary(self) -> None:
        mgr = CanaryManager()
        dep = mgr.start_canary("my_skill", 1, 2, org_id="org-1")
        assert dep.skill_name == "my_skill"
        assert dep.old_version == 1
        assert dep.new_version == 2
        assert dep.stage == CanaryStage.CANARY
        assert dep.org_id == "org-1"

    def test_get_deployment(self) -> None:
        mgr = CanaryManager()
        mgr.start_canary("s", 1, 2)
        dep = mgr.get_deployment("s")
        assert dep is not None
        assert dep.skill_name == "s"

    def test_get_deployment_missing(self) -> None:
        mgr = CanaryManager()
        assert mgr.get_deployment("nonexistent") is None

    def test_should_use_new_version_no_deployment(self) -> None:
        mgr = CanaryManager()
        assert mgr.should_use_new_version("nonexistent") is False

    def test_should_use_new_version_full_stage(self) -> None:
        mgr = CanaryManager()
        dep = mgr.start_canary("s", 1, 2, org_id="test-org")
        dep.stage = CanaryStage.FULL
        # At 100% traffic, should always return True (C14: org_id required)
        results = [mgr.should_use_new_version("s", org_id="test-org") for _ in range(100)]
        assert all(results)

    def test_should_use_new_version_requires_org_id(self) -> None:
        """C14: Empty org_id must return False to prevent cross-tenant leakage."""
        mgr = CanaryManager()
        mgr.start_canary("s", 1, 2, org_id="test-org")
        assert mgr.should_use_new_version("s", org_id="") is False

    def test_record_result_increments(self) -> None:
        mgr = CanaryManager()
        mgr.start_canary("s", 1, 2)
        mgr.record_result("s", success=True)
        mgr.record_result("s", success=False)
        mgr.record_result("s", success=True)
        dep = mgr.get_deployment("s")
        assert dep is not None
        assert dep.total_requests == 3
        assert dep.errors == 1

    def test_record_result_no_deployment(self) -> None:
        mgr = CanaryManager()
        # Should not raise
        mgr.record_result("nonexistent", success=True)

    def test_check_hold_when_no_deployment(self) -> None:
        mgr = CanaryManager()
        assert mgr.check_promotion_or_rollback("nonexistent") == "hold"

    def test_check_hold_insufficient_requests(self) -> None:
        mgr = CanaryManager(min_requests_per_stage=20, stage_duration_secs=0.0)
        mgr.start_canary("s", 1, 2)
        # Only 5 requests -- not enough
        for _ in range(5):
            mgr.record_result("s", success=True)
        assert mgr.check_promotion_or_rollback("s") == "hold"

    def test_rollback_on_high_errors(self) -> None:
        mgr = CanaryManager(error_threshold=0.1, min_requests_per_stage=10)
        mgr.start_canary("s", 1, 2)
        # Record 10 requests with 50% error rate
        for i in range(10):
            mgr.record_result("s", success=(i % 2 == 0))
        result = mgr.check_promotion_or_rollback("s")
        assert result == "rollback"
        # Deployment should be removed
        assert mgr.get_deployment("s") is None

    def test_rollback_recorded_in_list(self) -> None:
        mgr = CanaryManager(error_threshold=0.1, min_requests_per_stage=10)
        mgr.start_canary("s", 1, 2)
        for i in range(10):
            mgr.record_result("s", success=(i % 2 == 0))
        mgr.check_promotion_or_rollback("s")
        rollbacks = mgr.list_rollbacks()
        assert len(rollbacks) == 1
        assert rollbacks[0]["skill_name"] == "s"
        assert rollbacks[0]["new_version"] == 2
        assert rollbacks[0]["stage"] == "canary"
        assert rollbacks[0]["error_rate"] == 0.5

    def test_advance_stage(self) -> None:
        mgr = CanaryManager(
            error_threshold=0.5,
            min_requests_per_stage=5,
            stage_duration_secs=0.0,  # Elapsed always >= 0 immediately
        )
        dep = mgr.start_canary("s", 1, 2)
        # Manually set stage_started_at to the past so elapsed >= 0
        dep.stage_started_at = time.time() - 1.0
        for _ in range(5):
            mgr.record_result("s", success=True)
        result = mgr.check_promotion_or_rollback("s")
        assert result == "advance"
        dep = mgr.get_deployment("s")
        assert dep is not None
        assert dep.stage == CanaryStage.PARTIAL
        # Counters reset after advance
        assert dep.total_requests == 0
        assert dep.errors == 0

    def test_advance_through_all_stages_to_complete(self) -> None:
        mgr = CanaryManager(
            error_threshold=0.5,
            min_requests_per_stage=1,
            stage_duration_secs=0.0,
        )
        dep = mgr.start_canary("s", 1, 2)

        stages_seen = [dep.stage]
        for _ in range(4):  # canary -> partial -> majority -> full -> complete
            dep_current = mgr.get_deployment("s")
            if dep_current is None:
                break
            dep_current.stage_started_at = time.time() - 1.0
            mgr.record_result("s", success=True)
            result = mgr.check_promotion_or_rollback("s")
            if result == "advance":
                dep_check = mgr.get_deployment("s")
                if dep_check:
                    stages_seen.append(dep_check.stage)
            elif result == "complete":
                stages_seen.append("complete")
                break

        assert CanaryStage.CANARY in stages_seen
        assert CanaryStage.PARTIAL in stages_seen
        assert CanaryStage.MAJORITY in stages_seen
        # Last advance from FULL should complete and remove deployment
        assert mgr.get_deployment("s") is None

    def test_list_active(self) -> None:
        mgr = CanaryManager()
        mgr.start_canary("skill_a", 1, 2, org_id="org-1")
        mgr.start_canary("skill_b", 3, 4, org_id="org-2")
        active = mgr.list_active()
        assert len(active) == 2
        names = {d["skill_name"] for d in active}
        assert names == {"skill_a", "skill_b"}
        # Check dict keys
        entry = active[0]
        expected_keys = {
            "skill_name", "old_version", "new_version", "stage",
            "traffic_pct", "total_requests", "errors", "error_rate",
        }
        assert set(entry.keys()) == expected_keys

    def test_list_active_empty(self) -> None:
        mgr = CanaryManager()
        assert mgr.list_active() == []

    def test_list_rollbacks_limit(self) -> None:
        mgr = CanaryManager(error_threshold=0.01, min_requests_per_stage=1)
        for i in range(5):
            name = f"skill_{i}"
            mgr.start_canary(name, 1, 2)
            mgr.record_result(name, success=False)
            mgr.check_promotion_or_rollback(name)
        rollbacks = mgr.list_rollbacks(limit=3)
        assert len(rollbacks) == 3

    def test_list_rollbacks_empty(self) -> None:
        mgr = CanaryManager()
        assert mgr.list_rollbacks() == []

    def test_org_isolation(self) -> None:
        mgr = CanaryManager()
        mgr.start_canary("s", 1, 2, org_id="org-1")
        mgr.start_canary("s", 3, 4, org_id="org-2")
        dep1 = mgr.get_deployment("s", org_id="org-1")
        dep2 = mgr.get_deployment("s", org_id="org-2")
        assert dep1 is not None
        assert dep2 is not None
        assert dep1.new_version == 2
        assert dep2.new_version == 4


# ── LearningApprovalGate ───────────────────────────────────────────


class TestLearningApprovalGate:
    def test_request_approval(self) -> None:
        gate = LearningApprovalGate()
        a = gate.request_approval(
            learning_id=1,
            org_id="org-1",
            learning_preview="when X fails, try Y",
            tool_name="shell",
            hit_count=5,
        )
        assert a.learning_id == 1
        assert a.org_id == "org-1"
        assert a.status == "pending"
        assert a.learning_preview == "when X fails, try Y"
        assert a.tool_name == "shell"
        assert a.hit_count == 5

    def test_request_approval_idempotent(self) -> None:
        gate = LearningApprovalGate()
        a1 = gate.request_approval(1, learning_preview="first")
        a2 = gate.request_approval(1, learning_preview="second")
        assert a1 is a2
        assert a1.learning_preview == "first"

    def test_approve(self) -> None:
        gate = LearningApprovalGate()
        gate.request_approval(1)
        result = gate.approve(1, reviewer="admin", notes="looks good")
        assert result is not None
        assert result.status == "approved"
        assert result.reviewed_by == "admin"
        assert result.review_notes == "looks good"
        assert result.reviewed_at > 0

    def test_approve_nonexistent(self) -> None:
        gate = LearningApprovalGate()
        assert gate.approve(999, reviewer="admin") is None

    def test_approve_already_approved(self) -> None:
        gate = LearningApprovalGate()
        gate.request_approval(1)
        gate.approve(1, reviewer="admin")
        # Trying to approve again should fail (status != "pending")
        assert gate.approve(1, reviewer="other") is None

    def test_reject(self) -> None:
        gate = LearningApprovalGate()
        gate.request_approval(1)
        result = gate.reject(1, reviewer="admin", reason="too risky")
        assert result is not None
        assert result.status == "rejected"
        assert result.reviewed_by == "admin"
        assert result.review_notes == "too risky"
        assert result.reviewed_at > 0

    def test_reject_nonexistent(self) -> None:
        gate = LearningApprovalGate()
        assert gate.reject(999, reviewer="admin") is None

    def test_reject_already_rejected(self) -> None:
        gate = LearningApprovalGate()
        gate.request_approval(1)
        gate.reject(1, reviewer="admin", reason="no")
        # Trying to reject again should fail (status != "pending")
        assert gate.reject(1, reviewer="other") is None

    def test_approve_then_reject_fails(self) -> None:
        gate = LearningApprovalGate()
        gate.request_approval(1)
        gate.approve(1, reviewer="admin")
        assert gate.reject(1, reviewer="admin") is None

    def test_reject_then_approve_fails(self) -> None:
        gate = LearningApprovalGate()
        gate.request_approval(1)
        gate.reject(1, reviewer="admin")
        assert gate.approve(1, reviewer="admin") is None

    def test_get_pending(self) -> None:
        gate = LearningApprovalGate()
        gate.request_approval(1, org_id="org-1")
        gate.request_approval(2, org_id="org-1")
        gate.request_approval(3, org_id="org-2")
        gate.approve(2, reviewer="admin")

        pending = gate.get_pending(org_id="org-1")
        assert len(pending) == 1
        assert pending[0].learning_id == 1

    def test_get_pending_no_org_filter(self) -> None:
        gate = LearningApprovalGate()
        gate.request_approval(1, org_id="org-1")
        gate.request_approval(2, org_id="org-2")
        pending = gate.get_pending()
        assert len(pending) == 2

    def test_get_approved_ids(self) -> None:
        gate = LearningApprovalGate()
        gate.request_approval(1)
        gate.request_approval(2)
        gate.request_approval(3)
        gate.approve(1, reviewer="admin")
        gate.approve(3, reviewer="admin")
        ids = gate.get_approved_ids()
        assert sorted(ids) == [1, 3]

    def test_mark_promoted(self) -> None:
        gate = LearningApprovalGate()
        gate.request_approval(1)
        gate.approve(1, reviewer="admin")
        gate.mark_promoted(1)
        approval = gate._approvals[1]
        assert approval.status == "promoted"
        # Should no longer appear in approved_ids
        assert 1 not in gate.get_approved_ids()

    def test_mark_promoted_only_works_on_approved(self) -> None:
        gate = LearningApprovalGate()
        gate.request_approval(1)
        # Still pending -- mark_promoted should be a no-op
        gate.mark_promoted(1)
        assert gate._approvals[1].status == "pending"

    def test_mark_promoted_nonexistent(self) -> None:
        gate = LearningApprovalGate()
        # Should not raise
        gate.mark_promoted(999)

    # ── get_all (lines 116-136) ─────────────────────────────────────

    def test_get_all(self) -> None:
        gate = LearningApprovalGate()
        gate.request_approval(1, org_id="org-1", learning_preview="p1", tool_name="t1", hit_count=3)
        gate.request_approval(2, org_id="org-1", learning_preview="p2", tool_name="t2", hit_count=7)
        gate.request_approval(3, org_id="org-2")
        gate.approve(2, reviewer="admin", notes="ok")

        results = gate.get_all(org_id="org-1")
        assert len(results) == 2
        # Check dict structure
        entry = results[0]
        expected_keys = {
            "learning_id", "org_id", "status", "requested_at",
            "reviewed_by", "review_notes", "learning_preview",
            "tool_name", "hit_count",
        }
        assert set(entry.keys()) == expected_keys

    def test_get_all_no_org_filter(self) -> None:
        gate = LearningApprovalGate()
        gate.request_approval(1, org_id="org-1")
        gate.request_approval(2, org_id="org-2")
        results = gate.get_all()
        assert len(results) == 2

    def test_get_all_limit(self) -> None:
        gate = LearningApprovalGate()
        for i in range(10):
            gate.request_approval(i)
        results = gate.get_all(limit=3)
        assert len(results) == 3

    def test_get_all_shows_status(self) -> None:
        gate = LearningApprovalGate()
        gate.request_approval(1)
        gate.request_approval(2)
        gate.approve(1, reviewer="admin")
        gate.reject(2, reviewer="admin", reason="bad")

        results = gate.get_all()
        statuses = {r["learning_id"]: r["status"] for r in results}
        assert statuses[1] == "approved"
        assert statuses[2] == "rejected"

    def test_get_all_includes_review_info(self) -> None:
        gate = LearningApprovalGate()
        gate.request_approval(1, org_id="org-1")
        gate.approve(1, reviewer="alice", notes="lgtm")
        results = gate.get_all()
        assert len(results) == 1
        assert results[0]["reviewed_by"] == "alice"
        assert results[0]["review_notes"] == "lgtm"

    def test_get_pending_sorted_newest_first(self) -> None:
        gate = LearningApprovalGate()
        # Create in order; each gets a slightly later timestamp
        a1 = gate.request_approval(1)
        a1.requested_at = 100.0
        a2 = gate.request_approval(2)
        a2.requested_at = 200.0
        a3 = gate.request_approval(3)
        a3.requested_at = 150.0

        pending = gate.get_pending()
        ids = [p.learning_id for p in pending]
        assert ids == [2, 3, 1]  # newest first
