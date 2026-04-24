Feature: Conduit Runtime (Spec 44)
  The perception → decision → dispatch → observation pipeline that lets the self converse.

  @xfail
  Scenario: AC-44.1: handle function signature
    Given a bootstrapped self with a runtime
    When handle is called with a valid request
    Then it returns a ChatResponse

  @xfail
  Scenario: AC-44.2: SelfRuntime holds required fields
    Given a SelfRuntime constructed with repo, self_id, warden, reactor, and llm_client
    When the runtime fields are inspected
    Then all six fields are populated

  @xfail
  Scenario: AC-44.3: Unbootstrapped self returns 503
    Given a self_id with no facets, answers, or mood
    When handle is called
    Then the response status is 503
    And the body contains "self not bootstrapped"

  @xfail
  Scenario: AC-44.4: Warden ingress block returns 400
    Given a bootstrapped self with a runtime
    And the warden is configured to block
    When handle is called with a message containing an injection payload
    Then the response status is 400
    And the body contains "blocked by warden"

  @xfail
  Scenario: AC-44.5: Minimal block rendered in perception context
    Given a bootstrapped self with a runtime
    When the perception step builds context
    Then render_minimal_block output is prepended to the perception prompt

  @xfail
  Scenario: AC-44.6: Semantic retrieval materializes contributors
    Given a bootstrapped self with a runtime and embedded memories
    When the perception step runs retrieval
    Then retrieval contributors are materialized per spec 74

  @xfail
  Scenario: AC-44.7: Perception LLM call respects budget and timeout
    Given a bootstrapped self with a runtime
    And the LLM client is configured to hang for 300 seconds
    When the perception step runs
    Then the response status is 504
    And the perception timeout is 30 seconds

  @xfail
  Scenario: AC-44.8: No decision tool call returns 500 after retry
    Given a bootstrapped self with a runtime
    And the LLM returns no tool calls
    When the perception step runs twice
    Then the response status is 500

  @xfail
  Scenario: AC-44.9: Self-tool after decision raises
    Given a bootstrapped self with a runtime
    And a decision has already been made
    When a self-tool call arrives after the decision
    Then SelfToolAfterDecision is raised

  @xfail
  Scenario: AC-44.10: Decision OBSERVATION written before dispatch
    Given a bootstrapped self with a runtime
    And the perception step produces a decision
    When the observation is written
    Then the decision OBSERVATION exists in the repo before dispatch runs

  @xfail
  Scenario: AC-44.11: Dispatch reply_directly
    Given a bootstrapped self with a runtime
    And the decision is reply_directly
    When dispatch runs
    Then the response contains the LLM reply text
    And the response status is 200

  @xfail
  Scenario: AC-44.11b: Dispatch delegate
    Given a bootstrapped self with a runtime
    And the decision is delegate with a target specialist
    When dispatch runs
    Then the specialist response is returned

  @xfail
  Scenario: AC-44.11c: Dispatch ask_clarifying
    Given a bootstrapped self with a runtime
    And the decision is ask_clarifying
    When dispatch runs
    Then a clarifying question is returned to the user

  @xfail
  Scenario: AC-44.11d: Dispatch decline
    Given a bootstrapped self with a runtime
    And the decision is decline
    When dispatch runs
    Then the refusal explains without revealing security details

  @xfail
  Scenario: AC-44.12: Warden outcome scan on dispatch content
    Given a bootstrapped self with a runtime
    And the dispatch content triggers a warden block
    When the outcome scan runs
    Then the response reflects the blocked outcome

  @xfail
  Scenario: AC-44.13: Observation LLM call with budget and timeout
    Given a bootstrapped self with a runtime that has dispatched
    When the observation step runs
    Then the observation LLM call has a 2000 token budget
    And the observation timeout is 15 seconds

  @xfail
  Scenario: AC-44.14: ChatResponse rendered from outcome
    Given a bootstrapped self with a runtime
    When the full pipeline completes successfully
    Then the ChatResponse has the OpenAI chat completion shape

  @xfail
  Scenario: AC-44.15: Per-self advisory lock
    Given two concurrent requests for the same self_id
    When both attempt the pipeline simultaneously
    Then only one proceeds at a time via advisory lock

  @xfail
  Scenario: AC-44.16: Lock force-released after timeout
    Given a self_id with a hung pipeline task
    When the safety margin timeout elapses
    Then the lock is force-released
    And the hung task's writes raise LockReleased

  @xfail
  Scenario: AC-44.17: Force-release writes REGRET
    Given a self_id with a force-released lock
    When the release completes
    Then a REGRET memory is written describing the lock timeout

  @xfail
  Scenario: AC-44.18: request_hash bound via scope
    Given a bootstrapped self with a runtime
    When the request pipeline starts
    Then request_hash is computed as sha256 of the canonical request
    And it is bound via request_scope for steps 2 through 8

  @xfail
  Scenario: AC-44.19: Request write budget shared across steps
    Given a bootstrapped self with a runtime
    When perception and observation steps both run
    Then they share the same RequestWriteBudget

  @xfail
  Scenario: AC-44.20: Tool call scope wraps each invocation
    Given a bootstrapped self with a runtime
    When a tool call is executed
    Then tool_call_scope wraps the invocation with a uuid4 id

  @xfail
  Scenario: AC-44.21: Client disconnect cancels dispatch
    Given a bootstrapped self with a runtime
    And the client disconnects between steps 5 and 7
    When the disconnect is detected
    Then dispatch is cancelled
    And steps 1 through 6 writes remain
    And step 8 runs with outcome "cancelled"

  @xfail
  Scenario: AC-44.22: Specialist exception becomes REGRET
    Given a bootstrapped self with a runtime
    And the specialist raises an exception
    When step 8 processes the outcome
    Then a REGRET or LESSON memory is written

  @xfail
  Scenario: AC-44.24: Prometheus histogram for step duration
    Given a bootstrapped self with a runtime
    When the pipeline completes
    Then turing_conduit_step_seconds is recorded for each step

  @xfail
  Scenario: AC-44.25: Prometheus decision counter
    Given a bootstrapped self with a runtime
    When a decision is made
    Then turing_conduit_decision_total is incremented with the decision label
