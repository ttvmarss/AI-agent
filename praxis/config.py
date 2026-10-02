"""praxis.toml -> providers, router, agents. Missing tools are skipped and reported, never faked."""
import copy
import os
import shutil
import tomllib

from . import secrets
from .free_tiers import PRESETS
from .hardware import detect_hardware, profile_from_config
from .openai_compat import OpenAICompatProvider
from .paths import home
from .usage import UsageTracker
from . import discover
from .providers import ClaudeCLI, CodexCLI, DevinCLI, DevinProvider, DroidCLI, OllamaProvider
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
        # Devin: "auto" uses the `devin` command-line agent (from Devin Desktop, signed in with `devin auth login`) if it is found,
        # else the cloud API (DEVIN_API_KEY + DEVIN_ORG_ID, spends ACUs); "cli" / "api" force one of them.
        "devin": {"enabled": True, "mode": "auto", "model": ""},
        # free cloud tiers: each needs a (free) API key: `praxis keys set <name>`; see `praxis free`
        "groq": {"enabled": True}, "cerebras": {"enabled": True}, "ollama-cloud": {"enabled": True},
        "gemini": {"enabled": True}, "mistral": {"enabled": True}, "nvidia": {"enabled": True},
        "openrouter": {"enabled": True},
    },
    # Spend limits you want PRAXIS to respect (soft: an exhausted provider goes to the back, never blocks a goal).
    # Keys: calls_|cost_usd_|tokens_ + 5h|24h|7d. A family name ("claude") is a SHARED budget. Free tiers get theirs
    # automatically from their documented limits. Example:  [budgets.claude]  cost_usd_5h = 8.0
    "budgets": {},
    # One provider instance per model; the router picks by tier (unmeasured) or by measured quality-per-cost.
    # "" = the account's default model. IDs for claude were verified live; codex/droid IDs come from vendor docs
    # (2026-10-02) and are validated at runtime: a rejected ID falls back automatically (ModelUnavailable).
    "models": {
        "claude": {"best": "claude-fable-5-1", "balanced": "claude-opus-5-5", "fast": "claude-sonnet-5-5"},
        "codex": {"best": "gpt-5.5", "balanced": ""},
        "droid": {"best": "claude-fable-5.1", "balanced": ""},
    },
    "role_tiers": {
        "planner": ["balanced", "best", "fast", "free", "local"], "replanner": ["balanced", "best", "fast", "free", "local"],
        "critic": ["best", "balanced", "fast", "free", "local"], "delegate": ["balanced", "fast", "best"],
        "chat": ["fast", "free", "local", "balanced"],      # conversation wants the quickest model, not the strongest
    },
    "hardware": {"vram_gb": 0, "ram_gb": 0, "gpu_name": "", "ram_bw_gbps": 0, "gpu_bw_gbps": 0},
    "roles": {
        "planner": ["claude", "codex", "droid", "ollama", "ollama-cloud", "groq", "cerebras", "gemini", "mistral", "nvidia", "openrouter"],
        "replanner": ["claude", "codex", "droid", "ollama", "ollama-cloud", "groq", "cerebras", "gemini", "mistral", "nvidia", "openrouter"],
        "critic": ["codex", "claude", "droid", "groq", "cerebras", "ollama-cloud", "ollama", "gemini", "mistral", "nvidia", "openrouter"],
        "chat": ["groq", "cerebras", "gemini", "mistral", "ollama-cloud", "ollama", "claude", "nvidia", "openrouter", "codex", "droid"],
    },
    # strategy: "auto" = quality first, cheapest within 0.05 of the best once measured | "frugal" = local, then free cloud,
    # then subscription models small to large, escalating only when a cheaper model fails verification (use less Claude)
    # | "measured" = best score | "config" = the role orders below.
    "routing": {"strategy": "auto", "cooldown_s": 900, "slack": 0.25, "min_quality": 0.6, "escalate": True,
                "max_escalations": 2},
    "limits": {"max_steps": 20, "max_model_calls": 8, "max_cost_usd": 0.0},
    "privacy": {"data_class": "project"},
    "sandbox": {"backend": "auto"},   # auto | bwrap | unshare | docker | none
    # Hands-free voice (pip install faster-whisper piper-tts sounddevice). User config only: a project folder cannot touch it.
    "voice": {"enabled": True, "wake_word": "praxis", "stt_model": "base.en", "voice": "jarvis-high", "speak": True,
              "attentive_s": 15.0, "approval_s": 60.0, "input_device": "", "chat": True,
              "wake_required": False},        # False: just talk; True: it acts only on sentences that start with its name

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
    from .paths import home as default_home
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
        self.tools_found = discover.ensure_on_path(("devin", "droid"))      # Devin Desktop / Factory Desktop installs need not be on PATH
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
        for pr in PRESETS:  # free cloud tiers: one provider per model, only if you gave a key
            c = pc.get(pr.id, {})
            if not c.get("enabled", True):
                self.skipped[pr.id] = "disabled in config"
                continue
            key = secrets.get(pr.id, pr.key_env)
            if not key:
                self.skipped[pr.id] = f"no API key: `praxis keys set {pr.id}` (free key: {pr.signup_url})"
                continue
            models = list(c.get("models") or pr.models)
            if not models:
                self.skipped[pr.id] = f"no models chosen: `praxis free models {pr.id}` then set models in your config"
                continue
            for m in models:
                if pr.kind == "ollama-cloud":
                    self.providers.append(OllamaProvider(c.get("host", pr.base_url), m, api_key=key, label=pr.id,
                                                         privacy=pr.privacy, tier="free", timeout=300))
                else:
                    self.providers.append(OpenAICompatProvider(
                        pr.id, m, c.get("base_url", pr.base_url), api_key=key, key_env=pr.key_env, privacy=pr.privacy,
                        tier="free", rpm=pr.rpm, max_prompt_tokens=pr.max_prompt_tokens))
        budgets = {k: dict(v) for k, v in (cfg.get("budgets") or {}).items()}
        for pr in PRESETS:  # a free tier's own documented limits become its budget (with 10% headroom)
            derived = {}
            if pr.rpd:
                derived["calls_24h"] = int(pr.rpd * 0.9)
            if pr.tpd:
                derived["tokens_24h"] = int(pr.tpd * 0.9)
            if derived:
                budgets[pr.id] = {**derived, **budgets.get(pr.id, {})}
        self.usage = UsageTracker(budgets, path=os.path.join(home(), "usage.jsonl"))
        d = pc.get("devin", {})
        mode = d.get("mode", "auto")
        if not d.get("enabled"):
            self.skipped["devin"] = "disabled in config"
        else:
            cli_path = self.tools_found.get("devin") if mode in ("auto", "cli") else None
            if cli_path:
                self.providers.append(DevinCLI(model=d.get("model") or None, tier="balanced"))
            elif mode in ("auto", "api") and os.environ.get("DEVIN_API_KEY") and (d.get("org_id") or os.environ.get("DEVIN_ORG_ID")):
                dp = DevinProvider(d.get("org_id"))
                dp.tier = "best"
                self.providers.append(dp)
            elif mode == "api":
                self.skipped["devin"] = "DEVIN_API_KEY / DEVIN_ORG_ID not set"
            else:
                self.skipped["devin"] = ("the Devin CLI was not found: in Devin Desktop open the Command Palette and run \"Install Devin CLI\", "
                                         "then `devin auth login` (or set DEVIN_API_KEY and DEVIN_ORG_ID for the cloud API)")
        b = cfg["sandbox"]["backend"]
        if not detect_sandbox or b == "none":
            self.sandbox = Sandbox()
        else:
            self.sandbox = detect(prefer=("bwrap", "unshare", "docker") if b == "auto" else (b,))
        r = cfg["routing"]
        self.router = Router(self.providers, cfg["roles"], registry, r["strategy"], r["cooldown_s"],
                             role_tiers=cfg["role_tiers"], usage=self.usage, min_quality=r.get("min_quality", 0.6),
                             slack=r.get("slack", 0.25))
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
