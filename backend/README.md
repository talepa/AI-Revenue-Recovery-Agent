# Backend

FastAPI service for the AI Revenue Recovery Agent.

## Run via Docker (recommended)

```bash
cd ../infra
docker compose up --build
```

## Run locally

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
```

Then start just Postgres via Docker (`cd ../infra && docker compose up -d db`) — it's mapped to host port **5433**, not 5432, to avoid clashing with a locally-installed Postgres. `.env.example` already points at 5433.

```bash
alembic upgrade head      # apply migrations
uvicorn app.main:app --reload
```

## Database migrations (Alembic)

Models live in `app/models/`; `alembic/env.py` reads the DB URL from `app.core.config.settings` (not from `alembic.ini`), so it always matches whatever `.env`/environment is active.

```bash
alembic revision --autogenerate -m "describe the change"   # generate a migration after changing models
alembic upgrade head                                        # apply pending migrations
alembic downgrade -1                                         # roll back one migration
```

When running via Docker, migrations are applied automatically on container start (see `entrypoint.sh`) — no manual step needed.

## Test

```bash
pytest
```

## Endpoints

- `GET /health` — liveness, no dependencies
- `GET /health/db` — verifies the database connection with `SELECT 1`
