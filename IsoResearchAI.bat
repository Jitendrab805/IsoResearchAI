@echo off
REM Launch IsoResearch AI in its own desktop window (no console window).
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo IsoResearch AI is not set up yet. Running setup_windows.bat first...
    call setup_windows.bat
    if not exist ".venv\Scripts\pythonw.exe" exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -m isoresearch
