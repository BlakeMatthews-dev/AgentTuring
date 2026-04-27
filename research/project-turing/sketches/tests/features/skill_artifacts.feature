Feature: Versioned Skill Artifacts with Judging and Coaching (Skill Spec)

  Skills are real agent capabilities. Practice produces artifacts that are
  versioned, scored, and judged. Level tracks best-ever score, not a counter.
  Regression triggers actionable coaching that feeds into the next attempt.

  Scenario: SKILL-1: Seeded skill has name from agent registry
    Given a fresh self with no skills
    When a "Code Reading" skill is seeded
    Then the skill name is "Code Reading"
    And the skill kind is "coding"
    And stored_level is 0.1

  Scenario: SKILL-2: First artifact sets the level
    Given a seeded "Code Reading" skill
    When practice produces an artifact scored 0.4
    Then stored_level becomes 0.4
    And best_version is 1
    And active_coaching is None

  Scenario: SKILL-3: New best raises level
    Given a skill with best artifact at version 1 scored 0.4
    When practice produces an artifact scored 0.55
    Then stored_level becomes 0.55
    And best_version is 2
    And active_coaching is None

  Scenario: SKILL-4: Regression keeps best level, activates coaching
    Given a skill with best artifact at version 2 scored 0.55
    When practice produces an artifact scored 0.3
    Then stored_level stays at 0.55
    And best_version stays at 2
    And active_coaching contains actionable feedback

  Scenario: SKILL-5: Coaching from regression feeds into next practice
    Given a skill with active coaching "Try being more specific about the function's purpose"
    When the next practice prompt is built
    Then the prompt includes the coaching text

  Scenario: SKILL-6: New best after regression clears coaching
    Given a skill with active coaching from a regression
    When practice produces a new best artifact scored 0.6
    Then stored_level becomes 0.6
    And active_coaching is None

  Scenario: SKILL-7: No decay — level never decreases over time
    Given a skill at level 0.7 last practiced 30 days ago
    When current_level is computed
    Then it returns 0.7

  Scenario: SKILL-8: Fail outcome produces zero delta
    Given a skill at level 0.5
    When practice fails with score 0.1 (below best)
    Then stored_level stays at 0.5 (best ever)

  Scenario: SKILL-9: Judge scores are clamped to [0.0, 1.0]
    Given a skill with no prior artifacts
    When the judge returns a score of 1.5
    Then the stored score is clamped to 1.0

  Scenario: SKILL-10: Artifact history is queryable
    Given a skill with 3 artifacts at versions 1, 2, 3
    When list_skill_artifacts is called with limit 2
    Then 2 artifacts are returned ordered by version descending

  Scenario: SKILL-11: get_best_artifact returns highest score
    Given a skill with artifacts scored 0.3, 0.7, 0.5
    When get_best_artifact is called
    Then it returns the artifact scored 0.7

  Scenario: SKILL-12: Duplicate skill name is rejected
    Given a seeded "Code Reading" skill
    When another "Code Reading" skill is seeded
    Then no duplicate is created
    And total skill count is 1

  Scenario: SKILL-13: Seeding skips already-seeded skills
    Given 10 skills already seeded
    When SkillBuilder.on_tick fires
    Then no new backlog item is inserted

  Scenario: SKILL-14: Skills are only seeded from AGENT_SKILL_SEEDS
    Given a fresh self with no skills
    When all skills are seeded
    Then each skill name exists in AGENT_SKILL_SEEDS
    And total skill count equals len(AGENT_SKILL_SEEDS)
