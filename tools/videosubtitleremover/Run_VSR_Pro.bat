@echo off
setlocal EnableDelayedExpansion

title Video Subtitle Remover Pro

:: Change to script directory
cd /d "%~dp0"

:: Check if venv exists
if not exist "venv\Scripts\python.exe" (
    echo.
    echo  ============================================================
    echo   VIDEO SUBTITLE REMOVER PRO
    echo  ============================================================
    echo.
    echo  First-time setup required.
    echo  Preparing the runtime and dependencies...
    echo.
    python setup.py
    if errorlevel 1 (
        echo.
        echo  Setup did not complete. Review the messages above, then try again.
        pause
        exit /b 1
    )
)

echo Launching Video Subtitle Remover Pro...
if exist "venv\Scripts\pythonw.exe" (
    start "" "venv\Scripts\pythonw.exe" "VideoSubtitleRemover.py"
    exit /b 0
)

if exist "venv\Scripts\python.exe" (
    start "" "venv\Scripts\python.exe" "VideoSubtitleRemover.py"
    exit /b 0
)

echo.
echo  The Python runtime could not be found in the virtual environment.
echo  Re-run setup.py to repair the installation.
pause
exit /b 1
