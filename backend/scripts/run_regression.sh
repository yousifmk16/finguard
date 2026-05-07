#!/usr/bin/env bash
# TST-08: Run the full regression suite with coverage.
# Usage: ./scripts/run_regression.sh [extra pytest args]
#   e.g. ./scripts/run_regression.sh -k test_ingestion
set -euo pipefail
cd "$(dirname "$0")/.."

python -m pytest tests/ \
    -v \
    --tb=short \
    --cov=app \
    --cov-report=term-missing \
    --cov-report=html:htmlcov \
    "$@"
