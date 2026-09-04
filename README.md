# AI Revenue Recovery Agent

An AI-assisted system that detects at-risk B2B revenue (overdue invoices), decides how to recover it, and executes that decision inside deterministic financial guardrails — instead of relying on fixed retry rules or manual finance follow-ups.

> **Status: under active development, built phase-by-phase.** This README tracks what's actually implemented (see [Build status](#build-status)), not the end-state vision. It is a **portfolio project on seeded, synthetic data** — no real payments, customers, or financial infrastructure are involved.

## The problem

Businesses lose revenue when B2B invoices go overdue. Most companies handle this with either rigid rule-based reminders or manual finance-team chasing — neither of which scales well or reasons about context (this customer usually pays on time vs. this one has a pattern of late payment, this amount needs escalation vs. this one doesn't).

This project builds a controlled, auditable agentic workflow that:

1. Detects overdue invoices and quantifies revenue at risk.
2. Scores recovery probability with a trained ML model (XGBoost, synthetic data).
3. Uses an LLM to diagnose the likely cause and recommend a next action.
4. Runs that recommendation through a **deterministic policy engine** before anything happens.
5. Executes the approved action through a mock tool (email, payment link, escalation).
6. Tracks the outcome — payment, promise-to-pay, or escalation — and loops or stops.
7. Records every decision in an audit trail and surfaces recovered revenue on a dashboard.

## Design principle

The core engineering decision in this project is keeping these four responsibilities strictly separate:

| Layer | Responsibility | Can it touch money or send anything? |
|---|---|---|
| **LLM** | Diagnose the situation, recommend one action from a fixed set | No |
| **ML (XGBoost)** | Score recovery probability / risk level | No |
| **Deterministic policy engine** | Approve, reject, or force-escalate the recommended action against hard business rules (reminder caps, cooldowns, value thresholds, recovery window) | Decides, doesn't act |
| **Tools** | Actually send the email / generate the payment link / escalate | Only after policy approval |

The LLM never calls a tool directly. Every recommendation is checked by code, not by prompting the model to "be careful."

```
Overdue Invoice
      │
      ▼
Revenue-at-Risk + Recovery Case
      │
      ▼
Load Customer Context ──▶ XGBoost Risk/Probability Score
      │
      ▼
LLM Diagnosis ──▶ LLM Intervention Recommendation
      │
      ▼
Deterministic Policy Engine  ◀── hard-coded rules, not prompted behavior
      │  (approved)
      ▼
Mock Tool Execution (email / payment link / escalate)
      │
      ▼
Outcome Recorded ──▶ Recovered? ──yes──▶ Close Case
      │no
      ▼
Recovery window still valid? ──no──▶ Escalate / Close
      │yes
      ▼
Next Allowed Action (loop back to Policy Engine)
      │
      ▼
Audit Trail + Dashboard Metrics  (every step above is logged here)
```

## Tech stack

| Area | Choice | Why |
|---|---|---|
| Backend | Python 3.12, FastAPI, Pydantic, SQLAlchemy (async) | typed, async, industry-standard for AI services |
| Database | PostgreSQL | relational integrity for financial/audit data; `NUMERIC`, never float, for money |
| Agent orchestration | LangGraph | explicit typed state machine — not an open-ended agent loop |
| LLM | OpenAI-compatible, structured output via Pydantic | swappable provider, no unstructured free-text decisions |
| ML | XGBoost | recovery probability / risk scoring, trained on synthetic data |
| Events | Kafka (local, Docker) | domain events (`invoice.overdue`, `payment.received`, ...); wired in once the core workflow is proven |
| Caching / state | Redis | idempotency, locks, scheduling metadata |
| Frontend | Next.js, TypeScript, Tailwind | dashboard + case detail views |
| Testing | Pytest | unit + integration coverage on the deterministic layers |
| Infra | Docker, Docker Compose | one-command local environment |

Full architecture writeup: [docs/architecture.md](docs/architecture.md).

## Why these boundaries (V1 scope)

This is a portfolio project, not a startup MVP or a production system, so scope is deliberately narrow and deep rather than broad and shallow:

- **One complete workflow** (B2B overdue invoice recovery), fully wired end-to-end, rather than partial coverage of many workflows.
- **Seeded, synthetic data** — realistic companies/invoices/payment histories covering low/medium/high risk and escalation scenarios, no real integrations.
- **Mock tools** for email, payment links, and escalation, built behind interfaces so Stripe/Resend/Twilio can be substituted later without touching the agent logic.
- Explicitly **not building**: real payment processing, real collections, voice/Hinglish agents, multi-agent swarms, or production-scale infra. See [docs/architecture.md](docs/architecture.md#v1-boundaries) for the full list and the planned V2–V4 direction.

## Project structure

```
backend/
  app/
    core/       # config, db session, logging
    models/     # SQLAlchemy models
    schemas/    # Pydantic schemas
    api/        # FastAPI routers
    services/   # risk engine, policy engine, case orchestration
    ml/         # XGBoost training + inference
    agents/     # LangGraph workflow, diagnosis/intervention agents, LLM client
    tools/      # mock email / payment-link / escalation tools
    events/     # event publisher abstraction (in-process now, Kafka later)
    seed/       # synthetic data + scenario generators
  tests/
infra/
  docker-compose.yml
docs/
  architecture.md   # full design: schema, event model, LangGraph state, API surface
frontend/           # Next.js dashboard (added once the backend workflow is complete)
```

## Getting started

Requires Docker and Docker Compose.

```bash
cd infra
docker compose up --build
```

This starts PostgreSQL and the FastAPI backend. Once it's up:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/health/db
```

Full local (non-Docker) setup and environment variables are documented in [backend/README.md](backend/README.md).

## Build status

Built and verified incrementally, phase by phase — each phase has explicit acceptance criteria before the next one starts.

- [x] **Phase 1** — Project scaffold, Docker Compose, PostgreSQL, FastAPI health checks
- [x] **Phase 2** — Database models (all 12 tables) + Alembic migrations
- [x] **Phase 3** — Seed mock enterprise data (5 risk scenarios + 1 healthy account)
- [ ] Phase 4 — FastAPI CRUD/read APIs
- [ ] Phase 5 — Revenue-at-risk & recovery-case engine
- [ ] Phase 6 — XGBoost recovery-risk model (synthetic training data)
- [ ] Phase 7 — LangGraph recovery workflow
- [ ] Phase 8 — Diagnosis agent
- [ ] Phase 9 — Intervention agent
- [ ] Phase 10 — Deterministic policy engine
- [ ] Phase 11 — Mock recovery/action tools
- [ ] Phase 12 — Outcome tracking + promise-to-pay
- [ ] Phase 13 — Kafka event integration
- [ ] Phase 14 — Redis / idempotency / state management
- [ ] Phase 15 — Next.js dashboard
- [ ] Phase 16 — Audit trail + observability
- [ ] Phase 17 — Testing
- [ ] Phase 18 — End-to-end demo

## Explicit non-goals for V1

No real financial transactions, real customer collections, production payment processing, legal collections automation, autonomous negotiation, voice/Hinglish agents, or production-scale infrastructure. This is a controlled simulation intended to demonstrate agentic-system design with proper guardrails, not a product.

## License

MIT
