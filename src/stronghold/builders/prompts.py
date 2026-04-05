"""Default prompt templates for the Builders pipeline.

These are seeded into the PromptManager on first run. After that, they can be
edited via the API without redeploying:

    PUT /v1/stronghold/prompts/builders.mason.write_tests
    GET /v1/stronghold/prompts/builders.mason.write_tests/versions
    GET /v1/stronghold/prompts/builders.mason.write_tests/diff?v1=1&v2=2
    POST /v1/stronghold/prompts/builders.mason.write_tests/promote

Variables use {{name}} (double-brace) to avoid conflict with Python f-strings.
The pipeline replaces these at runtime via str.replace().
"""

from __future__ import annotations

# ── Frank prompts ────────────────────────────────────────────────────

ANALYZE_ISSUE = """\
Analyze this GitHub issue for implementation planning.

Issue #{{issue_number}}: {{issue_title}}

{{issue_content}}

Repository source structure:
{{file_listing}}

Dashboard files:
{{dashboard_listing}}

Test structure:
{{test_listing}}

Architecture context:
{{architecture_excerpt}}

{{feedback_block}}

Output ONLY a JSON object with these exact fields:
{"problem": "...", "requirements": ["..."], "edge_cases": ["..."], "affected_files": ["..."], "approach": "..."}
"""

ACCEPTANCE_CRITERIA = """\
Write Gherkin acceptance criteria for this issue.

Issue #{{issue_number}}: {{issue_title}}

Requirements:
{{requirements}}

Edge cases:
{{edge_cases}}

{{feedback_block}}

Rules:
- Each scenario MUST have Given, When, and Then steps
- Cover happy path, error scenarios, and edge cases
- Minimum 3 scenarios

Output ONLY Gherkin scenarios. No commentary.
Start directly with 'Scenario:'
"""

# ── Mason prompts ────────────────────────────────────────────────────

WRITE_FIRST_TEST = """\
Write a complete pytest test file with ONE test function for this criterion:

{{criterion}}

Target source code:
{{source_context}}

{{feedback_block}}

CRITICAL RULES:
- Include imports, fixture, and ONE test class with ONE test function
- Follow the test pattern from the Codebase Context above EXACTLY
- The test SHOULD FAIL initially (TDD — implementation not written yet)
- Match the test approach to the file type:
  - For .html files: read the file with pathlib and assert on HTML structure/content
  - For .py route files: mount the router with app.include_router(router), use TestClient
  - For .py utility files: import and instantiate the class directly
- NEVER use API route patterns (TestClient, include_router) for HTML/CSS issues

Output ONLY Python pytest code. No explanation.
"""

APPEND_TEST = """\
Add ONE new test function to this existing test file for a new criterion.

New criterion to test:
{{criterion}}

Existing test file:
```python
{{existing_code}}
```

{{feedback_block}}

CRITICAL RULES:
- Return the COMPLETE file with the new test function APPENDED at the end
- Do NOT modify or remove any existing test functions
- Do NOT duplicate imports or the fixture — they already exist
- Add only the new test function (def test_... or class Test...)
- Match the test approach used in the existing file (HTML structural vs route vs utility)

Output ONLY the complete Python file with the new test appended. No explanation.
"""

WRITE_TESTS = """\
Write a SINGLE pytest test file that validates ALL of these acceptance criteria:

{{criterion}}

Target source code:
{{source_context}}

{{feedback_block}}

CRITICAL RULES:
- ONE file with ONE set of imports, ONE fixture, MULTIPLE test classes/functions
- Follow the test pattern from the Codebase Context above EXACTLY
- Do NOT duplicate imports or fixtures — one set at the top of the file
- Match the test approach to the file type:
  - For .html files: read the file with pathlib and assert on HTML structure/content
  - For .py route files: mount the router with app.include_router(router), use TestClient
  - For .py utility files: import and instantiate the class directly
- NEVER use API route patterns (TestClient, include_router) for HTML/CSS issues

Output ONLY Python pytest code. No explanation.
Start with import statements. One file, all criteria.
"""

FIX_SYNTAX = """\
This pytest test file has errors:

```python
{{test_code}}
```

Error output:
```
{{error_output}}
```

Fix the code. Output ONLY the corrected Python code.
"""

IMPLEMENT = """\
These tests are failing:

```python
{{test_code}}
```

Test output:
```
{{pytest_output}}
```

Current source file `{{file_path}}`:
```python
{{source_code}}
```

Issue description:
{{issue_content}}

{{feedback_block}}

Write the MINIMUM code change to make the tests pass.
Output ONLY the complete updated source file. No explanation.
Do NOT remove existing functionality — only ADD the new code.
"""

FIND_AFFECTED_FILE = """\
Which source file should be modified to implement this issue?

Issue: {{issue_content}}

Available route files:
{{file_listing}}

Dashboard files:
{{dashboard_listing}}

Determine the correct file based on the issue type:
- UI/dashboard issues → look in src/stronghold/dashboard/*.html
- API route issues → look in src/stronghold/api/routes/*.py
- Utility/library issues → look in src/stronghold/ subdirectories

Output ONLY the file path, e.g.: src/stronghold/dashboard/index.html
"""

FIX_VIOLATIONS = """\
Fix the {{gate_name}} violations in this file:

Violations:
```
{{violations}}
```

Source file `{{file_path}}`:
```python
{{source_code}}
```

Output ONLY the corrected complete file.
"""

# ── Auditor prompts ──────────────────────────────────────────────────

AUDITOR_REVIEW = """\
You are the Auditor in the Stronghold Builders pipeline.

## The Builders Process
Builders solves GitHub issues through 6 stages:
1. issue_analyzed — Architect analyzes the problem
2. acceptance_defined — Architect writes Gherkin criteria
3. tests_written — Builder writes pytest tests (TDD)
4. implementation_started — Builder writes code to pass tests
5. implementation_ready — Runtime runs quality gates
6. quality_checks_passed — Final verification

You gate each transition. Catch REAL problems, not hypothetical ones.

## Current Stage: `{{stage}}`
**Purpose:** {{purpose}}
**In scope:** {{scope}}
**OUT OF SCOPE (do NOT critique):** {{out_of_scope}}

## Approval Checklist
{{checklist}}

## Evidence (gathered by runtime — not self-reported)
{{evidence}}

## Your Verdict
Check EACH checklist item against the evidence.
- If ALL items pass: APPROVED: <which items passed>
- If ANY item fails: CHANGES_REQUESTED then:
  FAILED ITEM: <which checklist item>
  EVIDENCE: <quote from evidence showing the failure>
  FIX: <exactly what should change>

Rules:
- Do NOT reject for items that are out of scope for this stage.
- Do NOT invent requirements not in the checklist.
- Do NOT request implementation details at analysis stages.
- {{rejection_format}}
"""

# ── Stage-specific auditor context ───────────────────────────────────

AUDITOR_STAGE_ISSUE_ANALYZED = """\
purpose: Understand the problem and plan the approach
scope: Problem statement, requirements list, edge cases, affected files, approach
out_of_scope: Implementation details, code, fallback values, error handling specifics — those belong in later stages
checklist:
- Problem statement is clear and matches the issue
- Requirements are listed and non-empty
- At least one edge case identified
- Affected files are plausible paths in the repo
rejection_format: State WHICH checklist item failed, QUOTE the problematic text, and say WHAT it should say instead
"""

AUDITOR_STAGE_ACCEPTANCE_DEFINED = """\
purpose: Define testable success criteria in Gherkin format
scope: Gherkin scenarios with Given/When/Then covering happy path, errors, edge cases
out_of_scope: Implementation approach, code, file paths — those belong in tests_written
checklist:
- At least 3 Gherkin scenarios present
- Each scenario has Given, When, and Then steps
- Happy path is covered
- At least one error or edge case scenario
- Scenarios are concrete and testable (not vague)
rejection_format: State WHICH scenario is wrong or missing, and provide the corrected Gherkin text
"""

AUDITOR_STAGE_TESTS_WRITTEN = """\
purpose: Create pytest test files that validate the acceptance criteria
scope: Test file exists, compiles without errors, tests map to criteria
out_of_scope: Whether tests PASS — they SHOULD fail at this stage (TDD). Implementation code has not been written yet. AssertionError and 404 responses are EXPECTED and CORRECT — the endpoint being tested does not exist yet. Only SyntaxError and ImportError indicate real problems.
checklist:
- Test file was created (evidence shows file path)
- Pytest ran without SyntaxError or ImportError (AssertionError is OK — that is TDD)
- At least one test function exists (test count > 0)
rejection_format: State WHICH error needs fixing with the EXACT error message. Do NOT reject for AssertionError or 404 — those are expected in TDD.
"""

AUDITOR_STAGE_IMPLEMENTATION_STARTED = """\
purpose: Write code that makes the failing tests pass
scope: Source files modified, test results improved
out_of_scope: Code style, naming — those are checked in quality gates stage
checklist:
- At least one source file was modified (evidence shows file list)
- Test pass count improved vs before implementation
- Changes are committed to git
rejection_format: State WHICH test still fails and WHY, quoting the error output
"""

AUDITOR_STAGE_IMPLEMENTATION_READY = """\
purpose: Run quality gates and fix violations in new code
scope: All gates ran, new-code violations addressed
out_of_scope: Pre-existing violations in files NOT touched by this issue
checklist:
- All 5 quality gates ran (pytest, ruff_check, ruff_format, mypy, bandit)
- No NEW violations introduced by this issue's changes
rejection_format: State WHICH gate failed with the EXACT violation text, and whether it is new or pre-existing
"""

AUDITOR_STAGE_QUALITY_CHECKS_PASSED = """\
purpose: Final verification — confirm commits and tests exist
scope: Git log, diff stat, final pytest run
out_of_scope: >
  Re-reviewing implementation decisions from earlier stages.
  Test pass/fail counts — the TDD stage already verified tests.
  Do NOT reject because some tests fail.
checklist:
- Git log shows at least one commit for this issue
- Diff shows changes to source and/or test files
- Pytest output is present (pytest was invoked, not empty)
rejection_format: State WHICH check failed, quoting the evidence
"""

# ── Registry ─────────────────────────────────────────────────────────

BUILDER_PROMPT_DEFAULTS: dict[str, str] = {
    # Frank
    "builders.frank.analyze_issue": ANALYZE_ISSUE,
    "builders.frank.acceptance_criteria": ACCEPTANCE_CRITERIA,
    # Mason
    "builders.mason.write_first_test": WRITE_FIRST_TEST,
    "builders.mason.append_test": APPEND_TEST,
    "builders.mason.write_tests": WRITE_TESTS,
    "builders.mason.fix_syntax": FIX_SYNTAX,
    "builders.mason.implement": IMPLEMENT,
    "builders.mason.find_affected_file": FIND_AFFECTED_FILE,
    "builders.mason.fix_violations": FIX_VIOLATIONS,
    # Auditor
    "builders.auditor.review": AUDITOR_REVIEW,
    "builders.auditor.stage.issue_analyzed": AUDITOR_STAGE_ISSUE_ANALYZED,
    "builders.auditor.stage.acceptance_defined": AUDITOR_STAGE_ACCEPTANCE_DEFINED,
    "builders.auditor.stage.tests_written": AUDITOR_STAGE_TESTS_WRITTEN,
    "builders.auditor.stage.implementation_started": AUDITOR_STAGE_IMPLEMENTATION_STARTED,
    "builders.auditor.stage.implementation_ready": AUDITOR_STAGE_IMPLEMENTATION_READY,
    "builders.auditor.stage.quality_checks_passed": AUDITOR_STAGE_QUALITY_CHECKS_PASSED,
}
