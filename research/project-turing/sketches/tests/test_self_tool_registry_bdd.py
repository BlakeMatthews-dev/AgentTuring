"""pytest-bdd step definitions for spec 68 (self-tool-registry)."""

from __future__ import annotations

import importlib
from typing import Any

import pytest
from pytest_bdd import given, when, then, scenarios

scenarios("features/self_tool_registry.feature")

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
    from turing.self_tool_registry import SelfTool

    return SelfTool(
        name=name,
        description=description,
        schema={"type": "object", "properties": {}},
        handler=handler,
        trust_tier=trust_tier,
    )


@given("a SelfTool constructor")
def tool_constructor() -> dict:
    return {}


@given('a valid SelfTool named "test"', target_fixture="tool_ctx")
def valid_tool() -> dict:
    tool = _make_tool(name="test")
    return {"tool": tool}


@given("a clean SELF_TOOL_REGISTRY", target_fixture="reg_ctx")
def clean_registry() -> dict:
    from turing.self_tool_registry import SELF_TOOL_REGISTRY

    saved = dict(SELF_TOOL_REGISTRY)
    SELF_TOOL_REGISTRY.clear()
    return {"saved": saved, "SELF_TOOL_REGISTRY": SELF_TOOL_REGISTRY}


@given("the self_tool_registry module is imported")
def module_imported() -> dict:
    return {}


@given(
    'a clean SELF_TOOL_REGISTRY with one registered tool "schematest"', target_fixture="schema_ctx"
)
def registry_with_schematest() -> dict:
    from turing.self_tool_registry import SELF_TOOL_REGISTRY, register_self_tool

    saved = dict(SELF_TOOL_REGISTRY)
    SELF_TOOL_REGISTRY.clear()
    register_self_tool(_make_tool(name="schematest"))
    return {"saved": saved, "SELF_TOOL_REGISTRY": SELF_TOOL_REGISTRY}


@given(
    'a clean SELF_TOOL_REGISTRY with one registered tool "cachetest"', target_fixture="cache_ctx"
)
def registry_with_cachetest(tmp_path) -> dict:
    from turing.self_tool_registry import SELF_TOOL_REGISTRY, register_self_tool

    saved = dict(SELF_TOOL_REGISTRY)
    SELF_TOOL_REGISTRY.clear()
    register_self_tool(_make_tool(name="cachetest"))
    cache_file = tmp_path / "self_tools.json"
    return {"saved": saved, "SELF_TOOL_REGISTRY": SELF_TOOL_REGISTRY, "cache_path": cache_file}


@given(
    'a clean SELF_TOOL_REGISTRY with tool "dispatch_test" and a fake handler',
    target_fixture="dispatch_ctx",
)
def registry_with_dispatch() -> dict:
    from turing.self_tool_registry import SELF_TOOL_REGISTRY, register_self_tool

    received: dict[str, Any] = {}

    def fake_handler(**kwargs: Any) -> None:
        received.update(kwargs)

    saved = dict(SELF_TOOL_REGISTRY)
    SELF_TOOL_REGISTRY.clear()
    register_self_tool(_make_tool(name="dispatch_test", handler=fake_handler))
    return {"saved": saved, "SELF_TOOL_REGISTRY": SELF_TOOL_REGISTRY, "received": received}


@given("a SelfRuntime instance", target_fixture="runtime_ctx")
def runtime_instance() -> dict:
    return {}


@given(
    'a clean SELF_TOOL_REGISTRY with tool "tx_fail" and a failing handler', target_fixture="tx_ctx"
)
def registry_with_failing(tmp_path) -> dict:
    from turing.self_tool_registry import SELF_TOOL_REGISTRY, register_self_tool

    def failing_handler(**kwargs: Any) -> None:
        raise RuntimeError("boom")

    observations: list[str] = []

    def fake_mirror(observation_text: str) -> None:
        observations.append(observation_text)

    saved = dict(SELF_TOOL_REGISTRY)
    SELF_TOOL_REGISTRY.clear()
    register_self_tool(_make_tool(name="tx_fail", handler=failing_handler))
    return {
        "saved": saved,
        "SELF_TOOL_REGISTRY": SELF_TOOL_REGISTRY,
        "observations": observations,
        "fake_mirror": fake_mirror,
    }


@given('a clean SELF_TOOL_REGISTRY with tool "tier_check"', target_fixture="tier_ctx")
def registry_with_tier() -> dict:
    from turing.self_tool_registry import SELF_TOOL_REGISTRY, register_self_tool

    saved = dict(SELF_TOOL_REGISTRY)
    SELF_TOOL_REGISTRY.clear()
    register_self_tool(_make_tool(name="tier_check"))
    return {"saved": saved, "SELF_TOOL_REGISTRY": SELF_TOOL_REGISTRY}


@given("the write_contributor function")
def write_contributor_fn() -> dict:
    return {}


@given("the record_personality_claim function")
def record_claim_fn() -> dict:
    return {}


@given("the retract_contributor_by_counter function")
def retract_fn() -> dict:
    return {}


@given(
    'a clean SELF_TOOL_REGISTRY with tool "notready_tool" that raises SelfNotReady',
    target_fixture="notready_ctx",
)
def registry_with_notready() -> dict:
    from turing.self_tool_registry import (
        SELF_TOOL_REGISTRY,
        SelfNotReady,
        register_self_tool,
    )

    mirrored: list[str] = []

    def not_ready_handler(**kwargs: Any) -> None:
        raise SelfNotReady("not bootstrapped")

    def fake_mirror(text: str) -> None:
        mirrored.append(text)

    saved = dict(SELF_TOOL_REGISTRY)
    SELF_TOOL_REGISTRY.clear()
    register_self_tool(_make_tool(name="notready_tool", handler=not_ready_handler))
    return {
        "saved": saved,
        "SELF_TOOL_REGISTRY": SELF_TOOL_REGISTRY,
        "mirrored": mirrored,
        "fake_mirror": fake_mirror,
    }


@when("a tool is created with a description over 400 characters")
def tool_desc_too_long(tool_constructor: dict) -> None:
    from turing.self_tool_registry import ToolRegistrationError

    long_desc = "I " + "x" * 500
    with pytest.raises(ToolRegistrationError, match="description too long"):
        _make_tool(description=long_desc)
    tool_constructor["passed"] = True


@when('a tool is created with trust_tier "t1"')
def tool_wrong_tier(tool_constructor: dict) -> None:
    from turing.self_tool_registry import ToolRegistrationError

    with pytest.raises(ToolRegistrationError, match="t0"):
        _make_tool(trust_tier="t1")
    tool_constructor["passed"] = True


@when("the tool name is reassigned")
def reassign_tool_name(tool_ctx: dict) -> None:
    tool = tool_ctx["tool"]
    try:
        tool.name = "mutated"
    except AttributeError:
        tool_ctx["caught_attribute_error"] = True


@when('a tool is created with name "valid" and description "I do valid things"')
def tool_valid(tool_constructor: dict) -> None:
    tool = _make_tool(name="valid", description="I do valid things")
    tool_constructor["tool"] = tool
    tool_constructor["passed"] = True


@when('register_self_tool is called with name "unique_insert_test"')
def register_unique(reg_ctx: dict) -> None:
    from turing.self_tool_registry import register_self_tool

    tool = _make_tool(name="unique_insert_test")
    register_self_tool(tool)
    reg_ctx["passed"] = True


@when('register_self_tool is called twice with name "dup_test"')
def register_dup(reg_ctx: dict) -> None:
    from turing.self_tool_registry import ToolRegistrationError, register_self_tool

    tool = _make_tool(name="dup_test")
    register_self_tool(tool)
    with pytest.raises(ToolRegistrationError, match="duplicate"):
        register_self_tool(tool)
    reg_ctx["passed"] = True


@when("SELF_TOOL_REGISTRY is inspected")
def inspect_registry(module_imported: dict) -> None:
    from turing.self_tool_registry import SELF_TOOL_REGISTRY, SelfTool

    module_imported["missing"] = []
    for name in _EXPECTED_TOOL_NAMES:
        if name not in SELF_TOOL_REGISTRY:
            module_imported["missing"].append(name)
        elif not isinstance(SELF_TOOL_REGISTRY[name], SelfTool):
            module_imported["missing"].append(f"{name}:not SelfTool")
    module_imported["passed"] = len(module_imported["missing"]) == 0


@when('a tool is created with description "The self notices things"')
def tool_bad_desc(tool_constructor: dict) -> None:
    from turing.self_tool_registry import ToolRegistrationError

    with pytest.raises(ToolRegistrationError, match="first-person"):
        _make_tool(description="The self notices things")
    tool_constructor["passed"] = True


@when('a tool is created with description "  I notice things"')
def tool_whitespace_desc(tool_constructor: dict) -> None:
    tool = _make_tool(description="  I notice things")
    tool_constructor["tool"] = tool
    tool_constructor["passed"] = True


@when("SelfRuntime.tool_schemas is called")
def call_tool_schemas(schema_ctx: dict) -> None:
    from turing.self_tool_registry import SelfRuntime

    rt = SelfRuntime()
    schemas = rt.tool_schemas()
    schema_ctx["schemas"] = schemas
    schema_ctx["passed"] = True


@when("SelfRuntime.tool_schemas is called with a cache_path")
def call_tool_schemas_cached(cache_ctx: dict) -> None:
    import json

    from turing.self_tool_registry import SelfRuntime

    rt = SelfRuntime(cache_path=cache_ctx["cache_path"])
    schemas1 = rt.tool_schemas()
    cache_ctx["schemas"] = schemas1
    cache_ctx["cache_exists"] = cache_ctx["cache_path"].exists()
    if cache_ctx["cache_path"].exists():
        with open(cache_ctx["cache_path"]) as f:
            cache_ctx["cached"] = json.load(f)
    schemas2 = rt.tool_schemas()
    cache_ctx["schemas_match"] = schemas2 == schemas1
    cache_ctx["passed"] = True


@when('SelfRuntime.invoke is called with tool "dispatch_test"')
def invoke_dispatch(dispatch_ctx: dict) -> None:
    from turing.self_tool_registry import SelfRuntime

    rt = SelfRuntime()
    rt.invoke("dispatch_test", self_id="self:1", args={"x": 42})
    dispatch_ctx["passed"] = True


@when('SelfRuntime.invoke is called with tool "nonexistent_tool"')
def invoke_unknown(runtime_ctx: dict) -> None:
    from turing.self_tool_registry import SelfRuntime, UnknownSelfTool

    rt = SelfRuntime()
    with pytest.raises(UnknownSelfTool):
        rt.invoke("nonexistent_tool", self_id="self:1", args={})
    runtime_ctx["passed"] = True


@when('SelfRuntime.invoke is called with tool "tx_fail"')
def invoke_failing(tx_ctx: dict) -> None:
    from turing.self_tool_registry import SelfRuntime

    rt = SelfRuntime(mirror_fn=tx_ctx["fake_mirror"])
    with pytest.raises(RuntimeError, match="boom"):
        rt.invoke("tx_fail", self_id="self:1", args={})
    tx_ctx["passed"] = True


@when('SelfRuntime.invoke is called with caller_tier "t1"')
def invoke_wrong_tier(tier_ctx: dict) -> None:
    from turing.self_tool_registry import SelfRuntime, TrustTierViolation

    rt = SelfRuntime()
    with pytest.raises(TrustTierViolation):
        rt.invoke("tier_check", self_id="self:1", args={}, caller_tier="t1")
    tier_ctx["passed"] = True


@when('write_contributor is called with origin "RETRIEVAL"')
def wc_retrieval(write_contributor_fn: dict) -> None:
    from turing.self_tool_registry import write_contributor

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
    write_contributor_fn["passed"] = True


@when("write_contributor is called with matching target and source node")
def wc_selfloop(write_contributor_fn: dict) -> None:
    from turing.self_tool_registry import write_contributor

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
    write_contributor_fn["passed"] = True


@when("record_personality_claim is called with nonexistent facet")
def rpc_bad_facet(record_claim_fn: dict) -> None:
    from turing.self_tool_registry import record_personality_claim

    with pytest.raises(ValueError, match="facet"):
        record_personality_claim(
            self_id="self:1",
            facet_id="nonexistent_facet",
            claim_text="I feel bold",
            evidence="observed boldness",
        )
    record_claim_fn["passed"] = True


@when("record_personality_claim is called with valid facet and claim")
def rpc_valid(record_claim_fn: dict) -> None:
    from turing.self_tool_registry import record_personality_claim

    result = record_personality_claim(
        self_id="self:1",
        facet_id="sincerity",
        claim_text="I am unusually honest",
        evidence="consistent truthful behavior",
    )
    record_claim_fn["result"] = result
    record_claim_fn["passed"] = True


@when("retract is called with weight 0.8")
def retract_valid(retract_fn: dict) -> None:
    from turing.self_tool_registry import retract_contributor_by_counter

    result = retract_contributor_by_counter(
        self_id="self:1",
        target_node_id="facet:1",
        source_id="mem:1",
        weight=0.8,
        rationale="outdated",
    )
    retract_fn["result"] = result
    retract_fn["passed"] = True


@when("retract is called with nonexistent target and source")
def retract_no_match(retract_fn: dict) -> None:
    from turing.self_tool_registry import NoMatchingContributor, retract_contributor_by_counter

    with pytest.raises(NoMatchingContributor):
        retract_contributor_by_counter(
            self_id="self:1",
            target_node_id="facet:ghost",
            source_id="mem:ghost",
            weight=0.5,
            rationale="nothing to retract",
        )
    retract_fn["passed"] = True


@when("the module is imported again")
def double_import(module_imported: dict) -> None:
    from turing.self_tool_registry import SELF_TOOL_REGISTRY, SelfTool

    count_before = len(SELF_TOOL_REGISTRY)
    importlib.import_module("turing.self_tool_registry")
    count_after = len(SELF_TOOL_REGISTRY)
    module_imported["count_match"] = count_before == count_after
    module_imported["all_selftool"] = all(
        isinstance(t, SelfTool) for t in SELF_TOOL_REGISTRY.values()
    )
    module_imported["passed"] = module_imported["count_match"] and module_imported["all_selftool"]


@when('SelfRuntime.invoke is called with tool "notready_tool"')
def invoke_notready(notready_ctx: dict) -> None:
    from turing.self_tool_registry import SelfNotReady, SelfRuntime

    rt = SelfRuntime(mirror_fn=notready_ctx["fake_mirror"])
    with pytest.raises(SelfNotReady):
        rt.invoke("notready_tool", self_id="self:1", args={})
    notready_ctx["passed"] = True


@then('ToolRegistrationError is raised matching "description too long"')
def tre_desc(tool_constructor: dict) -> None:
    assert tool_constructor.get("passed")


@then('ToolRegistrationError is raised matching "t0"')
def tre_tier(tool_constructor: dict) -> None:
    assert tool_constructor.get("passed")


@then("AttributeError is raised")
def attr_error(tool_ctx: dict) -> None:
    assert tool_ctx.get("caught_attribute_error")


@then('the tool name is "valid" and trust_tier is "t0"')
def tool_valid_props(tool_constructor: dict) -> None:
    tool = tool_constructor["tool"]
    assert tool.name == "valid"
    assert tool.trust_tier == "t0"


@then('the tool "unique_insert_test" is in SELF_TOOL_REGISTRY')
def tool_in_registry(reg_ctx: dict) -> None:
    from turing.self_tool_registry import SELF_TOOL_REGISTRY

    try:
        assert "unique_insert_test" in SELF_TOOL_REGISTRY
    finally:
        SELF_TOOL_REGISTRY.clear()
        SELF_TOOL_REGISTRY.update(reg_ctx["saved"])


@then('ToolRegistrationError is raised matching "duplicate"')
def tre_dup(reg_ctx: dict) -> None:
    from turing.self_tool_registry import SELF_TOOL_REGISTRY

    try:
        assert reg_ctx.get("passed")
    finally:
        SELF_TOOL_REGISTRY.clear()
        SELF_TOOL_REGISTRY.update(reg_ctx["saved"])


@then("all 19 expected tool names are present as SelfTool instances")
def all_tools(module_imported: dict) -> None:
    assert module_imported.get("passed"), f"Missing: {module_imported.get('missing')}"


@then('ToolRegistrationError is raised matching "first-person"')
def tre_first_person(tool_constructor: dict) -> None:
    assert tool_constructor.get("passed")


@then('the description starts with "I "')
def desc_starts(tool_constructor: dict) -> None:
    assert tool_constructor["tool"].description.startswith("I ")


@then("the result is a list with one entry of OpenAI function-call shape")
def schemas_shape(schema_ctx: dict) -> None:
    schemas = schema_ctx["schemas"]
    assert isinstance(schemas, list)
    assert len(schemas) == 1
    entry = schemas[0]
    assert entry["type"] == "function"
    fn = entry["function"]
    assert "name" in fn
    assert "description" in fn
    assert "parameters" in fn
    from turing.self_tool_registry import SELF_TOOL_REGISTRY

    SELF_TOOL_REGISTRY.clear()
    SELF_TOOL_REGISTRY.update(schema_ctx["saved"])


@then("a JSON file is written matching the schemas")
def json_cache(cache_ctx: dict) -> None:
    assert cache_ctx["cache_exists"]
    assert cache_ctx["cached"] == cache_ctx["schemas"]
    assert cache_ctx["schemas_match"]
    from turing.self_tool_registry import SELF_TOOL_REGISTRY

    SELF_TOOL_REGISTRY.clear()
    SELF_TOOL_REGISTRY.update(cache_ctx["saved"])


@then("the handler received the kwargs")
def handler_received(dispatch_ctx: dict) -> None:
    assert dispatch_ctx["received"] == {"self_id": "self:1", "x": 42}
    from turing.self_tool_registry import SELF_TOOL_REGISTRY

    SELF_TOOL_REGISTRY.clear()
    SELF_TOOL_REGISTRY.update(dispatch_ctx["saved"])


@then("UnknownSelfTool is raised")
def unknown_tool(runtime_ctx: dict) -> None:
    assert runtime_ctx.get("passed")


@then('RuntimeError is raised and an observation mentioning "tx_fail" is mirrored')
def tx_fail_observation(tx_ctx: dict) -> None:
    assert len(tx_ctx["observations"]) == 1
    assert "tx_fail" in tx_ctx["observations"][0]
    assert "boom" in tx_ctx["observations"][0]
    from turing.self_tool_registry import SELF_TOOL_REGISTRY

    SELF_TOOL_REGISTRY.clear()
    SELF_TOOL_REGISTRY.update(tx_ctx["saved"])


@then("TrustTierViolation is raised")
def tier_violation(tier_ctx: dict) -> None:
    from turing.self_tool_registry import SELF_TOOL_REGISTRY

    try:
        assert tier_ctx.get("passed")
    finally:
        SELF_TOOL_REGISTRY.clear()
        SELF_TOOL_REGISTRY.update(tier_ctx["saved"])


@then('ValueError is raised matching "RETRIEVAL"')
def val_retrieval(write_contributor_fn: dict) -> None:
    assert write_contributor_fn.get("passed")


@then('ValueError is raised matching "self-loop"')
def val_selfloop(write_contributor_fn: dict) -> None:
    assert write_contributor_fn.get("passed")


@then('ValueError is raised matching "facet"')
def val_facet(record_claim_fn: dict) -> None:
    assert record_claim_fn.get("passed")


@then('an OPINION memory with "I notice:" is returned')
def rpc_result(record_claim_fn: dict) -> None:
    result = record_claim_fn["result"]
    assert result is not None
    assert "I notice:" in result.content or "I notice: I am unusually honest" in str(result)


@then('a contributor with weight -0.8 and rationale starting "counter:" is returned')
def retract_result(retract_fn: dict) -> None:
    result = retract_fn["result"]
    assert result is not None
    assert result.weight == -0.8
    assert result.rationale.startswith("counter:")


@then("NoMatchingContributor is raised")
def no_match(retract_fn: dict) -> None:
    assert retract_fn.get("passed")


@then("SELF_TOOL_REGISTRY count is unchanged and all entries are SelfTool")
def idempotent(module_imported: dict) -> None:
    assert module_imported.get("passed")


@then("SelfNotReady is raised and no mirror was written")
def notready_no_mirror(notready_ctx: dict) -> None:
    assert notready_ctx["mirrored"] == []
    from turing.self_tool_registry import SELF_TOOL_REGISTRY

    SELF_TOOL_REGISTRY.clear()
    SELF_TOOL_REGISTRY.update(notready_ctx["saved"])
