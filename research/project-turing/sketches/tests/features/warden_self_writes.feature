Feature: Warden on Self-Writes (Spec 72)
  Every text the self writes into its own model passes through the Warden.

  @xfail
  Scenario: AC-72.1: Gate invokes warden scan and raises SelfWriteBlocked
    Given a warden configured to block
    When _warden_gate_self_write is called with injection text
    Then SelfWriteBlocked is raised with the verdict

  @xfail
  Scenario: AC-72.1: Clean text passes gate without error
    Given a warden configured to allow
    When _warden_gate_self_write is called with clean text
    Then no exception is raised

  @xfail
  Scenario: AC-72.2: note_passion calls gate with "note passion"
    Given an unbootstrapped self with a warden gate
    When note_passion is called with injection text
    Then SelfWriteBlocked is raised before repo write

  @xfail
  Scenario: AC-72.2: note_hobby calls gate with "note hobby"
    Given an unbootstrapped self with a warden gate
    When note_hobby is called with injection text
    Then SelfWriteBlocked is raised before repo write

  @xfail
  Scenario: AC-72.3: Blocked attempt produces no repo row or mirror
    Given a warden configured to block
    When _warden_gate_self_write is called
    Then no self-model row exists and no mirror memory exists

  @xfail
  Scenario: AC-72.4: Block writes OBSERVATION with warden reason
    Given a warden configured to block
    When _warden_gate_self_write is called with text "bad payload"
    Then an OBSERVATION memory exists with intent "warden blocked self write"

  @xfail
  Scenario: AC-72.5: Block memory carries mirror=True and request_hash
    Given a warden configured to block and a request scope
    When _warden_gate_self_write is called
    Then the block memory has context.mirror == True and context.request_hash

  @xfail
  Scenario: AC-72.6: Block memory uses only 80-char preview
    Given a warden configured to block
    When _warden_gate_self_write is called with text over 80 chars
    Then the block memory preview is at most 80 chars

  @xfail
  Scenario: AC-72.7: Warden trust posture is TOOL_RESULT
    Given the _warden_gate_self_write implementation
    Then the warden is called with trust TOOL_RESULT

  @xfail
  Scenario: AC-72.8: Bootstrap-time inserts skip gate
    Given a bootstrapped self
    Then bootstrap inserts did not trigger warden scans

  @xfail
  Scenario: AC-72.9: Mood nudges skip gate
    Given a self with mood
    When nudge_mood is called
    Then no warden scan occurred

  @xfail
  Scenario: AC-72.10: Prometheus counter increments on block
    Given a warden configured to block
    When _warden_gate_self_write is called with intent "note passion"
    Then turing_self_write_blocked_total increments for intent "note passion"

  @xfail
  Scenario: AC-72.11: Warden transient failure raises WardenUnavailable
    Given a warden that throws WardenTransientError
    When _warden_gate_self_write is called
    Then a block memory with reason "warden unavailable" is written

  @xfail
  Scenario: AC-72.12: Text over 10k chars is truncated before scan
    Given a warden configured to allow
    When _warden_gate_self_write is called with text over 10000 chars
    Then the warden received at most 10000 chars

  @xfail
  Scenario: AC-72.13: Config update mid-session does not cache
    Given a warden that changes from allow to block
    When _warden_gate_self_write is called twice
    Then the second call is blocked
