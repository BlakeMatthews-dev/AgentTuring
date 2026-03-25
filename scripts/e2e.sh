#!/usr/bin/env bash
# Run E2E tests against the live Docker stack.
# Usage: ./scripts/e2e.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> Starting Docker stack..."
docker compose up -d --build --wait 2>&1 | tail -5

echo "==> Waiting for health check..."
for i in $(seq 1 30); do
    if curl -sf http://localhost:8100/health > /dev/null 2>&1; then
        echo "    Stronghold is healthy."
        break
    fi
    echo "    Waiting... ($i/30)"
    sleep 2
done

echo "==> Health status:"
curl -s http://localhost:8100/health | python3 -m json.tool

echo ""
echo "==> Running E2E tests..."
python3 -m pytest tests/e2e/ -v --tb=short
result=$?

echo ""
echo "==> Cleaning up..."
# Don't tear down by default — useful for debugging
# docker compose down

exit $result
