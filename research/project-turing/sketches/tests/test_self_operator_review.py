from __future__ import annotations

import pytest

from turing.self_model import ActivationContributor, ContributorOrigin, NodeKind
from turing.self_operator_review import (
    ack_pending,
    insert_pending_contributor,
    is_gated_target,
    list_pending,
)


def _make_contributor(bootstrapped_id: str, new_id) -> ActivationContributor:
    return ActivationContributor(
        node_id=new_id("contrib"),
        self_id=bootstrapped_id,
        target_node_id="facet:honesty_humility.sincerity",
        target_kind=NodeKind.PERSONALITY_FACET,
        source_id=new_id("source"),
        source_kind="observation",
        weight=0.7,
        origin=ContributorOrigin.SELF,
        rationale="test contributor",
    )


class TestIsGatedTarget:
    def test_personality_facet_is_gated(self):
        assert is_gated_target(NodeKind.PERSONALITY_FACET) is True

    def test_hobby_is_not_gated(self):
        assert is_gated_target(NodeKind.HOBBY) is False

    def test_passion_is_gated(self):
        assert is_gated_target(NodeKind.PASSION) is True


class TestPendingContributorFlow:
    def test_insert_and_list(self, repo, srepo, bootstrapped_id, new_id):
        contrib = _make_contributor(bootstrapped_id, new_id)
        insert_pending_contributor(repo, contrib, acting_self_id=bootstrapped_id)
        pending = list_pending(repo, bootstrapped_id)
        assert len(pending) == 1
        assert pending[0]["node_id"] == contrib.node_id
        assert pending[0]["target_node_id"] == contrib.target_node_id

    def test_ack_approve_moves_to_live(self, repo, srepo, bootstrapped_id, new_id):
        contrib = _make_contributor(bootstrapped_id, new_id)
        insert_pending_contributor(repo, contrib, acting_self_id=bootstrapped_id)
        ack_pending(repo, contrib.node_id, "approve", reviewed_by="operator")
        row = repo.conn.execute(
            "SELECT node_id FROM self_activation_contributors WHERE node_id = ?",
            (contrib.node_id,),
        ).fetchone()
        assert row is not None

    def test_ack_reject_does_not_add_to_live(self, repo, srepo, bootstrapped_id, new_id):
        contrib = _make_contributor(bootstrapped_id, new_id)
        insert_pending_contributor(repo, contrib, acting_self_id=bootstrapped_id)
        ack_pending(repo, contrib.node_id, "reject", reviewed_by="operator")
        row = repo.conn.execute(
            "SELECT node_id FROM self_activation_contributors WHERE node_id = ?",
            (contrib.node_id,),
        ).fetchone()
        assert row is None

    def test_ack_unknown_node_raises_value_error(self, repo):
        with pytest.raises(ValueError, match="no pending contributor"):
            ack_pending(repo, "nonexistent:id", "approve", reviewed_by="op")

    def test_list_pending_excludes_reviewed(self, repo, srepo, bootstrapped_id, new_id):
        contrib = _make_contributor(bootstrapped_id, new_id)
        insert_pending_contributor(repo, contrib, acting_self_id=bootstrapped_id)
        ack_pending(repo, contrib.node_id, "approve", reviewed_by="operator")
        pending = list_pending(repo, bootstrapped_id)
        assert all(p["node_id"] != contrib.node_id for p in pending)
