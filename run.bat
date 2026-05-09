@echo off
title FinGuard Launcher
color 0A

echo =======================================
echo        FinGuard - Starting Up
echo =======================================
echo.

:: ---- Locate project root (the folder this .bat lives in) ----
set "ROOT=%~dp0"
set "FRONTEND=%ROOT%frontend"
set "BACKEND=%ROOT%backend"

:: ---- Check Node ----
where node >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js not found. Install from https://nodejs.org
    pause & exit /b 1
)

:: ---- Check Python ----
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install from https://python.org
    pause & exit /b 1
)

:: ---- Install frontend deps if missing ----
if not exist "%FRONTEND%\node_modules" (
    echo [1/3] Installing frontend dependencies...
    cd /d "%FRONTEND%"
    call npm install --silent
    if errorlevel 1 ( echo [ERROR] npm install failed & pause & exit /b 1 )
    echo       Done.
    echo.
)

:: ---- Start backend ----
echo [2/3] Starting backend  (http://localhost:8000)
start "FinGuard - Backend" cmd /k "cd /d "%BACKEND%" && set PYTHONPATH=%ROOT% && .venv\Scripts\python.exe -m alembic upgrade head && .venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000"

:: ---- Start frontend ----
echo [3/3] Starting frontend (http://localhost:3000)
start "FinGuard - Frontend" cmd /k "cd /d "%FRONTEND%" && npm run dev"

:: ---- Wait then open browser ----
echo.
echo Waiting for servers to start...
timeout /t 4 /nobreak >nul
start "" "http://localhost:3000"

echo.
echo =======================================
echo  App running at http://localhost:3000
echo  Close the two terminal windows to stop
echo =======================================
echo.
pause
