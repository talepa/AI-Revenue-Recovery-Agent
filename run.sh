#!/usr/bin/env bash
# One-command local dev runner: starts Postgres (Docker), sets up the
# backend venv, applies migrations, and launches the API with auto-reload.
#
# Usage: ./run.sh

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

if ! docker info >/dev/null 2>&1; then
    echo "Docker doesn't seem to be running. Start Docker Desktop and try again."
    exit 1
fi

echo "==> Starting Postgres (Docker)..."
(cd infra && docker compose up -d db)

DB_CONTAINER=$(cd infra && docker compose ps -q db)
echo "==> Waiting for Postgres to be healthy..."
for i in $(seq 1 30); do
    STATUS=$(docker inspect --format='{{.State.Health.Status}}' "$DB_CONTAINER" 2>/dev/null || echo "")
    if [ "$STATUS" = "healthy" ]; then
        break
    fi
    sleep 1
done
if [ "$STATUS" != "healthy" ]; then
    echo "Postgres did not become healthy in time. Check 'docker compose -f infra/docker-compose.yml logs db'."
    exit 1
fi

cd "$REPO_ROOT/backend"

if [ ! -d .venv ]; then
    echo "==> Creating virtualenv..."
    python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

echo "==> Installing dependencies..."
pip install -q -r requirements-dev.txt

if [ ! -f .env ]; then
    echo "==> Creating backend/.env from .env.example..."
    cp .env.example .env
fi

echo "==> Applying database migrations..."
alembic upgrade head

echo "==> Starting API with auto-reload at http://localhost:8000 (Ctrl+C to stop)"
echo "    Postgres stays running in Docker — 'cd infra && docker compose down' to stop it."
exec uvicorn app.main:app --reload --port 8000
