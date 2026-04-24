Feature: Forensic Tagging (Spec 75)
  Every self-model write carries request_hash and perception_tool_call_id.

  @xfail
  Scenario: AC-75.1: ContextVars defined with None default
    Given the self_forensics module
    Then _request_hash_var and _perception_tool_call_id_var default to None

  @xfail
  Scenario: AC-75.2: request_scope sets and unsets request_hash
    Given the request_scope context manager
    When request_scope is entered with hash "abc123"
    Then _request_hash_var is "abc123" inside and None outside

  @xfail
  Scenario: AC-75.3: tool_call_scope sets and unsets perception_tool_call_id
    Given the tool_call_scope context manager
    When tool_call_scope is entered with id "tc:1"
    Then _perception_tool_call_id_var is "tc:1" inside and None outside

  @xfail
  Scenario: AC-75.4: Mirror functions stamp request_hash and tool_call_id
    Given a request_scope with hash "r1" and a tool_call_scope with id "tc1"
    When mirror_observation is called
    Then the memory context has request_hash "r1" and perception_tool_call_id "tc1"

  @xfail
  Scenario: AC-75.4: Mirror without scope has no hash
    Given no active scope
    When mirror_observation is called
    Then the memory context has no request_hash field

  @xfail
  Scenario: AC-75.5: Self-model rows carry forensics in request scope
    Given a request_scope with hash "r2"
    When note_passion is called
    Then the passion row context has request_hash "r2"

  @xfail
  Scenario: AC-75.6: Write without scope has provenance out_of_band
    Given no active scope
    When mirror_observation is called
    Then the memory context has provenance "out_of_band"

  @xfail
  Scenario: AC-75.7: Direct insert missing provenance raises
    Given a direct repo insert with no request_hash and no provenance
    When the insert is attempted
    Then an abort is raised for missing provenance

  @xfail
  Scenario: AC-75.8: Index on request_hash exists
    Given the database schema
    Then an index on json_extract(context, '$.request_hash') exists for episodic_memory

  @xfail
  Scenario: AC-75.9: Forensics CLI query works
    Given memories with request_hash "r3"
    When the forensics query runs for "r3"
    Then all matching memories are returned sorted by created_at

  @xfail
  Scenario: AC-75.10: Pipeline computes and binds request_hash
    Given a ChatRequest with known content
    When the pipeline starts
    Then request_hash is sha256 of canonical request truncated to 16 hex chars

  @xfail
  Scenario: AC-75.11: Tool call scope wraps each invocation
    Given a perception pipeline with a tool call
    When the tool executes
    Then a uuid4 tool_call_scope is active during execution

  @xfail
  Scenario: AC-75.12: Concurrent requests have isolated ContextVars
    Given two async tasks with different request_hashes
    When both run concurrently
    Then each task sees only its own request_hash

  @xfail
  Scenario: AC-75.13: Forked task inherits parent vars
    Given a request_scope with hash "parent"
    When a background task is forked
    Then the child sees hash "parent" until reassigned

  @xfail
  Scenario: AC-75.14: Request hash is 16 hex chars (64 bits)
    Given a ChatRequest
    When request_hash is computed
    Then the hash is exactly 16 hex characters
