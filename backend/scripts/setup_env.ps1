$ErrorActionPreference = "Stop"

python -m venv .venv
& .\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
pip install -r requirements-dev.txt
pip install -r requirements.txt

Write-Host "Backend virtual environment is ready."
