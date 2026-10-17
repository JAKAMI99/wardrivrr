@echo off
setlocal EnableExtensions
cd /d "%~dp0"

REM Local debug runner — PostGIS + host API (run_dev.py). Not for the car mini-PC.
REM Unbuffered Python so logs keep flowing (avoids "frozen" looking console)
set PYTHONUNBUFFERED=1

if exist "venv\Scripts\python.exe" (
  set "PY=venv\Scripts\python.exe"
) else if exist ".venv\Scripts\python.exe" (
  set "PY=.venv\Scripts\python.exe"
) else (
  set "PY=python"
)

echo [wardrivrr] debug: %PY% run_dev.py %*
echo [wardrivrr] file-change reload stays inside the API; Ctrl+C stops for good
echo [wardrivrr] (clicking this window no longer freezes it)
"%PY%" run_dev.py %*
set "EC=%ERRORLEVEL%"
echo [wardrivrr] exited with code %EC%
exit /b %EC%
