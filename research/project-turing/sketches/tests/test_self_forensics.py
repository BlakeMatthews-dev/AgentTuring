"""Tests for forensic tagging (AC-39.1..6) and provenance in mirror bridge."""

from __future__ import annotations

import pytest

from turing.self_forensics import (
    get_perception_tool_call_id,
    get_request_hash,
    request_scope,
    tool_call_scope,
)
from turing.self_memory_bridge import mirror_observation, set_mirror_request_hash


class TestSelfForensics:
    def test_get_request_hash_none_outside_scope(self) -> None:
        assert get_request_hash() is None

    def test_get_request_hash_inside_scope(self) -> None:
        with request_scope("hash-abc"):
            assert get_request_hash() == "hash-abc"
        assert get_request_hash() is None

    def test_nested_request_scope_raises(self) -> None:
        with request_scope("outer"):
            with pytest.raises(RuntimeError):
                with request_scope("inner"):
                    pass

    def test_get_perception_tool_call_id_inside_scope(self) -> None:
        assert get_perception_tool_call_id() is None
        with tool_call_scope("tc-1"):
            assert get_perception_tool_call_id() == "tc-1"
        assert get_perception_tool_call_id() is None

    def test_nested_tool_call_scope_inner_wins(self) -> None:
        with tool_call_scope("outer-tc"):
            assert get_perception_tool_call_id() == "outer-tc"
            with tool_call_scope("inner-tc"):
                assert get_perception_tool_call_id() == "inner-tc"
            assert get_perception_tool_call_id() == "outer-tc"


class TestProvenance:
    def test_mirror_inside_request_scope_has_request_hash(self, repo, bootstrapped_id) -> None:
        set_mirror_request_hash("req-xyz")
        try:
            mid = mirror_observation(repo, bootstrapped_id, "obs", "intent")
            m = repo.get(mid)
            assert m.context.get("request_hash") == "req-xyz"
        finally:
            set_mirror_request_hash(None)

    def test_mirror_outside_scope_has_out_of_band(self, repo, bootstrapped_id) -> None:
        mid = mirror_observation(repo, bootstrapped_id, "obs", "intent")
        m = repo.get(mid)
        assert m.context.get("provenance") == "out_of_band"

    def test_mirror_explicit_provenance_kept(self, repo, bootstrapped_id) -> None:
        mid = mirror_observation(
            repo, bootstrapped_id, "obs", "intent", context={"provenance": "custom"}
        )
        m = repo.get(mid)
        assert m.context.get("provenance") == "custom"
