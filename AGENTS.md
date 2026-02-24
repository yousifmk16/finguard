# AGENTS

This file defines project-specific instructions for AI coding agents working in this repository.

## 1) Project Context

- Project: real-time cloud billing anomaly detection platform.
- Strategy: multi-cloud architecture with GCP-priority defaults.
- Current maturity: foundations and baselines are complete; implementation is incremental by sprint.

## 2) Source-of-Truth Documents

- Module map: `MODULES.md`
- Contribution rules: `CONTRIBUTING.md`
- Requirements baseline: `docs/requirements/sprint-1-requirements-baseline.md`
- Architecture baseline: `docs/architecture/sprint-1-architecture-baseline.md`
- API contract baseline: `docs/api/api-contracts.md`
- Deliverable record index: `docs/sprint/deliverables/index.md`

When making design-sensitive changes, align with these documents or update them in the same PR.

## 3) Repository Structure

- `backend/`: FastAPI services and backend tests
- `frontend/`: dashboard app
- `ml/`: feature/model code
- `data/`: synthetic and processed datasets
- `infra/`: Docker/K8s/scripts
- `docs/`: requirements/architecture/api/testing/sprint records
- `tests/`: integration/e2e/performance

## 4) Engineering Rules (Must Follow)

1. Keep changes scoped to the requested task.
2. Do not break existing API contracts without updating docs and callers.
3. Never commit secrets, credentials, private keys, or real billing exports.
4. Prefer small PRs; one user story/task per branch.
5. Preserve GCP-priority defaults while keeping provider adapters generic.
6. Add or update tests for non-trivial behavior changes.
7. Update deliverable/task records for completed tasks.

## 5) Coding Conventions

- Follow `CONTRIBUTING.md` for naming, commit style, and PR policy.
- Python: type hints for public functions, clear exceptions, testable units.
- Frontend: explicit loading/error/empty states; avoid unnecessary `any`.
- Keep modules cohesive and loosely coupled across boundaries.

## 6) Definition of Done (Task-Level)

A task is done only when all are true:

- implementation complete,
- lint passes,
- relevant tests pass,
- docs updated (if behavior/contract changed),
- deliverable record added or updated under `docs/sprint/deliverables/records/`.

## 7) Commands AI Should Use

Backend:

```bash
cd backend
python -m pip install -r requirements-dev.txt
python -m pip install -r requirements.txt
ruff check app tests
pytest tests
```

Frontend:

```bash
cd frontend
npm install
npm run lint
npm test
```

Local stack:

```bash
cd infra/docker
docker compose up --build
```

## 8) Documentation Requirements for New Work

For each completed task/story:

1. Update implementation files.
2. Add/update corresponding record file in:
   - `docs/sprint/deliverables/records/`
3. If architectural behavior changed, update:
   - `docs/requirements/sprint-1-requirements-baseline.md` and/or
   - `docs/architecture/sprint-1-architecture-baseline.md` and/or
   - `docs/api/api-contracts.md`

## 9) Preferred Implementation Order (Current)

1. `synthetic-data-generator`
2. `ingestion-api` + `stream-consumer-normalizer`
3. `feature-engineering-pipeline`
4. detection trio (`timeseries-anomaly-model`, `isolation-forest-anomaly-model`, `rule-engine`)
5. `hybrid-score-fusion` + `explainability-engine`
6. `anomaly-store-service` + `alert-orchestrator`
7. `backend-query-api` + `web-dashboard`
8. hardening: `observability-reliability`, `ci-cd-quality-gates`, `deployment-profiles`

## 10) Output Quality Expectations

- Explain decisions briefly in PR descriptions.
- Avoid placeholder-only implementations unless task explicitly asks for skeletons.
- Prefer deterministic behavior in tests.
- Keep backward compatibility where possible.
