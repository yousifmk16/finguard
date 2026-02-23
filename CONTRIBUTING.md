# Contributing Guide

This document defines naming conventions and coding standards for `finguard`.

## 1) General Principles

- Keep changes small and focused (one user story per PR).
- Prefer clear naming over clever code.
- Write testable functions and avoid hidden side effects.
- Follow existing structure and patterns before introducing new ones.

## 2) Naming Conventions

### Branches

- Feature: `feature/<story-id>-<short-name>`
- Fix: `fix/<ticket-id>-<short-name>`
- Chore: `chore/<short-name>`
- Docs: `docs/<short-name>`
- Tests: `test/<short-name>`

Examples:
- `feature/US-07-hybrid-score-fusion`
- `fix/API-03-status-update-validation`

### Files and folders

- Python modules: `snake_case.py`
- TypeScript/JavaScript utility files: `kebab-case.ts`
- React component files: `PascalCase.tsx`
- Tests: `<unit-under-test>.test.<ext>`
- Docs: `kebab-case.md`

### Code symbols

- Classes: `PascalCase`
- Functions/methods: `snake_case` (Python), `camelCase` (TS/JS)
- Constants: `UPPER_SNAKE_CASE`
- Variables: clear descriptive names, avoid single-letter names except loop indices

### API naming

- REST paths use plural nouns and kebab-case where needed
- Example paths:
  - `/api/v1/anomalies`
  - `/api/v1/anomalies/{id}`
  - `/api/v1/alerts`

## 3) Commit and PR Standards

### Commit style (Conventional Commits)

- `feat:` new functionality
- `fix:` bug fix
- `refactor:` non-functional code improvements
- `test:` test additions/updates
- `docs:` documentation changes
- `chore:` maintenance/build/config

Examples:
- `feat: add anomaly detail endpoint`
- `fix: handle missing account_id in ingestion payload`

### Pull Requests

Each PR should include:
- linked story/task ID,
- summary of changes,
- test evidence,
- screenshots for UI changes.

## 4) Coding Standards

### Python (backend, ml)

- Use type hints for public functions.
- Keep functions small and single-purpose.
- Raise specific exceptions; avoid bare `except`.
- Prefer dataclasses/pydantic models for structured data.
- Keep side-effect code isolated from pure logic.

### TypeScript/React (frontend)

- Use strict typing (avoid `any` unless justified).
- Keep components presentational when possible.
- Move API calls and data mapping into service/hooks layer.
- Handle loading, empty, and error states explicitly.

### Configuration and secrets

- Do not commit secrets.
- Use `.env` files locally and env variables in deployment.
- Keep sample values in `.env.example` only.

## 5) Testing Standards

- Unit tests for core logic and edge cases.
- Integration tests for ingestion -> detection -> alert flow.
- API contract tests for request/response schema.
- Use deterministic test data where possible.

Minimum expectations before merge:
- lint passes,
- tests pass,
- critical path unaffected.

## 6) Documentation Standards

- Update docs in the same PR when behavior changes.
- Keep architecture diagrams and API docs version-aligned.
- Add brief rationale for non-obvious design decisions.
