$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = Split-Path -Parent $ScriptDir

Set-Location $BackendDir

& .\.venv\Scripts\Activate.ps1

Write-Host "Running migrations..."
alembic upgrade head

Write-Host "Starting backend on http://localhost:8000"
uvicorn app.main:app --reload --port 8000
