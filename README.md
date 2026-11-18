# Crisis Safety and Humanitarian Intelligence Platform

Community crisis reporting, a public incident map, safety alerts and humanitarian intelligence.
The specifications are in [docs/source/](docs/source/). Where they conflict, [docs/DECISIONS.md](docs/DECISIONS.md)
records the choice the code makes.

## Status

The **first vertical slice** (Engineering pack §12.1, roadmap phases 0–5) is implemented in `backend/`:

anonymous report → validation → global idempotency → anonymous access credential → outbox →
worker intake + conservative matching → provisional incident or association → sanitized,
generalized public projection → public GeoJSON map.

| Area | State |
|------|-------|
| Database schema: all 11 schemas, 38 tables, guards, grants, seed data (migrations 0001–0015) | Written, **not yet run against PostGIS** |
| `POST /api/v1/reports` (idempotent, anonymous), `GET /reports/{id}/status` (token) | Done |
| `GET /api/v1/public/incidents` (bbox or radius, GeoJSON), `/{public_id}`, `/removals` | Done |
| `GET /api/v1/incident-categories` | Done |
| Outbox worker: matching (policy `match-2026.11.1`), projection refresh, freshness sweep | Done |
| Nightly retention: reports redacted after 30 days, reporter links purged after 7 (U-2) | Done |
| Neon + Render deployment (`render.yaml`, `python -m app.manage`, [docs/DEPLOY.md](docs/DEPLOY.md)) | Ready; waiting for the Neon and Render accounts |
| Unit tests (matching, disclosure, tokens, idempotency, config, API validation, failure handling) | 53 written; 52 pass on Python 3.11 (the UUIDv7 test needs 3.14), not yet run on 3.14 |
| Integration tests (DB spec §12.2 and slice acceptance §9.2) | Written, need PostGIS to run |
| Auth, review dashboard API, evidence upload, alerts, subscriptions, journey checks, organizations, intelligence, Flutter app, Next.js dashboard | Not started (phases 6–11) |

## Run locally

Needs Docker Desktop.

```bash
docker compose up --build        # PostGIS, migrations, API on :8000, worker
# API docs: http://localhost:8000/docs
```

Without Docker: PostgreSQL 18 with PostGIS 3.6 (what Neon runs), Python 3.14.

```bash
cd backend
python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"     # .venv/bin on Linux/macOS
psql -U postgres -f ../infra/db/init/00_roles.sql                  # runtime roles + crisis_test db
export DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/crisis
alembic upgrade head
uvicorn app.main:app --reload       # API
python -m app.worker                # worker, separate process
```

## Tests

```bash
cd backend
pytest tests/unit                                       # no database needed
TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/crisis_test pytest
```

Running the integration suite against PostGIS is the first job (DB spec risk R-1): it is the
only check of the DDL, triggers and spatial SQL.

## Try it

```bash
curl -X POST localhost:8000/api/v1/reports \
  -H "Idempotency-Key: $(uuidgen)" -H "Content-Type: application/json" \
  -d '{"category":"fire","location":{"latitude":5.9631,"longitude":10.1591}}'
# returns report_id, public_reference and a one-time access_token (keep it)

curl "localhost:8000/api/v1/public/incidents?bbox=10.1,5.9,10.2,6.0"
```

## Layout

```
backend/
  app/core/              config, database, error envelope, logging, token hashing
  app/modules/reporting/ submission, idempotency, anonymous status
  app/modules/incidents/ matching policy (pure) and matching transaction
  app/modules/disclosure/ projection policy (pure), projection service, public map routes
  app/infrastructure/    outbox, audit log, worker loop
  migrations/sql/        hand-written DDL, one file per Alembic revision
  tests/unit, tests/integration
infra/db/init/           runtime database roles (dev passwords only)
docs/                    source specifications and implementation decisions
```

## Decided (2026-11-18)

External OIDC sign-in, short-lived reports kept as incident history, automatic alerts, Neon + Render
hosting, and a UI/UX and branding phase before any frontend. Details in [docs/DECISIONS.md](docs/DECISIONS.md).

Still open: which OIDC provider; legal review of retention windows; disclosure policies for the 7
categories added from the API contract.
