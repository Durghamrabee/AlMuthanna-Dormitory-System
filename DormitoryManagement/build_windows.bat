@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Create the Python 3.12 or 3.13 environment described in README.md first.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" "tools\build_windows.py"
if errorlevel 1 (
    echo Build failed. Review the error above.
    pause
    exit /b 1
)
echo The portable package and checksum are in the releases folder.
pause
