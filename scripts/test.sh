#!/usr/bin/env bash
# Stronghold test runner — tiered execution.
#
# Usage:
#   ./scripts/test.sh              # critical tier (every change)
#   ./scripts/test.sh happy        # happy-path tier (feature branch)
#   ./scripts/test.sh full         # full suite (pre-commit)
#   ./scripts/test.sh coverage     # full suite + coverage report
#
# Tiers:
#   critical  ~288 tests   <1s    Auth, security, routing, pipeline, types
#   happy     ~876 tests   ~3s    One golden-path per feature module
#   full      ~1729 tests  ~50s   Everything including edge cases
#
set -euo pipefail
cd "$(dirname "$0")/.."

TIER="${1:-critical}"
shift 2>/dev/null || true

case "$TIER" in
  critical|smoke|fast)
    echo "=== Critical Regression (~288 tests) ==="
    python3 -m pytest -m critical -q "$@"
    ;;
  happy|feature|features)
    echo "=== Happy Path (~876 tests) ==="
    python3 -m pytest -m happy -q "$@"
    ;;
  full|all|precommit|pre-commit)
    echo "=== Full Suite (~1729 tests) ==="
    python3 -m pytest -q "$@"
    ;;
  coverage|cov)
    echo "=== Full Suite + Coverage ==="
    python3 -m coverage run --source=src/stronghold -m pytest -q "$@"
    python3 -m coverage report --sort=cover --skip-covered
    echo ""
    python3 -m coverage report | grep "^TOTAL"
    ;;
  *)
    echo "Unknown tier: $TIER"
    echo "Usage: $0 [critical|happy|full|coverage]"
    exit 1
    ;;
esac
