Feature: Self-tool Registry (Spec 68)
  The runtime surface that turns self-tool Python functions into OpenAI function-call schemas.

  @xfail
  Scenario: AC-68.1: Description too long raises ToolRegistrationError
    Given a SelfTool constructor
    When a tool is created with a description over 400 characters
    Then ToolRegistrationError is raised matching "description too long"

  @xfail
  Scenario: AC-68.1: Trust tier not t0 raises ToolRegistrationError
    Given a SelfTool constructor
    When a tool is created with trust_tier "t1"
    Then ToolRegistrationError is raised matching "t0"

  @xfail
  Scenario: AC-68.1: Frozen dataclass rejects mutation
    Given a valid SelfTool named "test"
    When the tool name is reassigned
    Then AttributeError is raised

  @xfail
  Scenario: AC-68.1: Valid tool constructs successfully
    Given a SelfTool constructor
    When a tool is created with name "valid" and description "I do valid things"
    Then the tool name is "valid" and trust_tier is "t0"

  @xfail
  Scenario: AC-68.2: Register inserts into registry
    Given a clean SELF_TOOL_REGISTRY
    When register_self_tool is called with name "unique_insert_test"
    Then the tool "unique_insert_test" is in SELF_TOOL_REGISTRY

  @xfail
  Scenario: AC-68.2: Duplicate registration raises ToolRegistrationError
    Given a clean SELF_TOOL_REGISTRY
    When register_self_tool is called twice with name "dup_test"
    Then ToolRegistrationError is raised matching "duplicate"

  @xfail
  Scenario: AC-68.3: All spec-28 tools present after import
    Given the self_tool_registry module is imported
    When SELF_TOOL_REGISTRY is inspected
    Then all 19 expected tool names are present as SelfTool instances

  @xfail
  Scenario: AC-68.4: Description must start with first-person "I "
    Given a SelfTool constructor
    When a tool is created with description "The self notices things"
    Then ToolRegistrationError is raised matching "first-person"

  @xfail
  Scenario: AC-68.4: Description with leading whitespace still passes
    Given a SelfTool constructor
    When a tool is created with description "  I notice things"
    Then the description starts with "I "

  @xfail
  Scenario: AC-68.5: tool_schemas returns OpenAI function shape
    Given a clean SELF_TOOL_REGISTRY with one registered tool "schematest"
    When SelfRuntime.tool_schemas is called
    Then the result is a list with one entry of OpenAI function-call shape

  @xfail
  Scenario: AC-68.6: tool_schemas writes JSON cache
    Given a clean SELF_TOOL_REGISTRY with one registered tool "cachetest"
    When SelfRuntime.tool_schemas is called with a cache_path
    Then a JSON file is written matching the schemas

  @xfail
  Scenario: AC-68.7: invoke dispatches to handler
    Given a clean SELF_TOOL_REGISTRY with tool "dispatch_test" and a fake handler
    When SelfRuntime.invoke is called with tool "dispatch_test"
    Then the handler received the kwargs

  @xfail
  Scenario: AC-68.7: invoke unknown tool raises UnknownSelfTool
    Given a SelfRuntime instance
    When SelfRuntime.invoke is called with tool "nonexistent_tool"
    Then UnknownSelfTool is raised

  @xfail
  Scenario: AC-68.8: invoke wraps in transaction rollback on error
    Given a clean SELF_TOOL_REGISTRY with tool "tx_fail" and a failing handler
    When SelfRuntime.invoke is called with tool "tx_fail"
    Then RuntimeError is raised and an observation mentioning "tx_fail" is mirrored

  @xfail
  Scenario: AC-68.9: invoke rejects non-t0 caller
    Given a clean SELF_TOOL_REGISTRY with tool "tier_check"
    When SelfRuntime.invoke is called with caller_tier "t1"
    Then TrustTierViolation is raised

  @xfail
  Scenario: AC-68.10: write_contributor rejects RETRIEVAL origin
    Given the write_contributor function
    When write_contributor is called with origin "RETRIEVAL"
    Then ValueError is raised matching "RETRIEVAL"

  @xfail
  Scenario: AC-68.10: write_contributor rejects self-loop
    Given the write_contributor function
    When write_contributor is called with matching target and source node
    Then ValueError is raised matching "self-loop"

  @xfail
  Scenario: AC-68.11: record_personality_claim validates facet
    Given the record_personality_claim function
    When record_personality_claim is called with nonexistent facet
    Then ValueError is raised matching "facet"

  @xfail
  Scenario: AC-68.11: record_personality_claim mints opinion
    Given the record_personality_claim function
    When record_personality_claim is called with valid facet and claim
    Then an OPINION memory with "I notice:" is returned

  @xfail
  Scenario: AC-68.12: retract writes negated contributor
    Given the retract_contributor_by_counter function
    When retract is called with weight 0.8
    Then a contributor with weight -0.8 and rationale starting "counter:" is returned

  @xfail
  Scenario: AC-68.13: retract with no match raises NoMatchingContributor
    Given the retract_contributor_by_counter function
    When retract is called with nonexistent target and source
    Then NoMatchingContributor is raised

  @xfail
  Scenario: AC-68.14: Double import is idempotent
    Given the self_tool_registry module is imported
    When the module is imported again
    Then SELF_TOOL_REGISTRY count is unchanged and all entries are SelfTool

  @xfail
  Scenario: AC-68.15: SelfNotReady does not leak partial mirror
    Given a clean SELF_TOOL_REGISTRY with tool "notready_tool" that raises SelfNotReady
    When SelfRuntime.invoke is called with tool "notready_tool"
    Then SelfNotReady is raised and no mirror was written
