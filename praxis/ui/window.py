"""Open PRAXIS as its own window: a Chromium-based browser (Edge ships with Windows 10/11; Chrome and Brave also work) in app mode, which is a
frameless window with no tabs or address bar, on a private profile so it is a separate process we can watch. Nothing to install."""
import os
import shutil
import sys
import webbrowser

from .. import paths, winproc

IS_WINDOWS = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"

WIN_PATHS = [
    (r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe", "edge"), (r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe", "edge"),
    (r"%ProgramFiles%\Google\Chrome\Application\chrome.exe", "chrome"), (r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe", "chrome"),
    (r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe", "chrome"),
    (r"%ProgramFiles%\BraveSoftware\Brave-Browser\Application\brave.exe", "brave"), (r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe", "brave"),
]
APP_PATH_KEYS = (("msedge.exe", "edge"), ("chrome.exe", "chrome"), ("brave.exe", "brave"))
MAC_PATHS = [("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge", "edge"), ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "chrome"),
             ("/Applications/Brave Browser.app/Contents/MacOS/Brave Browser", "brave")]
POSIX_NAMES = [("microsoft-edge", "edge"), ("microsoft-edge-stable", "edge"), ("google-chrome", "chrome"), ("google-chrome-stable", "chrome"), ("chromium", "chrome"),
               ("chromium-browser", "chrome"), ("brave-browser", "brave")]


def _registry_path(exe, winreg=None):
    try:
        import winreg as wr
        wr = winreg or wr
        for hive in (wr.HKEY_LOCAL_MACHINE, wr.HKEY_CURRENT_USER):
            try:
                with wr.OpenKey(hive, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe}") as k:
                    p = wr.QueryValueEx(k, None)[0]
                    if p:
                        return str(p).strip('"')
            except OSError:
                continue
    except Exception:
        pass
    return ""


def find_browsers(exists=os.path.isfile, which=shutil.which, environ=None, winreg=None):
    """-> [(path, kind)] of installed Chromium-based browsers, best first. Never raises."""
    env = environ if environ is not None else os.environ
    out = []
    def add(p, kind):
        if p and exists(p) and all(p != q for q, _ in out):
            out.append((p, kind))
    if IS_WINDOWS:
        for exe, kind in APP_PATH_KEYS:
            add(_registry_path(exe, winreg), kind)
        for tmpl, kind in WIN_PATHS:
            p = tmpl
            for var in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
                p = p.replace(f"%{var}%", env.get(var, ""))
            add(p, kind)
    elif IS_MAC:
        for p, kind in MAC_PATHS:
            add(p, kind)
    for name, kind in POSIX_NAMES:
        add(which(name) or "", kind)
    order = {"edge": 0, "chrome": 1, "brave": 2}
    return sorted(out, key=lambda t: order.get(t[1], 9))


def command(browser, url, profile, size=(1500, 940)):
    return [browser, f"--app={url}", f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check", f"--window-size={size[0]},{size[1]}",
            "--disable-features=Translate,msEdgeSidebarV2,HubsSidebar,msEdgeMouseGestureDefault", "--disable-session-crashed-bubble", "--hide-crash-restore-bubble",
            "--disable-infobars", "--ignore-gpu-blocklist", "--enable-gpu-rasterization", "--autoplay-policy=no-user-gesture-required", "--disable-background-networking"]


def open_window(url, browsers=None, popen=winproc.popen, open_default=webbrowser.open, out=print):
    """Open `url` as an app window. -> the browser process (to watch), or None when the default browser had to be used instead."""
    for exe, kind in (browsers if browsers is not None else find_browsers()):
        profile = os.path.join(paths.home(), "ui-profile")
        try:
            os.makedirs(profile, exist_ok=True)
            return popen(command(exe, url, profile))
        except OSError as e:
            out(f"could not start {kind}: {e}")
    out("No Chromium-based browser (Edge, Chrome, Brave) was found, so PRAXIS is opening in your default browser instead.")
    try:
        open_default(url)
    except Exception as e:
        out(f"Could not open a browser: {e}. Open this address yourself: {url}")
    return None
