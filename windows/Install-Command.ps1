# Adds a `praxis` command to your terminal.   Run once:  powershell -ExecutionPolicy Bypass -File windows\Install-Command.ps1
#   praxis                  opens the PRAXIS window and gives the terminal back (no console window, safe to close the terminal)
#   praxis run "..."        any other word is the normal command line (doctor, status, undo, voice, ...)
#   praxis update           pulls the latest code, then opens the window
$repo = Split-Path -Parent $PSScriptRoot
$bin = Join-Path $env:LOCALAPPDATA "PRAXIS\bin"
New-Item -ItemType Directory -Force -Path $bin | Out-Null
$cmd = @"
@echo off
rem PRAXIS launcher (written by Install-Command.ps1)
set "PRAXIS_HOME_REPO=$repo"
if /i "%~1"=="update" (
    pushd "%PRAXIS_HOME_REPO%"
    git pull origin claude/praxis-architecture-rev0
    popd
    py -3 -m praxis app
    exit /b %errorlevel%
)
set "PYTHONPATH=%PRAXIS_HOME_REPO%;%PYTHONPATH%"
py -3 -m praxis %*
"@
Set-Content -Path (Join-Path $bin "praxis.cmd") -Value $cmd -Encoding ASCII
$user = [Environment]::GetEnvironmentVariable("Path", "User")
if (-not (($user -split ";") -contains $bin)) {
    [Environment]::SetEnvironmentVariable("Path", ($user.TrimEnd(";") + ";" + $bin), "User")
    Write-Host "Added $bin to your PATH (open a NEW terminal for it to take effect)." -ForegroundColor Green
} else { Write-Host "PATH already contains $bin" -ForegroundColor Green }
Write-Host "Done. In a new terminal, type:  praxis" -ForegroundColor Cyan
