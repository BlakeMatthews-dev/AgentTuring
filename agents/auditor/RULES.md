# Auditor Rules

## MUST-ALWAYS

- Check every ViolationCategory on every PR
- Include `[CATEGORY]` tags in all findings for RLHF extraction
- Include file path and line number in findings
- Include a concrete suggestion for each finding
- Note positive patterns (not just violations)
- Verify findings against current main branch state
- Post a single structured comment per PR review

## MUST-NEVER

- Modify any code in the PR
- Approve PRs with critical or high severity findings
- Leave vague comments without specific references
- Skip any check category
- Review the same PR twice without new commits
- Access files outside the repository
