Feature: Self-write Preconditions (Spec 71)
  Bootstrap-complete checks, activation cache, and cross-self guards.

  @xfail
  Scenario: AC-71.1: Bootstrap complete returns True when all met
    Given a fully bootstrapped self
    Then _bootstrap_complete returns True

  @xfail
  Scenario: AC-71.1: False when facets missing
    Given an empty self with no data
    Then _bootstrap_complete returns False

  @xfail
  Scenario: AC-71.1: False when no answers
    Given a self with 24 facets but no answers or mood
    Then _bootstrap_complete returns False

  @xfail
  Scenario: AC-71.1: False when no mood
    Given a self with 24 facets and 200 answers but no mood
    Then _bootstrap_complete returns False

  @xfail
  Scenario: AC-71.2: note_passion raises before bootstrap
    Given an unbootstrapped self
    When note_passion is called
    Then SelfNotReady is raised

  @xfail
  Scenario: AC-71.2: note_hobby raises before bootstrap
    Given an unbootstrapped self
    When note_hobby is called
    Then SelfNotReady is raised

  @xfail
  Scenario: AC-71.2: note_interest raises before bootstrap
    Given an unbootstrapped self
    When note_interest is called
    Then SelfNotReady is raised

  @xfail
  Scenario: AC-71.2: note_preference raises before bootstrap
    Given an unbootstrapped self
    When note_preference is called
    Then SelfNotReady is raised

  @xfail
  Scenario: AC-71.2: note_skill raises before bootstrap
    Given an unbootstrapped self
    When note_skill is called
    Then SelfNotReady is raised

  @xfail
  Scenario: AC-71.2: write_self_todo raises before bootstrap
    Given an unbootstrapped self
    When write_self_todo is called
    Then SelfNotReady is raised

  @xfail
  Scenario: AC-71.2: revise_self_todo raises before bootstrap
    Given an unbootstrapped self
    When revise_self_todo is called
    Then SelfNotReady is raised

  @xfail
  Scenario: AC-71.2: complete_self_todo raises before bootstrap
    Given an unbootstrapped self
    When complete_self_todo is called
    Then SelfNotReady is raised

  @xfail
  Scenario: AC-71.2: archive_self_todo raises before bootstrap
    Given an unbootstrapped self
    When archive_self_todo is called
    Then SelfNotReady is raised

  @xfail
  Scenario: AC-71.2: practice_skill raises before bootstrap
    Given an unbootstrapped self
    When practice_skill is called
    Then SelfNotReady is raised

  @xfail
  Scenario: AC-71.2: downgrade_skill raises before bootstrap
    Given an unbootstrapped self
    When downgrade_skill is called
    Then SelfNotReady is raised

  @xfail
  Scenario: AC-71.2: rerank_passions raises before bootstrap
    Given an unbootstrapped self
    When rerank_passions is called
    Then SelfNotReady is raised

  @xfail
  Scenario: AC-71.2: write_contributor raises before bootstrap
    Given an unbootstrapped self
    When write_contributor is called
    Then SelfNotReady is raised

  @xfail
  Scenario: AC-71.2: record_personality_claim raises before bootstrap
    Given an unbootstrapped self
    When record_personality_claim is called
    Then SelfNotReady is raised

  @xfail
  Scenario: AC-71.2: retract_contributor_by_counter raises before bootstrap
    Given an unbootstrapped self
    When retract_contributor_by_counter is called
    Then SelfNotReady is raised

  @xfail
  Scenario: AC-71.2: note_engagement raises before bootstrap
    Given an unbootstrapped self
    When note_engagement is called
    Then SelfNotReady is raised

  @xfail
  Scenario: AC-71.2: note_interest_trigger raises before bootstrap
    Given an unbootstrapped self
    When note_interest_trigger is called
    Then SelfNotReady is raised

  @xfail
  Scenario: AC-71.2: Write tool succeeds after bootstrap
    Given a fully bootstrapped self
    When note_passion is called
    Then one passion is stored with text "music"

  @xfail
  Scenario: AC-71.3: recall_self raises before bootstrap
    Given an unbootstrapped self
    When recall_self is called
    Then SelfNotReady is raised

  @xfail
  Scenario: AC-71.3: render_minimal_block raises before bootstrap
    Given an unbootstrapped self
    When render_minimal_block is called
    Then SelfNotReady is raised

  @xfail
  Scenario: AC-71.4: Bootstrap completes without raising
    Given a self with bootstrap data
    When run_bootstrap completes
    Then facets count is 24 and answers count is 200 and mood exists

  @xfail
  Scenario: AC-71.4: Bootstrap repo inserts skip require_ready
    Given a fully bootstrapped self
    Then _bootstrap_complete returns True

  @xfail
  Scenario: AC-71.5: Cache hit returns same value
    Given a self with a facet and activation cache
    When the same node is queried twice
    Then the second call uses cached value with zero recomputes

  @xfail
  Scenario: AC-71.5: TTL expired recomputes
    Given a self with a facet and activation cache
    When the cache entry is older than 30 seconds
    Then a recompute occurs on access

  @xfail
  Scenario: AC-71.6: Insert contributor invalidates target cache
    Given a self with a facet and passion and cache entry
    When a contributor is inserted targeting the facet
    And the cache is invalidated for the target
    Then the next access recomputes

  @xfail
  Scenario: AC-71.6: Mark retracted invalidates target cache
    Given a self with a facet and passion and contributor and cache entry
    When the contributor is retracted
    And the cache is invalidated for the target
    Then the next access returns the base value

  @xfail
  Scenario: AC-71.7: Source mutation invalidates target caches
    Given a self with two facets sharing a contributor source
    When the source strength is updated
    And cache is invalidated for both targets
    Then both target activation values decrease

  @xfail
  Scenario: AC-71.8: Different ctx hash produces different entries
    Given a self with a facet and retrieval contributor
    When two contexts with different retrieval_similarity are used
    Then the context hashes differ and activation values differ

  @xfail
  Scenario: AC-71.9: LRU eviction at max entries
    Given an ActivationCache
    When more than 1024 entries are added
    Then cache size equals 1024 and the oldest entry is evicted

  @xfail
  Scenario: AC-71.10: update_facet_score mismatch raises CrossSelfAccess
    Given a self with a facet
    When update_facet_score is called with wrong acting_self_id
    Then CrossSelfAccess is raised

  @xfail
  Scenario: AC-71.10: update_passion mismatch raises CrossSelfAccess
    Given a self with a passion
    When update_passion is called with wrong acting_self_id
    Then CrossSelfAccess is raised

  @xfail
  Scenario: AC-71.10: update_hobby mismatch raises CrossSelfAccess
    Given a self with a hobby
    When update_hobby is called with wrong acting_self_id
    Then CrossSelfAccess is raised

  @xfail
  Scenario: AC-71.10: update_skill mismatch raises CrossSelfAccess
    Given a self with a skill
    When update_skill is called with wrong acting_self_id
    Then CrossSelfAccess is raised

  @xfail
  Scenario: AC-71.10: update_todo mismatch raises CrossSelfAccess
    Given a self with a todo
    When update_todo is called with wrong acting_self_id
    Then CrossSelfAccess is raised

  @xfail
  Scenario: AC-71.10: update_mood mismatch raises CrossSelfAccess
    Given a self with a mood
    When update_mood is called with wrong acting_self_id
    Then CrossSelfAccess is raised

  @xfail
  Scenario: AC-71.10: Matching acting_self_id succeeds
    Given a self with a facet
    When update_facet_score is called with matching acting_self_id
    Then the facet score is updated

  @xfail
  Scenario: AC-71.11: insert_contributor mismatch raises CrossSelfAccess
    Given an unbootstrapped self
    When insert_contributor is called with wrong acting_self_id
    Then CrossSelfAccess is raised

  @xfail
  Scenario: AC-71.11: insert_contributor matching succeeds
    Given an unbootstrapped self
    When insert_contributor is called with matching acting_self_id
    Then the contributor is stored

  @xfail
  Scenario: AC-71.12: insert_todo_revision mismatch raises CrossSelfAccess
    Given a self with a todo
    When insert_todo_revision is called with wrong acting_self_id
    Then CrossSelfAccess is raised

  @xfail
  Scenario: AC-71.12: insert_todo_revision matching succeeds
    Given a self with a todo
    When insert_todo_revision is called with matching acting_self_id
    Then the revision is stored

  @xfail
  Scenario: AC-71.13: Bootstrap inserts pass acting_self_id
    Given a fully bootstrapped self
    Then facets count is 24 and answers count is 200 and mood exists

  @xfail
  Scenario: AC-71.13: Bootstrap resume still works
    Given a self with a halted bootstrap at answer 50
    When bootstrap resumes
    Then answers count is 200

  @xfail
  Scenario: AC-71.14: Concurrent reads single compute
    Given a self with a facet and activation cache
    When two threads read the same key simultaneously
    Then both get the same value with at most 2 computes

  @xfail
  Scenario: AC-71.15: Fresh cache is empty
    Given a new ActivationCache instance
    Then cache size is 0

  @xfail
  Scenario: AC-71.15: Cache does not persist across instances
    Given a self with a filled cache
    When a second ActivationCache is created
    Then the second cache is empty and requires a recompute

  @xfail
  Scenario: AC-71.16: bootstrap_complete ignores cache
    Given a self and an empty ActivationCache
    When _bootstrap_complete is called
    Then the result is False and cache size remains 0

  @xfail
  Scenario: AC-71.16: bootstrap_complete consistent with repo counts
    Given a self progressively populated with facets then answers then mood
    Then _bootstrap_complete only returns True after all three are present
