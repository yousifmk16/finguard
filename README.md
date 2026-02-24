# finguard

Repository skeleton for the Real-Time Cloud Billing Anomaly Detection project.

## Project Goal

Build a real-time cloud billing anomaly detection platform with explainable alerts,
web dashboard visibility, and in-app/email notifications.

## Current Stage

Skeleton and engineering foundations are in place. Core features (data generator,
ingestion, detection, and UI logic) are planned next.

## Setup

### Prerequisites

- Git
- Docker + Docker Compose
- Python 3.11+
- Node.js 20+ (see `frontend/.nvmrc`)

### 1) Clone Repository

```bash
git clone https://github.com/yousifmk16/finguard.git
cd finguard
```

### 2) Backend Setup

```bash
cd backend
./scripts/setup_env.ps1   # Windows PowerShell
# or
./scripts/setup_env.sh    # Linux/macOS
```

### 3) Frontend Setup (Placeholder)

```bash
cd frontend
npm install
npm run lint
npm test
```

### 4) Environment Variables

- Backend env file: copy `backend/.env.example` to `backend/.env`
- Frontend env file: `frontend/.env` (to be added)
- Required variables list will be documented in sprint implementation.

### 5) Run Services (Placeholder)

```bash
cd infra/docker
docker compose up --build
```

### 6) Verify CI/Lint Baseline

```bash
# backend lint placeholder
ruff check backend/app backend/tests
```

## Top-level folders

- `backend/` API and service logic
- `frontend/` web dashboard
- `ml/` model training and inference code
- `data/` synthetic and processed datasets
- `infra/` deployment and infrastructure assets
- `docs/` architecture, API, testing, and runbooks
- `tests/` cross-service test suites

## Team Standards

- Contribution and coding standards: `CONTRIBUTING.md`

## CI

- GitHub Actions workflow: `.github/workflows/ci.yml`

## Run 1 Artifacts

- Requirements: `docs/requirements/requirements-spec.md`
- Architecture: `docs/architecture/architecture-overview.md`
- API contracts: `docs/api/api-contracts.md`
- Test plan: `docs/testing/test-plan.md`
- Backlog snapshot: `docs/sprint/product-backlog.md`
- Python runbook: `docs/runbooks/python-environment.md`
- Node runbook: `docs/runbooks/node-environment.md`
- Sprint 0 board: `docs/sprint/sprint-0-board.md`

## Contribution

- Standards and branch workflow: `CONTRIBUTING.md`
- PR template: `.github/PULL_REQUEST_TEMPLATE.md`

## Notes

Frontend and Docker sections are placeholders for the current project stage.
Backend Python environment setup is active and ready to use.
