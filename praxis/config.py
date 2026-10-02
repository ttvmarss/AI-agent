"""praxis.toml -> providers, router, agents. Missing tools are skipped and reported, never faked."""
import copy
import os
import shutil
import tomllib

from .providers import ClaudeCLI, CodexCLI, DevinProvider, DroidCLI, OllamaProvider
from .registry import Registry
from .router import ProviderError, Router
from .sandbox import Sandbox, detect

DEFAULTS = {
    "providers": {
        "claude": {"enabled": True, "model": ""},     # Claude subscription via `claude` login
        "codex": {"enabled": True, "model": ""},      # ChatGPT subscription via `codex` login
        "droid": {"enabled": True, "model": ""},      # Factory; needs FACTORY_API_KEY
        "ollama": {"enabled": True, "host": "http://127.0.0.1:11434", "model": "auto",
                   "num_ctx": 16384, "memory_gb": 0, "prefer": []},
        "devin": {"enabled": False},                  # needs DEVIN_API_KEY + DEVIN_ORG_ID; spends ACUs
    },
    "roles": {
        "planner": ["claude", "codex", "droid", "ollama"],
        "replanner": ["claude", "codex", "droid", "ollama"],
        "critic": ["codex", "claude", "droid", "ollama"],
    },
    "routing": {"strategy": "auto", "cooldown_s": 900},
    "limits": {"max_steps": 20, "max_model_calls": 8, "max_cost_usd": 0.0},
    "privacy": {"data_class": "project"},
    "sandbox": {"backend": "auto"},   # auto | bwrap | unshare | docker | none

}


def _merge(a, b):
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(a.get(k), dict):
            _merge(a[k], v)
        else:
            a[k] = v
    return a


def load_config(workspace=None):
    cfg = copy.deepcopy(DEFAULTS)
    for path in (os.path.expanduser("~/.config/praxis/praxis.toml"),
                 os.path.join(workspace, "praxis.toml") if workspace else None):
        if path and os.path.exists(path):
            with open(path, "rb") as f:
                _merge(cfg, tomllib.load(f))
    return cfg


class Stack:
    """The assembled system: usable providers, the router, delegate-capable agents, and what was skipped."""

    def __init__(self, cfg, registry):
        self.cfg, self.registry = cfg, registry
        self.providers, self.skipped = [], {}
        pc = cfg["providers"]
        for name, cls in (("claude", ClaudeCLI), ("codex", CodexCLI), ("droid", DroidCLI)):
            c = pc.get(name, {})
            if not c.get("enabled"):
                self.skipped[name] = "disabled in config"
            elif not shutil.which(name):
                self.skipped[name] = "not installed"
            else:
                self.providers.append(cls(model=c.get("model") or None))
        o = pc.get("ollama", {})
        if not o.get("enabled"):
            self.skipped["ollama"] = "disabled in config"
        else:
            op = OllamaProvider(o.get("host"), o.get("model", "auto"), o.get("num_ctx", 16384),
                                memory_bytes=int(o["memory_gb"] * 2**30) if o.get("memory_gb") else None,
                                registry=registry, prefer=o.get("prefer", []))
            try:
                op.version()
                self.providers.append(op)
            except ProviderError as e:
                self.skipped["ollama"] = str(e)[:120]
        d = pc.get("devin", {})
        if d.get("enabled"):
            dp = DevinProvider(d.get("org_id"))
            if dp.key and dp.org:
                self.providers.append(dp)
            else:
                self.skipped["devin"] = "DEVIN_API_KEY / DEVIN_ORG_ID not set"
        else:
            self.skipped["devin"] = "disabled in config"
        b = cfg["sandbox"]["backend"]
        self.sandbox = Sandbox() if b == "none" else detect(prefer=("bwrap", "unshare", "docker") if b == "auto" else (b,))
        r = cfg["routing"]
        self.router = Router(self.providers, cfg["roles"], registry, r["strategy"], r["cooldown_s"])
        self.agents = {p.card.name.split("/")[0]: p for p in self.providers if getattr(p, "can_delegate", False)}

    def only(self, provider):
        """A router restricted to one provider (used by `bench` to measure providers individually)."""
        return Router([provider], self.cfg["roles"], None, "config")


def build_stack(workspace=None):
    cfg = load_config(workspace)
    reg_path = os.path.join(workspace, ".praxis", "registry.json") if workspace else None
    return Stack(cfg, Registry(reg_path))
