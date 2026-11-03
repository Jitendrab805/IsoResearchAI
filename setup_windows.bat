@echo off
REM ==========================================================================
REM  IsoResearch AI - Windows setup
REM  Creates a private Python environment in .venv and installs dependencies.
REM  Needs internet ONCE (Python packages). Your papers are never uploaded.
REM ==========================================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"
echo.
echo  IsoResearch AI setup
echo  --------------------

set "PY="
for %%V in (3.12 3.11 3.13 3.10) do (
    if not defined PY (
        py -%%V -c "import sys" >nul 2>&1 && set "PY=py -%%V"
    )
)
if not defined PY (
    python -c "import sys; assert sys.version_info >= (3,10)" >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo [ERROR] Python 3.10-3.13 was not found.
    echo         Install Python 3.12 from https://www.python.org/downloads/windows/
    echo         and tick "Add python.exe to PATH" during installation. Then run this file again.
    pause
    exit /b 1
)
echo Using: %PY%
%PY% --version

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment in .venv ...
    %PY% -m venv .venv || (echo [ERROR] Could not create the virtual environment. & pause & exit /b 1)
)
set "VPY=.venv\Scripts\python.exe"
"%VPY%" -m pip install --upgrade pip
echo Installing required packages (this can take a few minutes) ...
"%VPY%" -m pip install -r requirements.txt || (
    echo [ERROR] Package installation failed. See the messages above and docs\TROUBLESHOOTING.md
    pause
    exit /b 1
)

echo.
set /p SEM="Install OPTIONAL semantic embeddings (sentence-transformers + CPU PyTorch, ~1 GB)? [y/N] "
if /i "!SEM!"=="y" (
    "%VPY%" -m pip install torch --index-url https://download.pytorch.org/whl/cpu
    "%VPY%" -m pip install -r requirements-embeddings.txt
    "%VPY%" scripts\download_embedding_model.py
)

echo Generating the SYNTHETIC example datasets ...
"%VPY%" examples\make_synthetic_data.py

echo Running a quick start-up check ...
set ISORESEARCH_SMOKE_MS=1500
"%VPY%" -m isoresearch --smoke-test
if errorlevel 1 (
    echo [WARNING] The start-up check reported a problem. See docs\TROUBLESHOOTING.md
) else (
    echo Start-up check OK.
)

echo.
echo ==========================================================================
echo  Setup complete.
echo  Next steps for the local AI model (optional but recommended):
echo    1. Install Ollama for Windows from https://ollama.com and start it.
echo    2. In a terminal run:   ollama pull qwen2.5:7b      (about 4.7 GB)
echo    3. Start IsoResearch AI with  IsoResearchAI.bat  and choose the model
echo       in Settings - AI model.
echo  Without a model you can still import, search and organise papers,
echo  analyse data and make plots.
echo ==========================================================================
pause
