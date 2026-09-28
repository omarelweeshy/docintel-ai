#!/usr/bin/env bash
# Run from a Linux checkout against an explicitly selected disposable database.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${TEST_DATABASE_URL:?Set TEST_DATABASE_URL to a disposable PostgreSQL/pgvector database}"
export DATABASE_URL="$TEST_DATABASE_URL"
test_venv="${DOCINTEL_TEST_VENV:-${XDG_CACHE_HOME:-$HOME/.cache}/docintel-test-venv}"
python3.12 -m venv "$test_venv"
"$test_venv/bin/pip" install -q -r apps/api/requirements-dev.lock
"$test_venv/bin/pip" install -q --no-deps -e apps/api
cd apps/api
"$test_venv/bin/alembic" upgrade head
"$test_venv/bin/alembic" check
"$test_venv/bin/ruff" check .
"$test_venv/bin/ruff" format --check .
"$test_venv/bin/mypy" app
"$test_venv/bin/pytest" -q -o cache_dir="$test_venv/pytest-cache"
