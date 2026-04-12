#!/usr/bin/env bash
# Cleanroom lint: scan diff against base branch for forbidden strings.
#
# Stronghold's docs, ADRs, code, and CI configs must not name specific
# upstream research archives, customer code names, competitor product
# names, or other identifiers that would expose internal-only context.
# This lint blocks new introductions.
#
# Usage:
#   scripts/cleanroom-lint.sh                  # diff against origin/integration
#   scripts/cleanroom-lint.sh main             # diff against origin/main
#   scripts/cleanroom-lint.sh --all-tracked    # scan every tracked file (slower)
#
# Exits 0 on clean, 1 on any match.

set -euo pipefail

# Forbidden patterns (case-insensitive, ERE).
# Keep this list in sync with the clean-room rules in
# the v0.9 plan and CONTRIBUTING.md.
FORBIDDEN_PATTERNS=(
  'jedai'
  'jedi'
  'disney'
  'wdpr'
  'stronghold-eval-topics'
  'archestra'
  'semantic-router'
  'vllm-disagg'
  'iris-guard'
  'jedai-docker'
)

JOINED=$(IFS='|'; echo "${FORBIDDEN_PATTERNS[*]}")
PATTERN="($JOINED)"

mode="diff"
base="${1:-origin/integration}"
if [[ "${1:-}" == "--all-tracked" ]]; then
  mode="all"
fi

red()    { printf '\033[31m%s\033[0m\n' "$*"; }
green()  { printf '\033[32m%s\033[0m\n' "$*"; }
yellow() { printf '\033[33m%s\033[0m\n' "$*"; }

echo "cleanroom-lint: pattern = ${PATTERN}"

if [[ "$mode" == "all" ]]; then
  echo "cleanroom-lint: mode = scan all tracked files"
  matches=$(git ls-files -z \
    | xargs -0 grep -inEH "$PATTERN" 2>/dev/null \
    | grep -v '^\.claude/worktrees/' \
    | grep -v '^scripts/cleanroom-lint\.sh:' \
    || true)
else
  echo "cleanroom-lint: mode = diff vs ${base}"
  if ! git rev-parse --verify "$base" >/dev/null 2>&1; then
    yellow "cleanroom-lint: base ref '${base}' not found, falling back to --all-tracked"
    mode="all"
    matches=$(git ls-files -z \
      | xargs -0 grep -inEH "$PATTERN" 2>/dev/null \
      | grep -v '^\.claude/worktrees/' \
      | grep -v '^scripts/cleanroom-lint\.sh:' \
      || true)
  else
    # Get the list of files changed (added or modified) vs base.
    changed_files=$(git diff --name-only --diff-filter=AM "${base}...HEAD" || true)
    if [[ -z "$changed_files" ]]; then
      green "cleanroom-lint: no changed files vs ${base}, nothing to scan"
      exit 0
    fi
    # Exclude this script — it contains the pattern list by definition.
    changed_files=$(echo "$changed_files" | grep -v 'scripts/cleanroom-lint\.sh')
    if [[ -z "$changed_files" ]]; then
      green "cleanroom-lint: only cleanroom-lint.sh changed, nothing else to scan"
      exit 0
    fi
    # Only inspect lines added in this branch (the '+' diff lines).
    matches=$(git diff "${base}...HEAD" -- $changed_files \
      | grep -inE "^\+[^+].*${PATTERN}" \
      || true)
  fi
fi

if [[ -z "$matches" ]]; then
  green "cleanroom-lint: clean ✓"
  exit 0
fi

red "cleanroom-lint: forbidden strings detected"
echo
echo "$matches"
echo
red "Failing. Update the diff to remove the forbidden strings, or update"
red "FORBIDDEN_PATTERNS in scripts/cleanroom-lint.sh if the entry is no"
red "longer sensitive (rare — discuss in PR review first)."
exit 1
