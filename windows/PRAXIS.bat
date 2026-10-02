@echo off
rem Double-click to start the PRAXIS desktop app (no console window).
setlocal
cd /d "%~dp0.."
where pyw >nul 2>nul
if %errorlevel%==0 (
    start "" pyw -3 -m praxis.ui %*
    exit /b 0
)
where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw -m praxis.ui %*
    exit /b 0
)
echo.
echo PRAXIS needs Python 3.11 or newer (the python.org installer includes Tk).
echo Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH",
echo (PRAXIS opens in Microsoft Edge or Google Chrome, which you already have; nothing else to install),
echo then double-click this file again. Or run windows\Install-PRAXIS.ps1 for guided setup.
echo.
pause
