@echo off
setlocal
cd /d "%~dp0\.."

if exist "venv\Scripts\python.exe" (
  set "PY=venv\Scripts\python.exe"
) else if exist ".venv\Scripts\python.exe" (
  set "PY=.venv\Scripts\python.exe"
) else (
  set "PY=python"
)

echo [docker/prepare-data] using %PY%
"%PY%" scripts\prepare_offline_data.py %*
exit /b %ERRORLEVEL%
