"""Capability Guard: deterministic, fail-closed permission enforcement.

Security is enforced here, in code, never by asking a model to behave.
Classes (docs §19): 0 observe · 1 safe local · 2 project edit · 3 external ·
4 financial/security/sensitive/unknown · 5 destructive/irreversible.
"""
import os
import re
import shlex
from dataclasses import dataclass

ALLOW, DENY, ESCALATE = "ALLOW", "DENY", "ESCALATE"
MAX_AUTO_CLASS_CAP = 2  # autonomy can never be granted above Class 2

_META = re.compile(r"[;&|<>`$\n\r\\(){}*?~]")
_READ_ONLY = {"ls", "cat", "head", "tail", "wc", "grep", "pwd", "echo", "diff", "stat", "file"}
_GIT_READ = {"status", "diff", "log", "show", "branch", "rev-parse", "ls-files"}
_TEST_RUNNERS = (["python3", "-m", "unittest"], ["python", "-m", "unittest"],
                 ["python3", "-m", "pytest"], ["python", "-m", "pytest"], ["pytest"])
_DESTRUCTIVE = {"rm", "rmdir", "dd", "shred", "truncate", "mkfs", "mv", "kill", "killall", "chmod", "chown"}
_NETWORK = {"curl", "wget", "ssh", "scp", "nc", "ncat", "telnet", "ftp", "rsync", "pip", "pip3", "npm"}


def _inside(path, ws):
    real_ws = os.path.realpath(ws)
    real = os.path.realpath(os.path.join(real_ws, path))
    return real == real_ws or real.startswith(real_ws + os.sep)


def classify_shell(cmd, ws):
    if not isinstance(cmd, str) or not cmd.strip():
        return 4
    if _META.search(cmd):
        return 4  # pipes, redirects, substitution, chaining, globbing: not analyzable -> fail closed
    try:
        argv = shlex.split(cmd)
    except ValueError:
        return 4
    if not argv:
        return 4
    prog = os.path.basename(argv[0])
    if prog != argv[0]:
        return 4  # explicit paths to binaries are not trusted
    args = argv[1:]
    if prog.startswith("mkfs"):
        return 5
    if prog in _DESTRUCTIVE:
        return 5
    if prog == "git":
        sub = next((a for a in args if not a.startswith("-")), "")
        if sub == "push":
            return 5 if any(a in ("--force", "-f", "--force-with-lease") or a.startswith("--force") for a in args) else 3
        if sub in ("reset", "clean", "checkout", "rebase", "filter-branch", "gc", "prune") or sub == "branch" and "-D" in args:
            return 5
        if sub in ("fetch", "pull", "clone", "remote"):
            return 3
        if sub in _GIT_READ and not any(a.startswith("--output") for a in args):
            return 0 if _paths_ok(args, ws) else 4
        return 4
    if prog in _NETWORK:
        return 3
    for runner in _TEST_RUNNERS:
        if argv[:len(runner)] == runner:
            return 2 if _paths_ok(argv[len(runner):], ws) else 4
    if prog in _READ_ONLY:
        return 0 if _paths_ok(args, ws) else 4
    return 4  # unknown program: fail closed


def _paths_ok(args, ws):
    for a in args:
        if a.startswith("-"):
            continue
        looks_like_path = a.startswith(("/", ".", "~")) or os.sep in a or os.path.exists(os.path.join(ws, a))
        if looks_like_path and not _inside(a, ws):
            return False
    return True


def classify_call(tool, args, ws):
    if tool == "fs.read" or tool == "fs.list":
        return 0 if _inside(args.get("path", "."), ws) else 4
    if tool == "fs.write":
        return 2 if _inside(args.get("path", ""), ws) and args.get("path") else 4
    if tool == "shell.run":
        return classify_shell(args.get("cmd"), ws)
    return 4  # unknown tool: fail closed


@dataclass
class Decision:
    tool: str
    args: dict
    cls: int
    verdict: str
    reason: str
    requires_checkpoint: bool = False
    tainted: bool = False


class Guard:
    def __init__(self, workspace, max_auto_class=2):
        if max_auto_class > MAX_AUTO_CLASS_CAP:
            raise ValueError(f"max_auto_class cannot exceed {MAX_AUTO_CLASS_CAP}")
        self.ws = workspace
        self.max_auto_class = max_auto_class

    def decide(self, tool, args, tainted=False):
        cls = classify_call(tool, args, self.ws)
        ckpt = cls >= 1
        if tainted and cls > 0:
            return Decision(tool, args, cls, DENY,
                            "step derived from untrusted content may only observe (Class 0)", ckpt, True)
        if cls <= self.max_auto_class:
            return Decision(tool, args, cls, ALLOW, f"Class {cls} within grant", ckpt, tainted)
        return Decision(tool, args, cls, ESCALATE, f"Class {cls} exceeds auto grant {self.max_auto_class}",
                        True, tainted)

    def authorize(self, decision, approver=None):
        """Resolve ESCALATE via an explicit human approver. Tainted denials are final."""
        if decision.verdict != ESCALATE:
            return decision.verdict
        if decision.tainted or approver is None:
            return DENY
        return ALLOW if approver(decision) else DENY
