#!/usr/bin/env bash
# Run IRA integration tests in Docker (LEGACY — requires the retired base
# docker-compose.yml; the stack now runs native, see start-ira.ps1).
# For the supported test path use:  cd ira && python -m pytest tests/
# Usage: bash scripts/test.sh [pytest-args]
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [ ! -f docker-compose.yml ]; then
    echo "❌ docker-compose.yml not found — the Docker test path was retired when the"
    echo "   stack moved native (see Makefile 'up' target and start-ira.ps1)."
    echo "   Run the suite directly instead:  cd ira && python -m pytest tests/"
    exit 1
fi

echo "=== IRA Integration Test Runner ==="
echo ""

# Build test image
echo "Building test image..."
docker compose -f docker-compose.yml -f docker-compose.test.yml build ira-api

# Start test dependencies
echo "Starting test postgres + redis..."
docker compose -f docker-compose.yml -f docker-compose.test.yml --profile test up -d postgres redis

# Wait for postgres
echo "Waiting for postgres..."
timeout 30 bash -c 'until docker compose exec postgres pg_isready -U "${POSTGRES_USER:-jarvis}" -d ira_test 2>/dev/null; do sleep 1; done'

# Run tests
echo ""
echo "Running tests..."
docker compose -f docker-compose.yml -f docker-compose.test.yml run --rm \
    -e PYTEST_ARGS="${*:-tests/ -v}" \
    ira-api \
    sh -c "python -m pytest \$PYTEST_ARGS"

EXIT_CODE=$?

# Cleanup
echo ""
echo "Cleaning up..."
docker compose -f docker-compose.yml -f docker-compose.test.yml --profile test down -v

if [ $EXIT_CODE -eq 0 ]; then
    echo "✅ All tests passed"
else
    echo "❌ Tests failed (exit code: $EXIT_CODE)"
fi

exit $EXIT_CODE
