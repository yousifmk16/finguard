# Test Plan

Sprint 0 baseline — superseded by the finalized test report (DOC-03, Sprint 5).

- **Finalized test report:** [`TEST_REPORT.md`](TEST_REPORT.md)

## Test Layers

- Unit tests: feature builders, scoring, rules (ml/tests/, services/tests/)
- Integration tests: ingest → detect → alert (backend/tests/test_integration_pipeline.py)
- API contract tests (backend/tests/test_api_contract.py)
- Performance tests: latency SLA (<60 s) — asserted in integration pipeline test

## Exit Criteria (Sprint 5 — all met)

| Criterion | Result |
|-----------|--------|
| Pass rate ≥ 99 % | 99.9 % (1124/1125) |
| Zero false positives on MLQ validation set | FP = 0 |
| Recall ≥ 0.70 | Recall = 0.730 |
| All 12 API endpoints covered | ✓ |
| No critical defects open | ✓ |
| Demo scenario runs end-to-end | ✓ |
