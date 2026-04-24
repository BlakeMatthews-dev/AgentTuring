Feature: Self-Write Budgets (Spec 73)
  Hard caps on how much self-model mutation a single request can produce.

  @xfail
  Scenario: AC-73.1: Default budget has correct caps
    Given a fresh RequestWriteBudget
    Then new_nodes is 3 and contributors is 5 and todo_writes is 2 and personality_claims is 3

  @xfail
  Scenario: AC-73.2: new() returns fresh instance with defaults
    Given the RequestWriteBudget class
    When new() is called
    Then all counters are at default values

  @xfail
  Scenario: AC-73.3: Budget set at pipeline start and cleared at end
    Given a request pipeline context
    When the pipeline starts and ends
    Then the budget is set during pipeline and cleared after

  @xfail
  Scenario: AC-73.4: use_budget context manager binds and unbinds
    Given a RequestWriteBudget
    When use_budget is entered and exited
    Then the budget var is set inside and None outside

  @xfail
  Scenario: AC-73.5: Counter decrement before write; zero raises
    Given a RequestWriteBudget with new_nodes at 0
    When note_passion attempts to consume new_nodes
    Then SelfWriteBudgetExceeded is raised with category "new_nodes"

  @xfail
  Scenario: AC-73.6: Failed write after decrement refunds counter
    Given a RequestWriteBudget with new_nodes at 1
    When a tool consumes new_nodes but then fails
    Then new_nodes is restored to 1

  @xfail
  Scenario: AC-73.7: Tool-to-category map is correct
    Given a fresh RequestWriteBudget
    When note_passion is called 4 times
    Then SelfWriteBudgetExceeded is raised on the 4th call

  @xfail
  Scenario: AC-73.7: Contributors category tracked
    Given a fresh RequestWriteBudget
    When write_contributor is called 6 times
    Then SelfWriteBudgetExceeded is raised on the 6th call

  @xfail
  Scenario: AC-73.7: Todo writes category tracked
    Given a fresh RequestWriteBudget
    When write_self_todo is called 3 times
    Then SelfWriteBudgetExceeded is raised on the 3rd call

  @xfail
  Scenario: AC-73.8: Non-budgeted tools bypass counter
    Given a fresh RequestWriteBudget
    When rerank_passions and practice_skill and note_engagement are called
    Then no budget counter is decremented

  @xfail
  Scenario: AC-73.9: Prometheus counter on exhaustion
    Given a RequestWriteBudget with new_nodes at 0
    When note_passion is attempted
    Then turing_self_write_budget_exceeded_total increments for "new_nodes"

  @xfail
  Scenario: AC-73.10: OBSERVATION mirror on exhaustion
    Given a RequestWriteBudget with new_nodes at 0
    When note_passion is attempted
    Then an OBSERVATION memory with intent "budget exceeded" is written

  @xfail
  Scenario: AC-73.11: Concurrent requests do not share budget
    Given two concurrent request pipelines
    When each consumes budget independently
    Then budgets are isolated per request

  @xfail
  Scenario: AC-73.12: Perception and observation share same budget
    Given a single request pipeline
    When perception step consumes 2 new_nodes
    Then observation step has only 1 new_nodes remaining

  @xfail
  Scenario: AC-73.13: Non-default config loads from turing.yaml
    Given a turing.yaml with custom budget caps
    When RequestWriteBudget is loaded
    Then the custom caps are used
