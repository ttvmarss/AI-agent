"""One place that knows how to start a child process on Windows without a console window popping up.

PRAXIS normally runs windowless (pythonw). A windowless Python that starts a console program (claude, codex, droid, cmd, powershell, nvidia-smi,
taskkill...) makes Windows open a NEW visible terminal for each one; a goal that tries three models therefore opened a pile of terminals
(and closing one killed the call with exit 3221225786). Every child process in PRAXIS is started with these flags, and a test refuses a
launch that forgets."""
import subprocess
import sys

CREATE_NEW_PROCESS_GROUP = 0x00000200
DETACHED_PROCESS = 0x00000008
CREATE_NO_WINDOW = 0x08000000
IS_WINDOWS = sys.platform.startswith("win")


def hidden(group=False, detached=False):
    """Keyword arguments for subprocess.run/Popen: no console window on Windows; on other systems a new session when `group` (so the whole
    tree can be killed) or `detached` (so the child outlives us)."""
    if IS_WINDOWS:
        flags = CREATE_NO_WINDOW
        if group:
            flags |= CREATE_NEW_PROCESS_GROUP
        if detached:
            flags |= DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        kw = {"creationflags": flags}
        try:                                          # belt and braces for programs that ignore the flag
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0
            kw["startupinfo"] = si
        except AttributeError:
            pass
        return kw
    return {"start_new_session": True} if (group or detached) else {}


def run(argv, **kw):
    """subprocess.run with a hidden window."""
    for k, v in hidden(group=kw.pop("group", False)).items():
        kw.setdefault(k, v)
    return subprocess.run(argv, **kw)


def popen(argv, **kw):
    """subprocess.Popen with a hidden window."""
    for k, v in hidden(group=kw.pop("group", False), detached=kw.pop("detached", False)).items():
        kw.setdefault(k, v)
    return subprocess.Popen(argv, **kw)
