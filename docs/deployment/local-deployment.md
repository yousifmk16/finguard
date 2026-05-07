# OPS-05 — Local deployment guide

A walkthrough for getting the FinGuard stack running on a single developer
machine. Production deployment lives in
[`cloud-deployment.md`](cloud-deployment.md) (OPS-06).

> **Audience:** developers and reviewers who want to verify the system
> end-to-end, run the test suite, or reproduce a bug locally. Not for
> production use — secrets default to dev fallbacks and the DLQ writes
> to a relative path.

## 1. Service map

The full stack is six processes. The first four are required for the API
to serve traffic; the consumers can be left off when you only want to test
the HTTP surface.

| # | Process | Default port | Required? | Source |
| - | --- | --- | --- | --- |
| 1 | PostgreSQL  | 5432 | yes | external |
| 2 | Redis       | 6379 | yes (any flow that uses streams) | external |
| 3 | Backend API | 8000 | yes | `backend/` |
| 4 | Frontend    | 3000 | UI only | `frontend/` |
| 5 | Stream consumer (ingestion) | n/a | only when ingesting via stream | `python -m services.stream.consumer` |
| 6 | Alert orchestrator | n/a | only when testing alert flows | `python -m app.alerts.orchestrator` |

## 2. Prerequisites

- Git
- **Python 3.11** — pinned in `backend/.python-version`. See [python-environment.md](../runbooks/python-environment.md).
- **Node.js 20** — pinned in `frontend/.nvmrc`. See [node-environment.md](../runbooks/node-environment.md).
- **PostgreSQL 14+** — running locally on `5432`, or accessible via
  `DATABASE_URL`.
- **Redis 7+** — running locally on `6379`, or accessible via `REDIS_URL`.
  Ingestion through the HTTP API does **not** require Redis; only the
  stream pipeline does.

> Windows users: prefer WSL2 or Docker Desktop for Postgres + Redis. The
> Python backend, frontend, and tests all run cleanly on native Windows.

## 3. Quick start

If your prereqs are already installed and Postgres / Redis are listening
on their default ports:

```bash
git clone https://github.com/yousifmk16/finguard.git
cd finguard

# 1. Backend
cd backend
./scripts/setup_env.sh        # Linux/macOS
# .\scripts\setup_env.ps1     # Windows PowerShell
cp .env.example .env
createdb finguard             # if Postgres is local
alembic upgrade head
.venv/bin/uvicorn app.main:app --port 8000   # or .\scripts\run_local.ps1

# 2. Frontend (in a second terminal)
cd ../frontend
cp .env.example .env.local
npm install
npm run dev
```

Open http://localhost:3000 for the UI and http://localhost:8000/docs for
the API. Verify with section 7.

## 4. Detailed setup

### 4.1 Backend env file

Copy `backend/.env.example` to `backend/.env` and adjust if needed:

```ini
APP_ENV=development
APP_PORT=8000
LOG_LEVEL=INFO
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/finguard
REDIS_URL=redis://localhost:6379/0
```

The full set of env vars FinGuard reads at runtime (with defaults):

| Var | Default | Used by |
| --- | --- | --- |
| `DATABASE_URL` | _(none — required)_ | SQLAlchemy session factory |
| `REDIS_URL` | `redis://localhost:6379/0` | `RedisStreamBroker` |
| `JWT_SECRET` | `dev-only-fallback` | `app.core.security` (set in any non-dev environment) |
| `JWT_ALGORITHM` | `HS256` | JWT issuance/validation |
| `JWT_EXPIRE_MINUTES` | `60` | token TTL |
| `FINGUARD_LOG_LEVEL` | `INFO` | OPS-02 logging |
| `FINGUARD_LOG_FORMAT` | `json` | OPS-02 logging — set to `text` for readable local output |
| `FINGUARD_CORS_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` | CORS allow-list |
| `STREAM_NAME` | `billing-events` | publisher + consumer |
| `STREAM_DLQ_PATH` | `logs/dlq.jsonl` | OPS-04 dead letters |
| `STREAM_CONSUMER_GROUP` | `billing-stream-consumers` | Redis Streams consumer group |
| `STREAM_CONSUMER_NAME` | `<host>-worker` | Redis Streams consumer id |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` | unset | `EmailChannel` (skipped when unset) |
| `ALERT_FROM_ADDRESS` / `ALERT_RECIPIENTS` | unset / empty | email alerts |
| `FINGUARD_WEIGHT_*` | see `services/rules/config.py` | rule weights |
| `FINGUARD_THRESHOLD_*` | see `services/rules/config.py` | rule thresholds |

Tip: for readable local logs, run with `FINGUARD_LOG_FORMAT=text`.

### 4.2 Postgres

Create the database and apply migrations:

```bash
createdb finguard            # uses your default Postgres user
cd backend
alembic upgrade head
```

Migrations live in [`backend/alembic/versions`](../../backend/alembic/versions)
(currently 5 migrations: billing events, anomalies, alerts, users,
audit logs). Re-running `alembic upgrade head` is idempotent.

### 4.3 Redis

Skip this section if you only need the HTTP API. The simplest path is
Docker:

```bash
docker run -d --name finguard-redis -p 6379:6379 redis:7-alpine
```

Or install natively (`brew install redis`, `apt install redis-server`,
WSL apt). Verify with `redis-cli ping` → `PONG`.

### 4.4 Backend install + run

```bash
cd backend
./scripts/setup_env.sh        # creates .venv, installs both requirement files
.venv/bin/uvicorn app.main:app --reload --port 8000
```

Windows: `.\scripts\run_local.ps1` activates the venv, runs `alembic upgrade head`,
and starts uvicorn in one shot.

### 4.5 Frontend install + run

```bash
cd frontend
cp .env.example .env.local       # already pre-configured for localhost:8000
npm install
npm run dev                      # starts Vite on http://localhost:3000
```

The dev server proxies `/api/*` to `VITE_API_PROXY_TARGET` (default
`http://localhost:8000`), so the SPA does not need CORS to talk to the
backend during development.

### 4.6 Stream consumer (optional)

When you want to test stream-mode ingestion or anomaly detection, run
the consumer in a separate terminal:

```bash
cd backend
.venv/bin/python -m services.stream.consumer
```

It reads `STREAM_NAME` from env (default `billing-events`), normalizes
each event, and routes failures to the DLQ documented in
[`retry-and-dlq.md`](../runbooks/retry-and-dlq.md).

### 4.7 Alert orchestrator (optional)

```bash
cd backend
.venv/bin/python -m app.alerts.orchestrator
```

Consumes `anomaly-events`, dispatches to the configured channels, retries
transient failures (OPS-04), and persists every alert to the `alerts`
table.

## 5. Run the test suite

After the backend venv is set up:

```bash
cd backend
./scripts/run_regression.sh      # OPS-04: full regression with coverage
# .\scripts\run_regression.ps1   # Windows
```

Or run the full repo suite (backend + services):

```bash
backend/.venv/bin/pytest backend/tests services/tests
```

## 6. Seed test data (optional)

The synthetic data generator lives in `generators/`. The simplest seed
flow is to POST a single event to the running API:

```bash
# Get an admin token (use the seeded admin from migration 0004 if present)
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@example.com","password":"changeme"}' | jq -r .access_token)

# Ingest one event
curl -X POST http://localhost:8000/api/v1/events \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "event_id":"11111111-1111-1111-1111-111111111111",
    "timestamp":"2026-05-08T12:00:00Z",
    "provider":"gcp","account_id":"acct-001","service":"BigQuery",
    "region":"us-central1","cost_amount":12.50,"usage_amount":100.0,
    "usage_unit":"core-hours","tags":{"env":"prod"},"source_type":"synthetic"
  }'
```

## 7. Verify the stack

OPS-01 / OPS-02 / OPS-03 give you three orthogonal verification points:

```bash
# Aggregate health (OPS-01) — checks app, db, ingestion store
curl -s http://localhost:8000/health | jq

# Prometheus metrics (OPS-03) — should grow with each request
curl -s http://localhost:8000/metrics | head -40

# OpenAPI spec & Swagger UI
open http://localhost:8000/docs
```

A healthy local stack returns:

```json
{
  "status": "ok",
  "version": "0.1.0",
  "timestamp": "2026-05-08T...",
  "uptime_seconds": 12.4,
  "components": {
    "app":       { "status": "ok" },
    "db":        { "status": "ok" },
    "ingestion": { "status": "ok", "store_size": 0, "store_capacity": 100000 }
  }
}
```

If `db.status` is `not_configured`, `DATABASE_URL` is unset. If it is
`error`, Postgres is not reachable — check `pg_isready -h localhost`.

## 8. Common workflows

### Tail the logs as humans

```bash
FINGUARD_LOG_FORMAT=text uvicorn app.main:app --port 8000
```

### Tail the dead-letter queue

See [`retry-and-dlq.md`](../runbooks/retry-and-dlq.md):

```bash
python -m services.stream.dlq_tools count
python -m services.stream.dlq_tools tail -n 10
```

### Look at the dashboard

`/metrics` is scrape-ready for Prometheus / Grafana Agent. The dashboard
JSON ships in [`infra/dashboards/finguard.json`](../../infra/dashboards/finguard.json) — see [`metrics-dashboards.md`](../runbooks/metrics-dashboards.md).

## 9. Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `ImportError: No module named 'jwt'` (or similar) on test run | Only `requirements-dev.txt` installed, not runtime deps | `pip install -r backend/requirements.txt` |
| `/health` returns `db.status = not_configured` | `DATABASE_URL` not exported | source `.env` or `export DATABASE_URL=...` |
| `/health` returns `db.status = error` | Postgres not running / wrong creds | `pg_isready` and re-check `DATABASE_URL` |
| `alembic.util.exc.CommandError: Can't locate revision` | Alembic versions table out of sync | drop the `alembic_version` row (or the DB) and re-run `alembic upgrade head` |
| Frontend shows CORS error in dev | `FINGUARD_CORS_ORIGINS` overridden but doesn't include `http://localhost:3000` | unset the var (defaults work) or add the origin |
| Tests pass but UI returns 401 | `JWT_SECRET` is set differently between processes | export the same secret in every shell or rely on the dev fallback |
| Stream consumer silently exits | `redis` package missing or Redis unreachable | `pip install redis` and verify `redis-cli ping` |
| DLQ file grows without bound | Bug upstream producing invalid events | inspect with `dlq_tools tail`, fix the producer; truncate `logs/dlq.jsonl` once resolved |

## 10. Resetting state

```bash
# Drop and recreate the DB
dropdb finguard && createdb finguard
cd backend && alembic upgrade head

# Clear the dead-letter queue
> logs/dlq.jsonl

# Restart with empty in-memory metrics + idempotency store
# (just bounce the uvicorn process — both are process-local)
```

## 11. Related docs

- [Python environment runbook](../runbooks/python-environment.md)
- [Node environment runbook](../runbooks/node-environment.md)
- [Metrics & dashboards (OPS-03)](../runbooks/metrics-dashboards.md)
- [Retry & dead-letter (OPS-04)](../runbooks/retry-and-dlq.md)
- [Cloud deployment guide (OPS-06)](cloud-deployment.md)
