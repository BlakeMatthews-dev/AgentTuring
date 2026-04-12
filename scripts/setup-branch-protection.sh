#!/usr/bin/env bash
# Set up branch protection rules for the Stronghold repo.
#
# Requires: GitHub Pro ($4/month for private repos) OR a public repo.
# Run this once after upgrading:
#   bash scripts/setup-branch-protection.sh
#
# What it does:
#   - integration: require CI + Cleanroom Lint to pass, no force pushes
#   - develop: require CI + Security + SAST, no force pushes, no direct commits
#   - main: require ALL checks + 1 review approval, no force pushes

set -euo pipefail

REPO="Agent-StrongHold/stronghold"

echo "=== Setting up branch protection for $REPO ==="

# integration: require CI lint + cleanroom to pass
echo "Configuring integration..."
gh api -X PUT "repos/$REPO/branches/integration/protection" \
  --input - <<'JSON'
{
  "required_status_checks": {
    "strict": true,
    "contexts": [
      "Lint & Type Check",
      "Cleanroom string lint"
    ]
  },
  "enforce_admins": false,
  "required_pull_request_reviews": null,
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}
JSON
echo "  ✓ integration protected (CI + Cleanroom required)"

# develop: require CI + security + SAST, no direct commits
echo "Configuring develop..."
gh api -X PUT "repos/$REPO/branches/develop/protection" \
  --input - <<'JSON'
{
  "required_status_checks": {
    "strict": true,
    "contexts": [
      "Lint & Type Check",
      "Security Tests",
      "SAST & Supply Chain",
      "Tests",
      "Cleanroom string lint"
    ]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "required_approving_review_count": 1,
    "dismiss_stale_reviews": true
  },
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}
JSON
echo "  ✓ develop protected (all CI + 1 review required)"

# main: require everything + approval
echo "Configuring main..."
gh api -X PUT "repos/$REPO/branches/main/protection" \
  --input - <<'JSON'
{
  "required_status_checks": {
    "strict": true,
    "contexts": [
      "Lint & Type Check",
      "Security Tests",
      "SAST & Supply Chain",
      "Tests",
      "Cleanroom string lint",
      "Full Repo Quality Check"
    ]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "required_approving_review_count": 1,
    "dismiss_stale_reviews": true,
    "require_code_owner_reviews": true
  },
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}
JSON
echo "  ✓ main protected (all CI + drift check + review + CODEOWNERS)"

echo ""
echo "=== Branch protection configured ==="
echo ""
echo "  integration: CI lint + cleanroom must pass to merge"
echo "  develop:     all CI jobs + 1 review to merge"
echo "  main:        all CI jobs + drift check + 1 code-owner review"
echo ""
echo "To verify: gh api repos/$REPO/branches/integration/protection --jq '.required_status_checks.contexts'"
