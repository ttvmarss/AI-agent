"""Tool runtime: workspace-confined tools plus checkpoint/rollback (the recovery primitive)."""
import hashlib
import os
import shutil
import subprocess
import uuid

# Never copied by checkpoints, never deleted by rollback, never listed: tool-managed or regenerable trees.
_SKIP = {".praxis", ".git", "node_modules", ".venv", "venv", "__pycache__"}
MAX_OUT = 20000


class ToolError(Exception):
    pass


class Workspace:
    def __init__(self, root, sandbox=None):
        self.sandbox = sandbox
        self.root = os.path.realpath(root)
        os.makedirs(self.root, exist_ok=True)
        self.ckpt_dir = os.path.join(self.root, ".praxis", "checkpoints")

    def resolve(self, rel):
        p = os.path.realpath(os.path.join(self.root, rel))
        if p != self.root and not p.startswith(self.root + os.sep):
            raise ToolError(f"path escapes workspace: {rel}")  # defense in depth behind the Guard
        return p

    # -- recovery -----------------------------------------------------------
    def checkpoint(self):
        cid = uuid.uuid4().hex[:12]
        dest = os.path.join(self.ckpt_dir, cid)
        os.makedirs(dest)
        for name in os.listdir(self.root):
            if name in _SKIP:
                continue
            src = os.path.join(self.root, name)
            if os.path.isdir(src) and not os.path.islink(src):
                shutil.copytree(src, os.path.join(dest, name), symlinks=True)
            else:
                shutil.copy2(src, os.path.join(dest, name), follow_symlinks=False)
        return cid

    def prune(self, delete_ids):
        """Delete exactly these checkpoint directories (anything not named here is left alone)."""
        for name in delete_ids:
            if os.sep in name or name in ("", ".", ".."):
                continue  # ids are plain directory names; never follow a crafted path
            shutil.rmtree(os.path.join(self.ckpt_dir, name), ignore_errors=True)

    def rollback(self, cid):
        src = os.path.join(self.ckpt_dir, cid)
        if not os.path.isdir(src):
            raise ToolError(f"unknown checkpoint {cid}")
        for name in os.listdir(self.root):
            if name in _SKIP:
                continue
            p = os.path.join(self.root, name)
            if os.path.isdir(p) and not os.path.islink(p):
                shutil.rmtree(p)
            else:
                os.unlink(p)
        for name in os.listdir(src):
            s = os.path.join(src, name)
            d = os.path.join(self.root, name)
            if os.path.isdir(s) and not os.path.islink(s):
                shutil.copytree(s, d, symlinks=True)
            else:
                shutil.copy2(s, d, follow_symlinks=False)

    def manifest(self):
        """{relpath: sha1} of every workspace file (used to report exactly what a delegate changed)."""
        out = {}
        for base, dirs, files in os.walk(self.root):
            dirs[:] = [d for d in dirs if d not in _SKIP]
            for fn in files:
                p = os.path.join(base, fn)
                if os.path.islink(p):
                    continue
                with open(p, "rb") as f:
                    out[os.path.relpath(p, self.root)] = hashlib.sha1(f.read()).hexdigest()
        return out

    # -- tools --------------------------------------------------------------
    def fs_read(self, path):
        with open(self.resolve(path), "r", errors="replace") as f:
            return f.read(MAX_OUT)

    def fs_list(self, path="."):
        return sorted(n for n in os.listdir(self.resolve(path)) if n not in _SKIP)

    def fs_write(self, path, content):
        p = self.resolve(path)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(content)
        return f"wrote {len(content)} bytes to {path}"

    def shell_run(self, cmd, timeout=60):
        import shlex
        argv = shlex.split(cmd)
        if self.sandbox is not None and self.sandbox.strong:
            argv = self.sandbox.wrap(argv, self.root)
        proc = subprocess.run(argv, cwd=self.root, capture_output=True, text=True,
                              timeout=timeout, shell=False)
        out = (proc.stdout + proc.stderr)[-MAX_OUT:]
        return {"returncode": proc.returncode, "output": out}


class ToolRuntime:
    def __init__(self, workspace, agents=None):
        self.ws = workspace
        self.agents = agents or {}
        self.tools = {
            "fs.read": lambda a: self.ws.fs_read(a["path"]),
            "fs.list": lambda a: self.ws.fs_list(a.get("path", ".")),
            "fs.write": lambda a: self.ws.fs_write(a["path"], a["content"]),
            "shell.run": lambda a: self.ws.shell_run(a["cmd"], a.get("timeout", 60)),
            "agent.delegate": self._delegate,
        }

    def _delegate(self, a):
        agent = self.agents.get(a.get("agent"))
        if agent is None or not getattr(agent, "can_delegate", False):
            raise ToolError(f"agent {a.get('agent')!r} is not configured for delegation")
        from .router import ProviderError
        before = self.ws.manifest()
        try:
            summary = agent.delegate(a["task"], self.ws.root)
        except ProviderError as e:
            raise ToolError(f"delegate failed: {e}")
        after = self.ws.manifest()
        changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
        return {"agent": a["agent"], "summary": str(summary)[:2000], "changed": changed}

    def run(self, tool, args):
        if tool not in self.tools:
            raise ToolError(f"unknown tool {tool}")
        try:
            return self.tools[tool](args)
        except ToolError:
            raise
        except subprocess.TimeoutExpired:
            raise ToolError("timeout")
        except Exception as e:  # tool failures are data, not crashes
            raise ToolError(f"{type(e).__name__}: {e}")
