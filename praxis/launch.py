"""Open the desktop app from a terminal and give the terminal back: `praxis` (or `praxis app`) starts the window detached, so closing the
terminal does not close PRAXIS and there is no console window behind it on Windows."""
import os
import subprocess
import sys

from . import build

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def windowless_python(exe=None):
    """pythonw.exe beside the running python on Windows (no console), else the running python itself."""
    exe = exe or sys.executable
    if sys.platform.startswith("win"):
        w = os.path.join(os.path.dirname(exe), "pythonw.exe")
        if os.path.isfile(w):
            return w
    return exe


def command(args=(), exe=None):
    return [windowless_python(exe), "-m", "praxis.desktop", *args]


def start(args=(), popen=subprocess.Popen, out=print):
    """Start the app detached. -> the child's pid, or None if it could not be started."""
    env = dict(os.environ)
    env["PYTHONPATH"] = ROOT + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")     # `-m praxis.desktop` finds this checkout from anywhere
    kw = {"creationflags": 0x00000008 | 0x00000200 | 0x08000000} if sys.platform.startswith("win") else {"start_new_session": True}
    try:
        p = popen(command(args), cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)
    except OSError as e:
        out(f"PRAXIS could not start: {e}")
        return None
    out(f"PRAXIS is opening   build {build.label()}")
    return getattr(p, "pid", 0)


def is_launch_request(argv):
    """`praxis` with nothing else, or `praxis app|ui|desktop [workspace]`."""
    return not argv or argv[0] in ("app", "ui", "desktop")
