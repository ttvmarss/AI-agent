@echo off
rem Double-click to bring PRAXIS up to date and open it. Safe to run any time; it only touches this folder and your user Python packages.
setlocal
cd /d "%~dp0.."
echo.
echo PRAXIS update  (folder: %CD%)
echo.
where git >nul 2>nul
if errorlevel 1 (
    echo [!] git was not found, so the code cannot be updated from here. Install Git for Windows, or download the new zip.
) else (
    git fetch origin claude/praxis-architecture-rev0
    git checkout claude/praxis-architecture-rev0
    git pull origin claude/praxis-architecture-rev0
)
echo.
echo.
echo This is the build you are about to run:
py -3 -c "from praxis import build; print('  ', build.label())"
echo.
start "" pyw -3 -m praxis.ui
