#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON="${ROOT_DIR}/.venv/bin/python"
if [ ! -f "$PYTHON" ]; then
    echo "Error: Python environment not found at $PYTHON. Run ./scripts/bootstrap-local.sh first."
    exit 1
fi

TEST_PATH="${1:-backend/tests}"
TEST_DB="${TEST_PGDATABASE:-test_nivasops}"

echo "Running pytest against test database: $TEST_DB"
TEST_PGDATABASE="$TEST_DB" "$PYTHON" -m pytest "$TEST_PATH" "${@:2}" -q
