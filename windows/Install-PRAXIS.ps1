# PRAXIS guided setup for Windows.  Run:  powershell -ExecutionPolicy Bypass -File windows\Install-PRAXIS.ps1
# It only CHECKS your machine, optionally installs Python, and creates a Desktop shortcut. It never touches your accounts.
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot

function Say($msg, $color = "White") { Write-Host $msg -ForegroundColor $color }
function Have($name) { return [bool](Get-Command $name -ErrorAction SilentlyContinue) }

Say "`nPRAXIS setup" Cyan
Say "folder: $repo`n"

# 1. Python 3.11+ with Tk
$pyOk = $false
if (Have "py") {
    $v = & py -3 -c "import sys; print(int(sys.version_info >= (3, 11)))" 2>$null
    $tk = & py -3 -c "import tkinter; print(1)" 2>$null
    if ($v -eq "1" -and $tk -eq "1") { $pyOk = $true }
}
if ($pyOk) {
    Say "[ok]   Python 3.11+ with Tk" Green
} else {
    Say "[miss] Python 3.11+ with Tk" Yellow
    if (Have "winget") {
        $a = Read-Host "Install Python 3.12 with winget now? (y/N)"
        if ($a -eq "y") { winget install -e --id Python.Python.3.12; Say "Close this window and run this script again so PATH refreshes." Yellow; exit 0 }
    } else {
        Say "       Install from https://www.python.org/downloads/ (tick 'Add python.exe to PATH'), then re-run." Yellow
    }
}

# 1b. The interface opens in Microsoft Edge or Google Chrome (as a plain app window). Windows 10/11 already has Edge.
if ($pyOk) {
    $br = & py -3 -c "from praxis.ui import window; print(','.join(k for _, k in window.find_browsers()))" 2>$null
    if ($br) { Say "[ok]   Window for the interface ($br)" Green }
    else { Say "[miss] Edge or Chrome (PRAXIS will open in your default browser instead)" Yellow }
}

# 1c. Voice: speak to PRAXIS and it speaks back. Everything runs on this machine (no audio leaves it).
if ($pyOk) {
    $vo = & py -3 -c "import faster_whisper, piper, sounddevice; print(1)" 2>$null
    if ($vo -eq "1") {
        Say "[ok]   Voice (speech recogniser, voice, audio)" Green
    } else {
        Say "[miss] Voice (about 100 MB of Python packages, plus about 200 MB of models on first launch; without it you type your goals)" Yellow
        $a = Read-Host "Install the voice packages now with pip (for your user only)? (y/N)"
        if ($a -eq "y") {
            & py -3 -m pip install --user "faster-whisper>=1.0" "piper-tts>=1.2" "sounddevice>=0.4"
            $vo = & py -3 -c "import faster_whisper, piper, sounddevice; print(1)" 2>$null
            if ($vo -eq "1") { Say "[ok]   Voice installed" Green } else { Say "[warn] Install failed; PRAXIS will ask you to type goals." Yellow }
        }
    }
}

# 2. The AI tools (each is optional; PRAXIS uses whatever it finds)
$tools = @(
    @{ n = "claude";     d = "Claude subscription   (install: irm https://claude.ai/install.ps1 | iex   then run: claude)" },
    @{ n = "codex";      d = "ChatGPT / Codex       (see https://learn.chatgpt.com/docs/cli   then run: codex login)" },
    @{ n = "droid";      d = "Factory Droid         (see https://docs.factory.com/cli/getting-started/quickstart ; set FACTORY_API_KEY)" },
    @{ n = "devin";      d = "Devin CLI             (in Devin Desktop: Command Palette > Install Devin CLI ; then: devin auth login)" },
    @{ n = "ollama";     d = "Ollama (local models) (https://ollama.com/download/windows)" },
    @{ n = "docker";     d = "Docker Desktop        (OPTIONAL: lets PRAXIS run code in a proven sandbox)" },
    @{ n = "nvidia-smi"; d = "NVIDIA driver         (needed for GPU use; Ollama wants driver 551.61 or newer)" }
)
foreach ($t in $tools) {
    if (Have $t.n) { Say ("[ok]   " + $t.d) Green } else { Say ("[miss] " + $t.d) Yellow }
}

# 3. Desktop shortcut
if ($pyOk) {
    try {
        $pyw = (Get-Command pyw).Source
        $ws = New-Object -ComObject WScript.Shell
        $lnk = $ws.CreateShortcut((Join-Path ([Environment]::GetFolderPath("Desktop")) "PRAXIS.lnk"))
        $lnk.TargetPath = $pyw
        $lnk.Arguments = "-3 -m praxis.ui"
        $lnk.WorkingDirectory = $repo
        $lnk.Description = "PRAXIS"
        $lnk.Save()
        Say "`n[ok]   Desktop shortcut created: PRAXIS" Green
    } catch { Say "`n[warn] Could not create the shortcut ($_). Use windows\PRAXIS.bat instead." Yellow }

    Say "`nMachine check:" Cyan
    Push-Location $repo
    & py -3 -m praxis doctor
    Pop-Location
}
Say "`nNext: open the PRAXIS shortcut. First time, visit the Fuel page (add free keys so PRAXIS can use less Claude), then Models." Cyan
