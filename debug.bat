@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set PYTHONUNBUFFERED=1
if exist "venv\Scripts\python.exe" (set "PY=venv\Scripts\python.exe") else if exist ".venv\Scripts\python.exe" (set "PY=.venv\Scripts\python.exe") else (set "PY=python")
"%PY%" run_dev.py %*
exit /b %ERRORLEVEL%
