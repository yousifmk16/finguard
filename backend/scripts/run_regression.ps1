# TST-08: Run the full regression suite with coverage.
# Usage: .\scripts\run_regression.ps1 [extra pytest args]
#   e.g. .\scripts\run_regression.ps1 -k test_ingestion
param([Parameter(ValueFromRemainingArguments)][string[]]$ExtraArgs)

$backendDir = Split-Path -Parent $PSScriptRoot
Set-Location $backendDir

& .\.venv\Scripts\python.exe -m pytest tests/ `
    -v `
    --tb=short `
    --cov=app `
    --cov-report=term-missing `
    --cov-report=html:htmlcov `
    @ExtraArgs
