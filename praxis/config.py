"""praxis.toml -> providers, router, agents. Missing tools are skipped and reported, never faked."""
import copy
import os
import shutil
import tomllib

from .hardware import detect_hardware, profile_from_config
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
                   "num_ctx": 0,            # 0 = auto: 8192 on <=8GB VRAM (KV cache would crowd out weights), else 16384
                   "memory_gb": 0, "prefer": [], "min_tokens_per_s": 6.0},
        "devin": {"enabled": False},                  # needs DEVIN_API_KEY + DEVIN_ORG_ID; spends ACUs
    },
    # One provider instance per model; the router picks by tier (unmeasured) or by measured quality-per-cost.
    # "" = the account's default model. IDs for claude were verified live; codex/droid IDs come from vendor docs
    # (2026-10-02) and are validated at runtime: a rejected ID falls back automatically (ModelUnavailable).
    "models": {
        "claude": {"best": "claude-fable-5-1", "balanced": "claude-opus-5-5", "fast": "claude-sonnet-5-5"},
        "codex": {"best": "gpt-5.5", "balanced": ""},
        "droid": {"best": "claude-fable-5.1", "balanced": ""},
    },
    "role_tiers": {
        "planner": ["balanced", "best", "fast"], "replanner": ["balanced", "best", "fast"],
        "critic": ["best", "balanced", "fast"], "delegate": ["balanced", "fast", "best"],
    },
    "hardware": {"vram_gb": 0, "ram_gb": 0, "gpu_name": "", "ram_bw_gbps": 0, "gpu_bw_gbps": 0},
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


# Sections a workspace's own praxis.toml may set. Everything that decides WHERE DATA GOES or WHAT IS TRUSTED
# (provider hosts/ids, sandbox, privacy, limits, routing) comes only from the user's own config.
WORKSPACE_SAFE = ("hardware", "role_tiers", "roles")


def _read(path):
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def user_config_paths():
    from .desktop.settings import default_home
    return [os.path.join(os.path.expanduser("~"), ".config", "praxis", "praxis.toml"),
            os.path.join(default_home(), "praxis.toml")]


def load_config(workspace=None):
    cfg = copy.deepcopy(DEFAULTS)
    if workspace:  # untrusted: a folder you open may ship a hostile praxis.toml (e.g. pointing the "local" model at a remote host)
        theirs = _read(os.path.join(workspace, "praxis.toml"))
        _merge(cfg, {k: v for k, v in theirs.items() if k in WORKSPACE_SAFE})
    for path in user_config_paths():  # trusted, and applied last so it wins
        _merge(cfg, _read(path))
    return cfg


class Stack:
    """The assembled system: usable providers, the router, delegate-capable agents, and what was skipped."""

    def __init__(self, cfg, registry, detect_sandbox=True):
        self.cfg, self.registry = cfg, registry
        self.profile = profile_from_config(cfg["hardware"], detect_hardware())
        self.providers, self.skipped = [], {}
        pc = cfg["providers"]
        for name, cls in (("claude", ClaudeCLI), ("codex", CodexCLI), ("droid", DroidCLI)):
            c = pc.get(name, {})
            if not c.get("enabled"):
                self.skipped[name] = "disabled in config"
            elif not shutil.which(name):
                self.skipped[name] = "not installed"
            else:
                models = dict(cfg["models"].get(name) or {})
                if c.get("model"):                      # legacy single-model override wins
                    models = {"balanced": c["model"]}
                seen = set()
                for tier, model in (models or {"balanced": ""}).items():
                    if model in seen:
                        continue
                    seen.add(model)
                    self.providers.append(cls(model=model or None, tier=tier))
        o = pc.get("ollama", {})
        self.ollama_num_ctx = o.get("num_ctx") or (8192 if 0 < self.profile.vram_total <= 8.5 * 2**30 else 16384)
        if not o.get("enabled"):
            self.skipped["ollama"] = "disabled in config"
        else:
            op = OllamaProvider(o.get("host"), o.get("model", "auto"), self.ollama_num_ctx,
                                memory_bytes=int(o["memory_gb"] * 2**30) if o.get("memory_gb") else None,
                                registry=registry, prefer=o.get("prefer", []), profile=self.profile,
                                min_tps=o.get("min_tokens_per_s", 6.0))
            try:
                op.version()
                self.providers.append(op)
            except ProviderError as e:
                self.skipped["ollama"] = str(e)[:120]
        d = pc.get("devin", {})
        if d.get("enabled"):
            dp = DevinProvider(d.get("org_id"))
            dp.tier = "best"
            if dp.key and dp.org:
                self.providers.append(dp)
            else:
                self.skipped["devin"] = "DEVIN_API_KEY / DEVIN_ORG_ID not set"
        else:
            self.skipped["devin"] = "disabled in config"
        b = cfg["sandbox"]["backend"]
        if not detect_sandbox or b == "none":
            self.sandbox = Sandbox()
        else:
            self.sandbox = detect(prefer=("bwrap", "unshare", "docker") if b == "auto" else (b,))
        r = cfg["routing"]
        self.router = Router(self.providers, cfg["roles"], registry, r["strategy"], r["cooldown_s"],
                             role_tiers=cfg["role_tiers"])
        # one delegate per family, chosen by the role's tier preference (default: balanced)
        self.agents = {}
        pref = cfg["role_tiers"].get("delegate", [])
        for p in sorted((p for p in self.providers if getattr(p, "can_delegate", False)),
                        key=lambda p: pref.index(p.tier) if p.tier in pref else len(pref)):
            self.agents.setdefault(p.card.name.split("/")[0], p)

    def only(self, provider):
        """A router restricted to one provider (used by `bench` to measure providers individually)."""
        return Router([provider], self.cfg["roles"], None, "config")


def build_stack(workspace=None):
    cfg = load_config(workspace)
    reg_path = os.path.join(workspace, ".praxis", "registry.json") if workspace else None
    return Stack(cfg, Registry(reg_path))
