@echo off
REM Build a standalone Windows application folder with PyInstaller.
REM Result: dist\IsoResearchAI\IsoResearchAI.exe   (copy the whole folder to install)
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Run setup_windows.bat first.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m pip install "pyinstaller>=6.6"
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean isoresearch.spec
if errorlevel 1 (
    echo [ERROR] Build failed - see docs\PACKAGING.md
    pause
    exit /b 1
)
echo.
echo Built: dist\IsoResearchAI\IsoResearchAI.exe
pause
