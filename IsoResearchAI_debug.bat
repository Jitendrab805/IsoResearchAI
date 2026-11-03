@echo off
REM Start IsoResearch AI with a console window so error messages are visible.
cd /d "%~dp0"
".venv\Scripts\python.exe" -m isoresearch
echo.
echo IsoResearch AI exited with code %errorlevel%.
pause
