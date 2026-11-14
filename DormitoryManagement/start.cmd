@echo off
setlocal
cd /d "%~dp0"
if exist "dist\AlMuthannaNative\AlMuthannaNative.exe" (
    start "" "dist\AlMuthannaNative\AlMuthannaNative.exe"
    exit /b 0
)
if not exist ".venv\Scripts\pythonw.exe" (
    echo Please follow README.md to install the development environment.
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "main.py"
