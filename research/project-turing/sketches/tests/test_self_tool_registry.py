"""Tests for specs/self-tool-registry.md: AC-31.* (mapped as AC-68.*)."""

from __future__ import annotations

import importlib
from typing import Any

import pytest

_EXPECTED_TOOL_NAMES = frozenset(
    {
        "recall_self",
        "write_self_todo",
        "note_passion",
        "note_hobby",
        "note_interest",
        "note_preference",
        "note_skill",
        "revise_self_todo",
        "complete_self_todo",
        "archive_self_todo",
        "practice_skill",
        "downgrade_skill",
        "rerank_passions",
        "write_contributor",
        "record_personality_claim",
        "retract_contributor_by_counter",
        "note_engagement",
        "note_interest_trigger",
    }
)


def _make_tool(
    name: str = "test_tool",
    description: str = "I test things",
    trust_tier: str = "t0",
    handler: Any = lambda **kw: None,
) -> Any:
    from turing.self_tool_registry import SelfTool  # not implemented yet

    return SelfTool(
        name=name,
        description=description,
        schema={"type": "object", "properties": {}},
        handler=handler,
        trust_tier=trust_tier,
    )


# ---------- AC-68.1 — SelfTool validation ----------------------------------


@pytest.mark.xfail(reason="AC-68.1: self-tool-registry not implemented")
def test_ac_68_1_description_too_long_raises() -> None:
    from turing.self_tool_registry import ToolRegistrationError  # not implemented yet

    long_desc = "I " + "x" * 500
    with pytest.raises(ToolRegistrationError, match="description too long"):
        _make_tool(description=long_desc)


@pytest.mark.xfail(reason="AC-68.1: self-tool-registry not implemented")
def test_ac_68_1_trust_tier_not_t0_raises() -> None:
    from turing.self_tool_registry import ToolRegistrationError  # not implemented yet

    with pytest.raises(ToolRegistrationError, match="t0"):
        _make_tool(trust_tier="t1")


@pytest.mark.xfail(reason="AC-68.1: self-tool-registry not implemented")
def test_ac_68_1_frozen_dataclass_rejects_mutation() -> None:
    tool = _make_tool()
    with pytest.raises(AttributeError):
        tool.name = "mutated"


@pytest.mark.xfail(reason="AC-68.1: self-tool-registry not implemented")
def test_ac_68_1_valid_tool_constructs() -> None:
    tool = _make_tool(name="valid", description="I do valid things")
    assert tool.name == "valid"
    assert tool.trust_tier == "t0"


# ---------- AC-68.2 — SELF_TOOL_REGISTRY + register_self_tool ---------------


@pytest.mark.xfail(reason="AC-68.2: self-tool-registry not implemented")
def test_ac_68_2_register_inserts_into_registry() -> None:
    from turing.self_tool_registry import (
        SELF_TOOL_REGISTRY,
        register_self_tool,
    )  # not implemented yet

    tool = _make_tool(name="unique_insert_test")
    saved = dict(SELF_TOOL_REGISTRY)
    try:
        register_self_tool(tool)
        assert SELF_TOOL_REGISTRY["unique_insert_test"] is tool
    finally:
        SELF_TOOL_REGISTRY.clear()
        SELF_TOOL_REGISTRY.update(saved)


@pytest.mark.xfail(reason="AC-68.2: self-tool-registry not implemented")
def test_ac_68_2_duplicate_registration_raises() -> None:
    from turing.self_tool_registry import (
        SELF_TOOL_REGISTRY,
        ToolRegistrationError,
        register_self_tool,
    )  # not implemented yet

    tool = _make_tool(name="dup_test")
    saved = dict(SELF_TOOL_REGISTRY)
    try:
        register_self_tool(tool)
        with pytest.raises(ToolRegistrationError, match="duplicate"):
            register_self_tool(tool)
    finally:
        SELF_TOOL_REGISTRY.clear()
        SELF_TOOL_REGISTRY.update(saved)


# ---------- AC-68.3 — all expected tools present after import ---------------


@pytest.mark.xfail(reason="AC-68.3: self-tool-registry not implemented")
def test_ac_68_3_all_spec28_tools_present() -> None:
    from turing.self_tool_registry import SELF_TOOL_REGISTRY, SelfTool  # not implemented yet

    for name in _EXPECTED_TOOL_NAMES:
        assert name in SELF_TOOL_REGISTRY, f"missing tool: {name}"
        assert isinstance(SELF_TOOL_REGISTRY[name], SelfTool)


# ---------- AC-68.4 — description must start with "I " ----------------------


@pytest.mark.xfail(reason="AC-68.4: self-tool-registry not implemented")
def test_ac_68_4_description_must_start_with_first_person() -> None:
    from turing.self_tool_registry import ToolRegistrationError  # not implemented yet

    with pytest.raises(ToolRegistrationError, match="first-person"):
        _make_tool(description="The self notices things")


@pytest.mark.xfail(reason="AC-68.4: self-tool-registry not implemented")
def test_ac_68_4_description_with_leading_whitespace_passes() -> None:
    tool = _make_tool(description="  I notice things")
    assert tool.description.startswith("I ")


# ---------- AC-68.5 — tool_schemas() returns OpenAI shape -------------------


@pytest.mark.xfail(reason="AC-68.5: self-tool-registry not implemented")
def test_ac_68_5_tool_schemas_openai_function_shape() -> None:
    from turing.self_tool_registry import (
        SELF_TOOL_REGISTRY,
        SelfRuntime,
        register_self_tool,
    )  # not implemented yet

    saved = dict(SELF_TOOL_REGISTRY)
    try:
        SELF_TOOL_REGISTRY.clear()
        register_self_tool(_make_tool(name="schematest"))
        rt = SelfRuntime()
        schemas = rt.tool_schemas()
        assert isinstance(schemas, list)
        assert len(schemas) == 1
        entry = schemas[0]
        assert entry["type"] == "function"
        fn = entry["function"]
        assert "name" in fn
        assert "description" in fn
        assert "parameters" in fn
    finally:
        SELF_TOOL_REGISTRY.clear()
        SELF_TOOL_REGISTRY.update(saved)


# ---------- AC-68.6 — tool_schemas() writes JSON cache -----------------------


@pytest.mark.xfail(reason="AC-68.6: self-tool-registry not implemented")
def test_ac_68_6_tool_schemas_writes_json_cache(tmp_path) -> None:
    import json

    from turing.self_tool_registry import (
        SELF_TOOL_REGISTRY,
        SelfRuntime,
        register_self_tool,
    )  # not implemented yet

    saved = dict(SELF_TOOL_REGISTRY)
    cache_file = tmp_path / "self_tools.json"
    try:
        SELF_TOOL_REGISTRY.clear()
        register_self_tool(_make_tool(name="cachetest"))
        rt = SelfRuntime(cache_path=cache_file)
        schemas1 = rt.tool_schemas()
        assert cache_file.exists()
        with open(cache_file) as f:
            cached = json.load(f)
        assert cached == schemas1
        schemas2 = rt.tool_schemas()
        assert schemas2 == schemas1
    finally:
        SELF_TOOL_REGISTRY.clear()
        SELF_TOOL_REGISTRY.update(saved)


# ---------- AC-68.7 — invoke dispatches; unknown raises ---------------------


@pytest.mark.xfail(reason="AC-68.7: self-tool-registry not implemented")
def test_ac_68_7_invoke_dispatches_to_handler() -> None:
    from turing.self_tool_registry import (
        SELF_TOOL_REGISTRY,
        SelfRuntime,
        register_self_tool,
    )  # not implemented yet

    received: dict[str, Any] = {}

    def fake_handler(**kwargs: Any) -> None:
        received.update(kwargs)

    saved = dict(SELF_TOOL_REGISTRY)
    try:
        SELF_TOOL_REGISTRY.clear()
        register_self_tool(_make_tool(name="dispatch_test", handler=fake_handler))
        rt = SelfRuntime()
        rt.invoke("dispatch_test", self_id="self:1", args={"x": 42})
        assert received == {"self_id": "self:1", "x": 42}
    finally:
        SELF_TOOL_REGISTRY.clear()
        SELF_TOOL_REGISTRY.update(saved)


@pytest.mark.xfail(reason="AC-68.7: self-tool-registry not implemented")
def test_ac_68_7_invoke_unknown_tool_raises() -> None:
    from turing.self_tool_registry import SelfRuntime, UnknownSelfTool  # not implemented yet

    rt = SelfRuntime()
    with pytest.raises(UnknownSelfTool):
        rt.invoke("nonexistent_tool", self_id="self:1", args={})


# ---------- AC-68.8 — invoke transaction + failure observation ---------------


@pytest.mark.xfail(reason="AC-68.8: self-tool-registry not implemented")
def test_ac_68_8_invoke_wraps_in_transaction_rollback_on_error() -> None:
    from turing.self_tool_registry import (
        SELF_TOOL_REGISTRY,
        SelfRuntime,
        register_self_tool,
    )  # not implemented yet

    observations: list[str] = []

    def failing_handler(**kwargs: Any) -> None:
        raise RuntimeError("boom")

    def fake_mirror(observation_text: str) -> None:
        observations.append(observation_text)

    saved = dict(SELF_TOOL_REGISTRY)
    try:
        SELF_TOOL_REGISTRY.clear()
        register_self_tool(_make_tool(name="tx_fail", handler=failing_handler))
        rt = SelfRuntime(mirror_fn=fake_mirror)
        with pytest.raises(RuntimeError, match="boom"):
            rt.invoke("tx_fail", self_id="self:1", args={})
        assert len(observations) == 1
        assert "tx_fail" in observations[0]
        assert "boom" in observations[0]
    finally:
        SELF_TOOL_REGISTRY.clear()
        SELF_TOOL_REGISTRY.update(saved)


# ---------- AC-68.9 — invoke trust-tier enforcement -------------------------


@pytest.mark.xfail(reason="AC-68.9: self-tool-registry not implemented")
def test_ac_68_9_invoke_rejects_non_t0_caller() -> None:
    from turing.self_tool_registry import (
        SELF_TOOL_REGISTRY,
        SelfRuntime,
        TrustTierViolation,
        register_self_tool,
    )  # not implemented yet

    saved = dict(SELF_TOOL_REGISTRY)
    try:
        SELF_TOOL_REGISTRY.clear()
        register_self_tool(_make_tool(name="tier_check"))
        rt = SelfRuntime()
        with pytest.raises(TrustTierViolation):
            rt.invoke("tier_check", self_id="self:1", args={}, caller_tier="t1")
    finally:
        SELF_TOOL_REGISTRY.clear()
        SELF_TOOL_REGISTRY.update(saved)


# ---------- AC-68.10 — write_contributor tool ------------------------------


@pytest.mark.xfail(reason="AC-68.10: self-tool-registry not implemented")
def test_ac_68_10_write_contributor_rejects_retrieval_origin() -> None:
    from turing.self_tool_registry import write_contributor  # not implemented yet

    with pytest.raises(ValueError, match="RETRIEVAL"):
        write_contributor(
            self_id="self:1",
            target_node_id="facet:1",
            target_kind="facet",
            source_id="mem:1",
            source_kind="memory",
            weight=0.5,
            rationale="test",
            origin="RETRIEVAL",
        )


@pytest.mark.xfail(reason="AC-68.10: self-tool-registry not implemented")
def test_ac_68_10_write_contributor_rejects_self_loop() -> None:
    from turing.self_tool_registry import write_contributor  # not implemented yet

    with pytest.raises(ValueError, match="self-loop"):
        write_contributor(
            self_id="self:1",
            target_node_id="node:A",
            target_kind="facet",
            source_id="node:A",
            source_kind="memory",
            weight=0.5,
            rationale="loop",
        )


# ---------- AC-68.11 — record_personality_claim tool ------------------------


@pytest.mark.xfail(reason="AC-68.11: self-tool-registry not implemented")
def test_ac_68_11_record_personality_claim_validates_facet() -> None:
    from turing.self_tool_registry import record_personality_claim  # not implemented yet

    with pytest.raises(ValueError, match="facet"):
        record_personality_claim(
            self_id="self:1",
            facet_id="nonexistent_facet",
            claim_text="I feel bold",
            evidence="observed boldness",
        )


@pytest.mark.xfail(reason="AC-68.11: self-tool-registry not implemented")
def test_ac_68_11_record_personality_claim_mints_opinion() -> None:
    from turing.self_tool_registry import record_personality_claim  # not implemented yet

    result = record_personality_claim(
        self_id="self:1",
        facet_id="sincerity",
        claim_text="I am unusually honest",
        evidence="consistent truthful behavior",
    )
    assert result is not None
    assert "I notice:" in result.content or "I notice: I am unusually honest" in str(result)


# ---------- AC-68.12 — retract_contributor_by_counter ----------------------


@pytest.mark.xfail(reason="AC-68.12: self-tool-registry not implemented")
def test_ac_68_12_retract_writes_negated_contributor() -> None:
    from turing.self_tool_registry import retract_contributor_by_counter  # not implemented yet

    result = retract_contributor_by_counter(
        self_id="self:1",
        target_node_id="facet:1",
        source_id="mem:1",
        weight=0.8,
        rationale="outdated",
    )
    assert result is not None
    assert result.weight == -0.8
    assert result.rationale.startswith("counter:")


# ---------- AC-68.13 — retract with no match raises -------------------------


@pytest.mark.xfail(reason="AC-68.13: self-tool-registry not implemented")
def test_ac_68_13_retract_no_match_raises() -> None:
    from turing.self_tool_registry import (  # not implemented yet
        NoMatchingContributor,
        retract_contributor_by_counter,
    )

    with pytest.raises(NoMatchingContributor):
        retract_contributor_by_counter(
            self_id="self:1",
            target_node_id="facet:ghost",
            source_id="mem:ghost",
            weight=0.5,
            rationale="nothing to retract",
        )


# ---------- AC-68.14 — double import is idempotent --------------------------


@pytest.mark.xfail(reason="AC-68.14: self-tool-registry not implemented")
def test_ac_68_14_double_import_no_duplicates() -> None:
    from turing.self_tool_registry import SELF_TOOL_REGISTRY, SelfTool  # not implemented yet

    count_before = len(SELF_TOOL_REGISTRY)
    importlib.import_module("turing.self_tool_registry")
    count_after = len(SELF_TOOL_REGISTRY)
    assert count_before == count_after
    for name, tool in SELF_TOOL_REGISTRY.items():
        assert isinstance(tool, SelfTool)


# ---------- AC-68.15 — SelfNotReady does not leak partial mirror ------------


@pytest.mark.xfail(reason="AC-68.15: self-tool-registry not implemented")
def test_ac_68_15_self_not_ready_no_partial_mirror() -> None:
    from turing.self_tool_registry import (  # not implemented yet
        SELF_TOOL_REGISTRY,
        SelfNotReady,
        SelfRuntime,
        register_self_tool,
    )

    mirrored: list[str] = []

    def not_ready_handler(**kwargs: Any) -> None:
        raise SelfNotReady("not bootstrapped")

    def fake_mirror(text: str) -> None:
        mirrored.append(text)

    saved = dict(SELF_TOOL_REGISTRY)
    try:
        SELF_TOOL_REGISTRY.clear()
        register_self_tool(_make_tool(name="notready_tool", handler=not_ready_handler))
        rt = SelfRuntime(mirror_fn=fake_mirror)
        with pytest.raises(SelfNotReady):
            rt.invoke("notready_tool", self_id="self:1", args={})
        assert mirrored == []
    finally:
        SELF_TOOL_REGISTRY.clear()
        SELF_TOOL_REGISTRY.update(saved)
