#!/usr/bin/env bash
# Run from a Linux checkout against an explicitly selected disposable database. Requires uv.
set -euo pipefail
cd "$(dirname "$0")/../apps/api"
: "${TEST_DATABASE_URL:?Set TEST_DATABASE_URL to a disposable PostgreSQL/pgvector database}"
export DATABASE_URL="$TEST_DATABASE_URL"
uv sync --frozen
uv run alembic upgrade head
uv run alembic check
uv run ruff check .
uv run ruff format --check .
uv run mypy app
uv run pytest -q
