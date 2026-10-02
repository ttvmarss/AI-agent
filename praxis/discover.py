"""Finds AI tools that are installed but not on PATH, so a desktop install is enough (Devin Desktop, Factory Desktop).

Only well-known install locations are looked at, nothing is ever executed from a folder PRAXIS merely guessed at without a check:
a candidate for the Devin CLI must answer `--help` with the non-interactive flag (`--print`), so that the Devin Desktop *editor
launcher* (which opens a window) can never be mistaken for the command-line agent."""
from . import cache
import os
import shutil
import subprocess
import sys

WIN = sys.platform.startswith("win")
EXE = ("", ".exe", ".cmd", ".bat")                     # the same list everywhere: a Windows install tree can be inspected from any OS


def _env(env, key, default=""):
    return (env or os.environ).get(key, default) or default


def candidates(name, env=None, isdir=os.path.isdir, listdir=os.listdir, walk=os.walk):
    """Likely paths for the executable `name` (devin | droid), most specific first."""
    local, prof, home = _env(env, "LOCALAPPDATA"), _env(env, "USERPROFILE"), os.path.expanduser("~")
    roots, direct = [], []
    if name == "devin":
        direct += [os.path.join(local, "Programs", "Devin", "bin", "devin"), os.path.join(local, "Programs", "Devin", "resources", "app", "bin", "devin"),
                   os.path.join(local, "devin", "cli", "bin", "devin"),            # where the official installer puts it (seen on a real install)
                   os.path.join(local, "devin", "bin", "devin"), os.path.join(local, "Devin", "bin", "devin"),
                   os.path.join(prof, ".devin", "bin", "devin"), os.path.join(home, ".devin", "bin", "devin"),
                   os.path.join(home, ".local", "bin", "devin")]
        roots += [os.path.join(local, "Programs", "Devin"), os.path.join(local, "devin")]
    elif name == "droid":
        direct += [os.path.join(prof, "bin", "droid"), os.path.join(prof, ".factory", "bin", "droid"), os.path.join(local, "Factory", "bin", "droid"),
                   os.path.join(home, ".local", "bin", "droid"), os.path.join(home, ".factory", "bin", "droid")]
        roots += [os.path.join(local, "Factory")]
    direct = [d for d in direct if os.path.isabs(d)]       # an unset LOCALAPPDATA / USERPROFILE must not turn into a path relative to the cwd
    roots = [r for r in roots if os.path.isabs(r)]
    out = [d + e for d in direct for e in EXE]
    for root in roots:                                   # a shallow look (depth 4) for the CLI binary beside the desktop app
        if not root or not isdir(root):
            continue
        base_depth = root.rstrip("\\/").count(os.sep)
        for dirpath, dirs, files in walk(root):
            if dirpath.count(os.sep) - base_depth >= 4:
                dirs[:] = []
                continue
            for f in files:
                stem, ext = os.path.splitext(f)
                if stem.lower() == name and ext.lower() in EXE and os.path.join(dirpath, f) not in out:
                    if dirpath.rstrip("\\/") == root.rstrip("\\/") and ext.lower() == ".exe" and name == "devin":
                        continue                         # Devin.exe in the install root is the DESKTOP APP, not the CLI
                    out.append(os.path.join(dirpath, f))
    return out


def looks_like_devin_cli(path, run=None, timeout=20):
    """True only if the program documents `--print`: the command-line agent, not the editor launcher."""
    run_is_default = run is None
    run = run or (lambda argv: subprocess.run(argv, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace",
                                              stdin=subprocess.DEVNULL))
    def ask():
        try:
            r = run([path, "--help"])
            return "--print" in ((r.stdout or "") + (r.stderr or ""))
        except Exception:
            return None                                   # not cached: try again next time
    try:
        st = os.stat(path)
        stamp = f"{st.st_mtime:.0f}:{st.st_size}"         # a new version of the program is checked afresh
    except OSError:
        return bool(ask())
    return bool(cache.get("devin_cli:" + path, ask, ttl_s=90 * 86400, stamp=stamp) if run_is_default else ask())


def find(name, env=None, exists=os.path.isfile, verify=None, **kw):
    """The path of `name` if it is on PATH or in a known install folder (and, for devin, really is the CLI); else None."""
    on_path = shutil.which(name, path=(env or os.environ).get("PATH"))
    if on_path and (name != "devin" or (verify or looks_like_devin_cli)(on_path)):
        return on_path
    for c in candidates(name, env, **kw):
        if exists(c) and (name != "devin" or (verify or looks_like_devin_cli)(c)):
            return c
    return None


def ensure_on_path(names=("devin", "droid"), env=None, **kw):
    """Make the found tools runnable by name for this process (adds their folders to PATH). -> {name: path or None}"""
    found = {}
    for n in names:
        p = find(n, env, **kw)
        found[n] = p
        target = env if env is not None else os.environ
        if p and shutil.which(n, path=target.get("PATH")) != p:            # also when a different `devin` (the editor launcher) is first on PATH
            target["PATH"] = os.path.dirname(p) + os.pathsep + target.get("PATH", "")
    return found
