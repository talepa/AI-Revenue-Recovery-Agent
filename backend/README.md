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
cp .env.example .env   # then start a local Postgres, or point DATABASE_URL at one
uvicorn app.main:app --reload
```

## Test

```bash
pytest
```

## Endpoints (Phase 1)

- `GET /health` — liveness, no dependencies
- `GET /health/db` — verifies the database connection with `SELECT 1`
