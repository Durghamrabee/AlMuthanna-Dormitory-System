@echo off
setlocal
cd /d "%~dp0"
set "PROJECT_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PROJECT_PYTHON%" set "PROJECT_PYTHON=%~dp0..\..\.venv\Scripts\python.exe"
if not exist "%PROJECT_PYTHON%" (
  echo Install the project virtual environment first. See README.md.
  pause
  exit /b 1
)
"%PROJECT_PYTHON%" scripts\configure_local.py
if errorlevel 1 exit /b 1
"%PROJECT_PYTHON%" manage.py migrate --check
if errorlevel 1 (
  echo Pending migrations. Back up the database and run manage.py migrate first.
  pause
  exit /b 1
)
"%PROJECT_PYTHON%" manage.py ensure_local_admin
if errorlevel 1 exit /b 1
"%PROJECT_PYTHON%" manage.py runserver 127.0.0.1:8000 --noreload
