"""Opening things on the user's computer: a website, an application, a file or folder in the workspace.

Three separate jobs, so each can be checked on its own:
  resolve()   what does the user mean?  ("google chrome", "youtube", "https://x.org", "notes.txt")  -> an Action
  classify()  how risky is it?  (Class for the Guard: known apps and known sites are Class 2, any other website Class 3, anything that
              could execute code, an unknown program or a path outside the workspace Class 4)
  Launcher    start it (ShellExecute on Windows, `open`/`xdg-open`/the program elsewhere), and Processes: is it really running now?
PRAXIS never claims it opened something: the plan verifies that the program's process exists (`process_running`)."""
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse

from . import winproc

IS_WINDOWS = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"

EXECUTABLE_EXT = {".exe", ".bat", ".cmd", ".com", ".msi", ".ps1", ".psm1", ".vbs", ".vbe", ".js", ".jse", ".wsf", ".wsh", ".scr", ".lnk", ".url",
                  ".hta", ".jar", ".reg", ".dll", ".cpl", ".sh", ".command", ".app", ".appimage", ".py", ".pyw"}


@dataclass
class App:
    key: str
    label: str
    win: str                    # what ShellExecute is given on Windows (an App Paths name, or a URI)
    procs_win: tuple            # process names that prove it is running
    posix: tuple = ()           # program names to look for elsewhere
    mac: str = ""               # `open -a` name
    aliases: tuple = ()


APPS = [
    App("chrome", "Google Chrome", "chrome.exe", ("chrome.exe",), ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"), "Google Chrome",
        ("google chrome", "chrome", "google")),
    App("edge", "Microsoft Edge", "msedge.exe", ("msedge.exe",), ("microsoft-edge", "microsoft-edge-stable"), "Microsoft Edge", ("microsoft edge", "edge")),
    App("firefox", "Firefox", "firefox.exe", ("firefox.exe",), ("firefox",), "Firefox", ("mozilla firefox", "firefox")),
    App("brave", "Brave", "brave.exe", ("brave.exe",), ("brave-browser", "brave"), "Brave Browser", ("brave browser", "brave")),
    App("notepad", "Notepad", "notepad.exe", ("notepad.exe",), ("gedit", "kate", "mousepad"), "TextEdit", ("notepad", "text editor")),
    App("calculator", "Calculator", "calc.exe", ("calculatorapp.exe", "calculator.exe", "calc.exe", "win32calc.exe"), ("gnome-calculator", "kcalc", "galculator"),
        "Calculator", ("calculator", "calc")),
    App("paint", "Paint", "mspaint.exe", ("mspaint.exe",), ("kolourpaint", "pinta"), "", ("paint", "ms paint", "mspaint")),
    App("taskmgr", "Task Manager", "taskmgr.exe", ("taskmgr.exe",), (), "Activity Monitor", ("task manager", "activity monitor")),
    App("vscode", "Visual Studio Code", "Code.exe", ("code.exe",), ("code", "codium"), "Visual Studio Code", ("vs code", "vscode", "visual studio code", "code editor")),
    App("word", "Microsoft Word", "WINWORD.EXE", ("winword.exe",), ("libreoffice --writer",), "Microsoft Word", ("microsoft word", "word")),
    App("excel", "Microsoft Excel", "EXCEL.EXE", ("excel.exe",), (), "Microsoft Excel", ("microsoft excel", "excel")),
    App("powerpoint", "Microsoft PowerPoint", "POWERPNT.EXE", ("powerpnt.exe",), (), "Microsoft PowerPoint", ("microsoft powerpoint", "powerpoint")),
    App("outlook", "Microsoft Outlook", "OUTLOOK.EXE", ("outlook.exe", "olk.exe"), (), "Microsoft Outlook", ("microsoft outlook", "outlook")),
    App("spotify", "Spotify", "spotify:", ("spotify.exe",), ("spotify",), "Spotify", ("spotify",)),
    App("settings", "Settings", "ms-settings:", ("systemsettings.exe",), ("gnome-control-center",), "System Settings", ("settings", "windows settings", "system settings")),
]
BY_ALIAS = {a: app for app in APPS for a in (app.key, *app.aliases)}

SITES = {"youtube": "https://www.youtube.com", "google": "https://www.google.com", "gmail": "https://mail.google.com", "github": "https://github.com",
         "reddit": "https://www.reddit.com", "twitter": "https://x.com", "x": "https://x.com", "netflix": "https://www.netflix.com",
         "amazon": "https://www.amazon.com", "wikipedia": "https://www.wikipedia.org", "chatgpt": "https://chatgpt.com", "claude": "https://claude.ai",
         "google drive": "https://drive.google.com", "google maps": "https://maps.google.com", "maps": "https://maps.google.com",
         "stack overflow": "https://stackoverflow.com", "linkedin": "https://www.linkedin.com", "twitch": "https://www.twitch.tv",
         "spotify web": "https://open.spotify.com", "calendar": "https://calendar.google.com", "google calendar": "https://calendar.google.com"}
# Chrome is a browser AND a site-less name; "google" alone means the website, "google chrome" the app (aliases above keep both apart).
BY_ALIAS.pop("google", None)

FILE_EXT = EXECUTABLE_EXT | {".txt", ".md", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".csv", ".json", ".xml", ".png", ".jpg", ".jpeg", ".gif",
                             ".zip", ".rar", ".7z", ".log", ".ini", ".cfg", ".toml", ".yml", ".yaml", ".html", ".htm", ".css", ".ts", ".tsx", ".c", ".cpp", ".h",
                             ".java", ".rs", ".go", ".mp3", ".mp4", ".wav", ".mov", ".svg"}
DOMAIN = re.compile(r"^(?:https?://)?(?:[a-z0-9-]+\.)+[a-z]{2,}(?::\d+)?(?:/[^\s]*)?$", re.I)
BAD_NAME = re.compile(r"[;&|<>`$\\(){}*?~\n\r\"']")
BROWSER_BY_PROGID = (("chromehtml", "chrome.exe"), ("msedgehtm", "msedge.exe"), ("firefoxurl", "firefox.exe"), ("bravehtml", "brave.exe"),
                     ("opera", "opera.exe"), ("vivaldi", "vivaldi.exe"))


@dataclass
class Action:
    kind: str                 # "app" | "site" | "url" | "path" | "unknown"
    label: str
    target: str               # what to launch: ShellExecute name / URL / absolute path
    procs: tuple = ()         # process names that will prove it ran
    cls: int = 4
    why: str = ""
    app: object = None
    extra: dict = field(default_factory=dict)


def _clean(text):
    t = re.sub(r"\s+", " ", str(text or "").strip().lower())
    t = re.sub(r"^(?:the|my|a|an)\s+", "", t)
    t = re.sub(r"\s+(?:app|application|program|browser|website|web site|site|page)$", "", t)
    return t.strip(" .,!?")


def default_browser(winreg=None):
    """The process name of the user's default browser. Windows reads the registry; elsewhere a sensible guess. Never raises."""
    if IS_WINDOWS:
        try:
            import winreg as wr
            wr = winreg or wr
            with wr.OpenKey(wr.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice") as k:
                prog = str(wr.QueryValueEx(k, "ProgId")[0]).lower()
            for needle, exe in BROWSER_BY_PROGID:
                if needle in prog:
                    return exe
        except Exception:
            pass
        return "msedge.exe"
    for exe in ("firefox", "google-chrome", "chromium", "chrome"):
        if shutil.which(exe):
            return exe
    return "firefox"


def resolve(target, workspace=None, browser=None):
    """-> Action. Never raises; an unrecognised target is kind "unknown" (Class 4: a human decides)."""
    raw = str(target or "").strip()
    if not raw or len(raw) > 2000 or BAD_NAME.search(raw.replace("'", "").replace("\"", "")) and "://" not in raw:
        return Action("unknown", raw[:80], raw, cls=4, why="empty, or contains characters that could chain commands or script a page")
    low = raw.lower()
    # 1. an explicit URL
    if "://" in raw or low.startswith(("mailto:", "tel:")):
        u = urlparse(raw)
        if u.scheme in ("http", "https") and u.hostname and not u.username:
            return Action("url", u.hostname, raw, (browser or default_browser(),), 3, "a website that is not on the known list: you decide")
        why = "this link carries a password, which is how phishing links look" if u.scheme in ("http", "https") else f"'{u.scheme}:' links can run code or leave the browser"
        return Action("unknown", raw[:80], raw, cls=4, why=why)
    # 2. a known application
    key = _clean(raw)
    app = BY_ALIAS.get(key)
    if app is not None:
        procs = app.procs_win if IS_WINDOWS else tuple(dict.fromkeys(Path_name(p) for p in (app.posix or (app.key,))))
        return Action("app", app.label, app.win if IS_WINDOWS else (app.mac if IS_MAC else ""), procs, 2, "a known application", app)
    # 3. a file or folder inside the workspace (before domains: "notes.txt" looks like a web address)
    if workspace:
        full = os.path.realpath(os.path.join(workspace, raw))
        real_ws = os.path.realpath(workspace)
        inside = full == real_ws or full.startswith(real_ws + os.sep)
        if os.path.exists(full):
            ext = os.path.splitext(full)[1].lower()
            rel = os.path.relpath(full, real_ws).split(os.sep)[0].lower()
            if not inside or rel in (".praxis", ".git"):
                return Action("path", raw, full, cls=4, why="outside the workspace, or PRAXIS's own state")
            if ext in EXECUTABLE_EXT:
                return Action("path", os.path.basename(full), full, cls=4, why=f"a {ext} file can run code")
            return Action("path", os.path.basename(full), full, cls=2, why="a document in the workspace")
    # 4. a known site, or something that looks like a domain
    if key in SITES:
        return Action("site", key, SITES[key], (browser or default_browser(),), 2, "a well-known website")
    if DOMAIN.match(raw) and " " not in raw and os.path.splitext(raw.split("/")[0])[1].lower() not in FILE_EXT:
        url = raw if "://" in raw else "https://" + raw
        return Action("url", urlparse(url).hostname or raw, url, (browser or default_browser(),), 3, "a website that is not on the known list: you decide")
    return Action("unknown", raw[:80], raw, cls=4, why="not a program or site PRAXIS knows")


def Path_name(p):
    return os.path.basename(p.split()[0]).lower()


def classify(target, workspace=None):
    return resolve(target, workspace).cls


class Launcher:
    """Starts things. Replaceable in tests."""

    def __init__(self, startfile=None, popen=winproc.popen, which=shutil.which):
        self._startfile = startfile
        self.popen, self.which = popen, which

    def start(self, action):
        if action.kind == "unknown":
            raise OSError(f"don't know how to open {action.label!r}")
        if IS_WINDOWS:
            sf = self._startfile or getattr(os, "startfile")
            sf(action.target)                                     # ShellExecute: App Paths, URIs, default handlers; no console is created
            return
        if action.kind == "app":
            if IS_MAC and action.app is not None and action.app.mac:
                self.popen(["open", "-a", action.app.mac], stdout=winproc.subprocess.DEVNULL, stderr=winproc.subprocess.DEVNULL, detached=True)
                return
            for name in (action.app.posix if action.app else ()):
                exe = self.which(name.split()[0])
                if exe:
                    self.popen([exe] + name.split()[1:], stdout=winproc.subprocess.DEVNULL, stderr=winproc.subprocess.DEVNULL, detached=True)
                    return
            raise OSError(f"{action.label} is not installed")
        opener = "open" if IS_MAC else "xdg-open"
        exe = self.which(opener)
        if not exe:
            raise OSError(f"no way to open {action.label} here ({opener} not found)")
        self.popen([exe, action.target], stdout=winproc.subprocess.DEVNULL, stderr=winproc.subprocess.DEVNULL, detached=True)


class Processes:
    """Is a program running? Windows: tasklist; elsewhere: ps. `clock`/`sleep` are injectable so polling is testable."""

    def __init__(self, lister=None, sleep=time.sleep, clock=time.monotonic):
        self._lister, self.sleep, self.clock = lister, sleep, clock

    def names(self):
        if self._lister is not None:
            return {n.lower() for n in self._lister()}
        out = set()
        try:
            if IS_WINDOWS:
                r = winproc.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, timeout=15, encoding="utf-8", errors="replace")
                for line in r.stdout.splitlines():
                    if line.startswith('"'):
                        out.add(line.split('","')[0].strip('"').lower())
            else:
                r = winproc.run(["ps", "-A", "-o", "comm="], capture_output=True, text=True, timeout=15)
                out = {os.path.basename(l.strip()).lower() for l in r.stdout.splitlines() if l.strip()}
        except Exception:
            pass
        return out

    def running(self, name, wait=0.0, every=0.5):
        """True as soon as a process called `name` exists (".exe" optional, Linux's 15-character truncation tolerated); polls up to `wait` seconds."""
        want = os.path.basename(str(name or "")).lower()
        if not want:
            return False
        bare = want[:-4] if want.endswith(".exe") else want
        end = self.clock() + max(0.0, wait)
        while True:
            for n in self.names():
                nb = n[:-4] if n.endswith(".exe") else n
                if nb == bare or (len(nb) >= 12 and bare.startswith(nb)):
                    return True
            if self.clock() >= end:
                return False
            self.sleep(every)


class Opener:
    """What the tool runtime and the verifier share."""

    def __init__(self, workspace, launcher=None, processes=None):
        self.workspace = workspace
        self.launcher = launcher or Launcher()
        self.processes = processes or Processes()

    def resolve(self, target):
        return resolve(target, self.workspace)

    def open(self, target):
        a = self.resolve(target)
        self.launcher.start(a)
        return {"opened": a.label, "kind": a.kind, "processes": list(a.procs)}

    def describe(self):
        """The line the planner is given about this computer."""
        names = ", ".join(sorted({a.aliases[0] if a.aliases else a.key for a in APPS}))
        return (f"desktop.open{{target}} opens, on the user's computer, a website (an https URL or a known site such as youtube), an application by name ({names}) "
                f"or a file or folder inside the workspace. Verify it with process_running{{name}} (the program's process, e.g. chrome.exe or notepad.exe; "
                f"a website opens in the default browser, which is {default_browser()}). Use desktop.open, never shell.run, to open things.")
