"""OS-level containment for code execution (the real control; command allowlists are not).

A backend is only ever called *strong* if `selftest()` actually attacks it and every attack fails:
  - writing a file inside the workspace must SUCCEED,
  - writing a file outside the workspace must FAIL,
  - opening a network connection must FAIL,
  - overwriting/deleting the workspace's .praxis/ state (event log, checkpoints, registry) must FAIL.
Backends (first that passes wins): bwrap (Linux), unshare (Linux, rootless user namespaces), docker.
No strong backend => the Guard classes code execution as Class 4 (human approval each time).
"""
import os
import shlex
import shutil
import subprocess

from . import winproc
import sys
import tempfile

_UNSHARE_SCRIPT = r'''set -e
WS="$1"; shift
mount --make-rprivate /
mount -o remount,ro,bind / /
mount --bind "$WS" "$WS"
mount -o remount,rw,bind "$WS"
cd "$WS"
mkdir -p "$WS/.praxis"
mount -t tmpfs tmpfs "$WS/.praxis"   # real PRAXIS state is invisible and unwritable to executed code
mkdir -p "$WS/.praxis/tmp"
export TMPDIR="$WS/.praxis/tmp" HOME="$WS/.praxis/tmp"
exec "$@"
'''


class Sandbox:
    kind = "none"
    strong = False

    def wrap(self, argv, ws):
        return argv


class UnshareSandbox(Sandbox):
    kind = "unshare"

    def wrap(self, argv, ws):
        return ["unshare", "--user", "--map-root-user", "--mount", "--net", "--pid", "--fork", "--kill-child",
                "sh", "-c", _UNSHARE_SCRIPT, "sbx", ws] + list(argv)


class BwrapSandbox(Sandbox):
    kind = "bwrap"

    def wrap(self, argv, ws):
        return ["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp",
                "--bind", ws, ws, "--tmpfs", f"{ws}/.praxis", "--unshare-net", "--unshare-pid", "--die-with-parent", "--chdir", ws,
                "--setenv", "TMPDIR", "/tmp", "--setenv", "HOME", "/tmp"] + list(argv)


class DockerSandbox(Sandbox):
    kind = "docker"

    def __init__(self, image="python:3.11-slim"):
        self.image = image

    def wrap(self, argv, ws):
        uid, gid = (os.getuid(), os.getgid()) if hasattr(os, "getuid") else (1000, 1000)
        return ["docker", "run", "--rm", "--network", "none", "--read-only", "--tmpfs", "/tmp",
                "-v", f"{ws}:/work", "--tmpfs", "/work/.praxis", "-w", "/work", "--memory", "2g", "--pids-limit", "256",
                "--user", f"{uid}:{gid}", "-e", "HOME=/tmp", self.image] + list(argv)


_NET_PROBE = ("import socket,sys\n"
              "try:\n socket.create_connection(('1.1.1.1',53),timeout=2); print('NET_OPEN')\n"
              "except Exception:\n print('NET_BLOCKED')\n")


def selftest(sb, python=None):
    """Attack the sandbox. Returns (ok, details). Never trust a backend that was not attacked."""
    py = python or ("python3" if sb.kind == "docker" else sys.executable)
    base = os.path.realpath(tempfile.mkdtemp(prefix="praxis-sbx-"))
    ws, outside = os.path.join(base, "ws"), os.path.join(base, "outside")
    os.makedirs(ws); os.makedirs(outside)
    details = {}

    def run(code):
        try:
            p = winproc.run(sb.wrap([py, "-c", code], ws), capture_output=True, text=True, timeout=90, cwd=ws)
            return p.stdout.strip()
        except Exception as e:
            return f"ERR {type(e).__name__}"
    try:
        run("open('inside.txt','w').write('x')")
        details["inside_write"] = os.path.exists(os.path.join(ws, "inside.txt"))
        run(f"open({os.path.join(outside, 'pwn.txt')!r},'w').write('x')")
        details["outside_write_blocked"] = not os.path.exists(os.path.join(outside, "pwn.txt"))
        details["network_blocked"] = run(_NET_PROBE) == "NET_BLOCKED"
        state = os.path.join(ws, ".praxis"); os.makedirs(state, exist_ok=True)
        with open(os.path.join(state, "events.db"), "w") as f:
            f.write("REAL")
        run("import os\ntry: open('.praxis/events.db','w').write('TAMPERED')\nexcept OSError: pass\n"
            "try: os.remove('.praxis/events.db')\nexcept OSError: pass\n")
        try:
            with open(os.path.join(state, "events.db")) as f:
                details["praxis_state_protected"] = f.read() == "REAL"
        except OSError:  # deleted by the attack => NOT protected (a verdict, never a crash)
            details["praxis_state_protected"] = False
    finally:
        shutil.rmtree(base, ignore_errors=True)
    return all(details.values()), details


def detect(prefer=("bwrap", "unshare", "docker"), log=None):
    """First backend that exists AND survives its own self-attack. Returns Sandbox() (kind none) if none."""
    cands = {"bwrap": (BwrapSandbox, "bwrap"), "unshare": (UnshareSandbox, "unshare"), "docker": (DockerSandbox, "docker")}
    for name in prefer:
        cls, binary = cands[name]
        linux_only = name in ("bwrap", "unshare")
        if not shutil.which(binary) or (linux_only and not sys.platform.startswith("linux")):
            continue
        sb = cls()
        try:
            ok, details = selftest(sb)
        except Exception as e:  # a sandbox we cannot even test is a sandbox we do not trust
            ok, details = False, {"selftest_crashed": f"{type(e).__name__}: {e}"}
        if log:
            log(f"sandbox {name}: {'PASS' if ok else 'FAIL'} {details}")
        if ok:
            sb.strong = True
            return sb
    return Sandbox()
