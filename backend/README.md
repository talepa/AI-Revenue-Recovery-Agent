# Backend

FastAPI service for the AI Revenue Recovery Agent.

## Quickest way to run it

From the repo root: `./run.sh` — starts Postgres in Docker, sets up the venv, migrates, and launches the API with auto-reload. See the root [README](../README.md#getting-started).

## Run via Docker only (no local Python, no auto-reload)

```bash
cd ../infra
docker compose up --build
```

## Run locally, manually

Same as `run.sh` but step by step, if you want control over each part:

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

## Seed demo data

Populates a realistic dataset covering all five recovery scenarios from the project brief (low-risk, repeat-late-payer medium-risk, high-risk escalated, promise-to-pay, and recovered-after-reminder) plus one fully healthy account. Safe to re-run — it clears prior seed data first, and all dates are relative to "today" so the scenarios (e.g. "5 days overdue") stay accurate no matter when you run it.

```bash
python -m app.seed.run
```

Via Docker: `docker compose exec api python -m app.seed.run`.

This is demo/dev data for the running app, not the (larger, purely synthetic) training set the Phase 6 ML model will use.

## Test

```bash
pytest
```

Note: `tests/test_seed.py` is an integration test that runs the real seed script against the database — it needs `DATABASE_URL` pointing at a live Postgres (e.g. `docker compose up -d db`).

## Endpoints

- `GET /health` — liveness, no dependencies
- `GET /health/db` — verifies the database connection with `SELECT 1`
- `GET /companies` / `GET /companies/{id}` — company list / detail with contacts
- `GET /invoices` (filter by `status`, `company_id`; paginated) / `GET /invoices/overdue` / `GET /invoices/{id}`
- `GET /recovery-cases` — dashboard-table shape: company, invoice, amount, days overdue, risk, status, current action, recovered amount
- `GET /recovery-cases/{id}` — full case detail: invoice, actions (with the policy decision behind each), agent diagnoses/recommendations, promise-to-pay, communications, audit trail
- `GET /recovery-cases/{id}/audit-trail` — just the ordered audit log for a case
- `POST /recovery-cases/detect-overdue` — deterministic engine trigger: flips newly-overdue invoices to `OVERDUE` and opens a recovery case for each (idempotent, manually/cron-triggered — no long-running consumer in V1)
- `GET /dashboard/metrics` — total revenue at risk, total recovered, recovery rate, active/escalated case counts, average days overdue, breakdown by risk level

Interactive docs at `/docs` once the server is running.

## ML risk model

`app/ml/` holds the recovery-risk XGBoost model. It's trained on **synthetic data only** — see [synthetic_data.py](app/ml/synthetic_data.py) for the documented generative process. Not a production financial model.

```bash
python -m app.ml.train   # regenerates synthetic data, retrains, overwrites app/ml/artifacts/
```

The trained model (`app/ml/artifacts/recovery_risk_model.json`) and its metrics (`metrics.json`, currently AUC ~0.78) are committed to the repo, so the app runs out of the box without retraining. Real feature extraction (from actual payment history in Postgres — separate from the synthetic training generator) lives in `app/services/risk_context.py`; `POST /recovery-cases/detect-overdue` scores every case it creates automatically.
