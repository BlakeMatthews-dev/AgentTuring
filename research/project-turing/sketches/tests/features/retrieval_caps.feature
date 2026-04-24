Feature: Retrieval Contributor Cap (Spec 74)
  Bounded per-target count and weight-sum for retrieval contributors.

  @xfail
  Scenario: AC-74.1: Materialize inserts at most K contributors per target
    Given a similarity map with 12 hits for one target
    When materialize_retrieval_contributors is called
    Then at most 8 contributors are inserted for the target

  @xfail
  Scenario: AC-74.2: Contributors inserted in descending similarity order
    Given a similarity map with varied similarities
    When materialize_retrieval_contributors is called
    Then contributors are ordered by descending similarity with lexical tie-break

  @xfail
  Scenario: AC-74.3: Sum cap stops insertion when exceeded
    Given a similarity map with high-weight hits summing over 1.0
    When materialize_retrieval_contributors is called
    Then insertion stops once running sum exceeds RETRIEVAL_SUM_CAP

  @xfail
  Scenario: AC-74.4: At least one contributor inserted even if weight exceeds cap
    Given a single hit with similarity 1.0
    When materialize_retrieval_contributors is called
    Then one contributor is inserted with weight RETRIEVAL_SUM_CAP

  @xfail
  Scenario: AC-74.5: Weight equals similarity times coefficient
    Given a similarity of 0.75
    When the weight is computed
    Then weight is 0.75 times RETRIEVAL_WEIGHT_COEFFICIENT

  @xfail
  Scenario: AC-74.6: Contributors have expires_at set
    Given a similarity map with hits
    When materialize_retrieval_contributors is called
    Then all contributors have expires_at equal to now plus RETRIEVAL_TTL

  @xfail
  Scenario: AC-74.7: Two requests materialize independently
    Given a target with retrieval contributors from request A
    When request B materializes for the same target
    Then request B creates its own contributors without duplicates

  @xfail
  Scenario: AC-74.8: Materialization uses same repo path as write_contributor
    Given a similarity map
    When materialize_retrieval_contributors is called
    Then contributors are inserted with origin=retrieval and expires_at set

  @xfail
  Scenario: AC-74.9: Count and sum caps both enforced
    Given 50 low-similarity hits each with weight 0.05
    When materialize_retrieval_contributors is called
    Then at most 8 contributors are inserted and sum <= 1.0

  @xfail
  Scenario: AC-74.10: High-similarity fixture stops at sum cap
    Given 3 hits each with similarity 1.0
    When materialize_retrieval_contributors is called
    Then at most 2 are inserted (sum 0.8 + third exceeds cap)

  @xfail
  Scenario: AC-74.11: Prometheus gauge reports active retrieval contributors
    Given a self with retrieval contributors materialized
    Then turing_retrieval_contributors_active reports the count

  @xfail
  Scenario: AC-74.12: Drop counter increments on cap hit
    Given 12 hits for one target
    When materialize_retrieval_contributors is called
    Then turing_retrieval_contributors_dropped_total increments with reason count_cap

  @xfail
  Scenario: AC-74.13: Zero hits means no rows inserted
    Given a similarity map with zero hits
    When materialize_retrieval_contributors is called
    Then no contributors are inserted and active_now uses durable only

  @xfail
  Scenario: AC-74.14: Similarity above 1.0 clamps to 1.0
    Given a similarity of 1.5
    When the weight is computed
    Then similarity is clamped to 1.0 before multiplication

  @xfail
  Scenario: AC-74.15: Idempotent within same request
    Given a similarity map
    When materialize_retrieval_contributors is called twice
    Then the second call inserts no duplicates
