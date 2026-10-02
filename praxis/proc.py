"""Subprocess plumbing shared by the CLI-backed providers (subscription auth lives in the CLIs, not here)."""
import os
import re
import shutil
import subprocess
import sys
import threading

from .router import ModelUnavailable, ProviderError, RateLimited

_LIMIT = re.compile(r"(usage limit|rate.?limit|too many requests|\b429\b|quota|limit reached|"
                    r"out of credits|credit balance|overloaded)", re.I)


_UNAVAILABLE = re.compile(r"(unrecognized_model|unknown model|invalid model|"
                          r"model[^\n]{0,80}(not found|not available|unsupported|does not exist|not supported)|"
                          r"do(es)? not have access|not entitled)", re.I)


def classify(msg):
    return ModelUnavailable if _UNAVAILABLE.search(msg) else RateLimited if _LIMIT.search(msg) else ProviderError


_cancel = None


def set_cancel(event):
    """Register the event that aborts in-flight subprocesses (the desktop Stop button / kill switch)."""
    global _cancel
    _cancel = event


def _kill_tree(p):
    try:
        if sys.platform.startswith("win"):
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True, timeout=10)
        else:
            import signal
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)
    except Exception:
        try:
            p.kill()
        except Exception:
            pass


def run_cli(argv, stdin_text="", strip_env=(), timeout=300, cwd=None):
    """Run a CLI without a shell. `strip_env` removes API-key variables so the CLI uses the user's
    subscription login instead of silently billing an API key. Cancellable; kills the whole process tree."""
    env = {k: v for k, v in os.environ.items() if k not in set(strip_env)}
    exe = shutil.which(argv[0], path=env.get("PATH")) or argv[0]  # resolves claude.cmd / codex.cmd shims on Windows
    kw = {"creationflags": 0x00000200} if sys.platform.startswith("win") else {"start_new_session": True}
    try:
        p = subprocess.Popen([exe] + list(argv[1:]), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, cwd=cwd, env=env, shell=False, **kw)
    except FileNotFoundError:
        raise ProviderError(f"{argv[0]}: not installed or not on PATH")
    deadline = threading.Event()
    out = err = ""
    pending = stdin_text
    t_end = None if timeout is None else __import__("time").time() + timeout
    while True:
        try:
            out, err = p.communicate(input=pending, timeout=0.25)
            break
        except subprocess.TimeoutExpired:
            pending = None  # stdin already delivered on the first call
            if _cancel is not None and _cancel.is_set():
                _kill_tree(p)
                p.communicate()
                raise ProviderError(f"{argv[0]}: cancelled")
            if t_end is not None and __import__("time").time() > t_end:
                _kill_tree(p)
                p.communicate()
                raise ProviderError(f"{argv[0]}: timed out after {timeout}s")
    if p.returncode != 0:
        msg = (err or out).strip()[-600:]
        raise classify(msg)(f"{argv[0]} exit {p.returncode}: {msg}")
    return out, err


def flatten(messages):
    """CLIs take one prompt: render system + conversation into a single text block."""
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    convo = "\n\n".join(f"[{m['role'].upper()}]\n{m['content']}" for m in messages if m["role"] != "system")
    return system, convo
