"""Subprocess plumbing shared by the CLI-backed providers (subscription auth lives in the CLIs, not here)."""
import os
import re
import subprocess

from .router import ProviderError, RateLimited

_LIMIT = re.compile(r"(usage limit|rate.?limit|too many requests|\b429\b|quota|limit reached|"
                    r"out of credits|credit balance|overloaded)", re.I)


def run_cli(argv, stdin_text="", strip_env=(), timeout=300, cwd=None):
    """Run a CLI without a shell. `strip_env` removes API-key variables so the CLI uses the user's
    subscription login instead of silently billing an API key."""
    env = {k: v for k, v in os.environ.items() if k not in set(strip_env)}
    try:
        p = subprocess.run(argv, input=stdin_text, capture_output=True, text=True,
                           timeout=timeout, cwd=cwd, env=env, shell=False)
    except FileNotFoundError:
        raise ProviderError(f"{argv[0]}: not installed or not on PATH")
    except subprocess.TimeoutExpired:
        raise ProviderError(f"{argv[0]}: timed out after {timeout}s")
    if p.returncode != 0:
        msg = (p.stderr or p.stdout).strip()[-600:]
        raise (RateLimited if _LIMIT.search(msg) else ProviderError)(f"{argv[0]} exit {p.returncode}: {msg}")
    return p.stdout, p.stderr


def flatten(messages):
    """CLIs take one prompt: render system + conversation into a single text block."""
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    convo = "\n\n".join(f"[{m['role'].upper()}]\n{m['content']}" for m in messages if m["role"] != "system")
    return system, convo
