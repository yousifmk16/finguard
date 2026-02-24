# Python Environment Runbook

This runbook documents the backend Python setup for local development.

## Version

- Python `3.11` (`backend/.python-version`)

## Setup (Windows PowerShell)

```powershell
cd backend
./scripts/setup_env.ps1
```

## Setup (Linux/macOS)

```bash
cd backend
chmod +x scripts/setup_env.sh
./scripts/setup_env.sh
```

## Manual setup

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
pip install -r requirements.txt
```

## Verify

```bash
cd backend
ruff check app tests
pytest tests
```

## Environment file

Copy `backend/.env.example` to `backend/.env` and set local values.
