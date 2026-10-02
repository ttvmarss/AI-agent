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
_INTERPRETERS = {"python3": ".py", "python": ".py", "node": ".js"}
_DESTRUCTIVE = {"rm", "rmdir", "dd", "shred", "truncate", "mkfs", "mv", "kill", "killall", "chmod", "chown"}
_NETWORK = {"curl", "wget", "ssh", "scp", "nc", "ncat", "telnet", "ftp", "rsync", "pip", "pip3", "npm"}


_PROTECTED_DIRS = {".praxis", ".git"}
_PROTECTED_FILES = {"praxis.toml"}


def _protected(path, ws):
    """PRAXIS's own state/config (log, checkpoints, registry, git hooks, config) is never the plan's to read or write.
    Resolved through symlinks, case-insensitive (macOS/Windows filesystems)."""
    real_ws = os.path.realpath(ws)
    rel = os.path.relpath(os.path.realpath(os.path.join(real_ws, path)), real_ws)
    parts = [p.lower() for p in rel.split(os.sep) if p not in ("", ".")]
    return bool(parts) and (parts[0] in _PROTECTED_DIRS or (len(parts) == 1 and parts[0] in _PROTECTED_FILES))


def _inside(path, ws):
    real_ws = os.path.realpath(ws)
    real = os.path.realpath(os.path.join(real_ws, path))
    return real == real_ws or real.startswith(real_ws + os.sep)


def classify_shell(cmd, ws, sandboxed=False):
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
    # Running project code is Class 2 ONLY inside a sandbox that survived its self-attack; otherwise a human decides.
    exec_cls = 2 if sandboxed else 4
    for runner in _TEST_RUNNERS:
        if argv[:len(runner)] == runner:
            return exec_cls if _paths_ok(argv[len(runner):], ws) else 4
    if prog in _INTERPRETERS and args and not args[0].startswith("-"):
        script = args[0]
        if script.endswith(_INTERPRETERS[prog]) and _inside(script, ws) and _paths_ok(args[1:], ws):
            return exec_cls
        return 4
    if prog in _READ_ONLY:
        return 0 if _paths_ok(args, ws) else 4
    return 4  # unknown program: fail closed


def _paths_ok(args, ws):
    for a in args:
        if a.startswith("-"):
            continue
        if _protected(a, ws):
            return False
        looks_like_path = a.startswith(("/", ".", "~")) or os.sep in a or os.path.exists(os.path.join(ws, a))
        if looks_like_path and not _inside(a, ws):
            return False
    return True


DESKTOP_OBSERVE = {"desktop.windows": 1, "desktop.wait": 0}
DESKTOP_INPUT = ("desktop.focus", "desktop.type", "desktop.key", "desktop.click", "desktop.scroll")


def classify_desktop(tool, args, ws, granted=False):
    """Controlling the desktop is Class 4 (a human decides) until the user has approved desktop control for THIS goal; then input is Class 2 and
    every action is still logged and checkpointed. Closing a window (it may hold unsaved work) and reading the clipboard (it may hold a password that
    would then be shown to a model) are always Class 3: they ask every time."""
    if tool in DESKTOP_OBSERVE:
        return DESKTOP_OBSERVE[tool]
    if tool == "desktop.screenshot":
        name = args.get("name", "screenshot.png")
        return 2 if isinstance(name, str) and _inside(name, ws) and not _protected(name, ws) else 4
    if tool == "desktop.clipboard":
        return 3 if args.get("op") == "get" else (2 if args.get("op") == "set" else 4)
    if tool == "desktop.close":
        return 3
    if tool in DESKTOP_INPUT:
        return 2 if granted else 4
    return 4


def classify_call(tool, args, ws, sandboxed=False, desktop_granted=False):
    if tool == "fs.read" or tool == "fs.list":
        p = args.get("path", ".")
        return 0 if _inside(p, ws) and not _protected(p, ws) else 4
    if tool == "fs.write":
        p = args.get("path", "")
        return 2 if p and _inside(p, ws) and not _protected(p, ws) else 4
    if tool == "shell.run":
        return classify_shell(args.get("cmd"), ws, sandboxed)
    if tool == "desktop.open":
        from . import opener
        t = args.get("target")
        return opener.classify(t, ws) if isinstance(t, str) else 4
    if tool.startswith("desktop.") and tool != "desktop.open":
        return classify_desktop(tool, args if isinstance(args, dict) else {}, ws, desktop_granted)
    if tool == "agent.delegate":
        task, agent = args.get("task"), args.get("agent")
        if not isinstance(task, str) or not task.strip():
            return 4
        # Delegation sends project context to a vendor (>=3); Devin also spends money (4).
        return {"claude": 3, "codex": 3, "droid": 3}.get(agent, 4)
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
    def __init__(self, workspace, max_auto_class=2, sandboxed=False):
        if max_auto_class > MAX_AUTO_CLASS_CAP:
            raise ValueError(f"max_auto_class cannot exceed {MAX_AUTO_CLASS_CAP}")
        self.ws = workspace
        self.max_auto_class = max_auto_class
        self.sandboxed = sandboxed
        self.desktop_granted = False        # set when the user approves desktop control; cleared at the start of every goal

    def decide(self, tool, args, tainted=False):
        cls = classify_call(tool, args, self.ws, self.sandboxed, self.desktop_granted and not tainted)
        if tainted and tool.startswith("desktop.") and tool not in DESKTOP_OBSERVE:
            cls = max(cls, 3)               # a plan shaped by untrusted file content never gets to open programs, press keys or click on its own
        ckpt = cls >= 1
        if tainted and cls > 2:  # hard cap: plans shaped by untrusted content never exceed reversible Class 2
            return Decision(tool, args, cls, DENY,
                            f"plan derived from untrusted content is capped at Class 2 (this is Class {cls})", ckpt, True)
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
