"""Router: vendor-independent model access. Adapters are the only place vendor specifics may live."""
import json
import os
import time
import urllib.request
from dataclasses import dataclass, field


class ProviderError(Exception):
    pass


class RateLimited(ProviderError):
    """Subscription/usage limit hit: router puts the provider on cooldown and falls back."""


@dataclass
class CapabilityCard:
    name: str
    privacy: str = "cloud"            # cloud | local
    scores: dict = field(default_factory=dict)  # measured, not marketing
    cost_per_call: float = 0.0


class Provider:
    card: CapabilityCard

    def complete(self, role, messages):  # -> str
        raise NotImplementedError


class ScriptedProvider(Provider):
    """Deterministic provider for tests/eval: pops queued responses (str or callable)."""

    def __init__(self, responses, name="scripted", privacy="local"):
        self.queue = list(responses)
        self.card = CapabilityCard(name, privacy)
        self.calls = []

    def complete(self, role, messages):
        self.calls.append((role, messages))
        if not self.queue:
            raise ProviderError("scripted provider exhausted")
        r = self.queue.pop(0)
        r = r(role, messages) if callable(r) else r
        if isinstance(r, Exception):
            raise r
        return r


class AnthropicProvider(Provider):
    """Messages API over stdlib HTTP. Key from env; never logged."""

    def __init__(self, model, api_key=None, max_tokens=4096):
        self.model = model
        self.key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.max_tokens = max_tokens
        self.card = CapabilityCard(f"anthropic/{model}", "cloud")

    def complete(self, role, messages):
        if not self.key:
            raise ProviderError("ANTHROPIC_API_KEY not set")
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        msgs = [m for m in messages if m["role"] != "system"]
        body = json.dumps({"model": self.model, "max_tokens": self.max_tokens,
                           "system": system, "messages": msgs}).encode()
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages", data=body,
            headers={"x-api-key": self.key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                data = json.load(r)
        except Exception as e:
            raise ProviderError(f"{type(e).__name__}: {e}")
        return "".join(b.get("text", "") for b in data.get("content", []))


class Router:
    """Hard filters first (privacy, cooldown, exclusions), then preference order.

    Order = config order for the role, or measured benchmark score when `strategy` is "measured"
    (or "auto" and every candidate has a score). Every call is reported through `on_event`.
    """

    def __init__(self, providers, roles=None, registry=None, strategy="auto", cooldown_s=900, clock=time.time):
        self.providers = providers
        self.roles = roles or {}
        self.registry = registry
        self.strategy = strategy
        self.cooldown_s = cooldown_s
        self.clock = clock
        self.cooling = {}          # provider name -> resume timestamp
        self.last_provider = None  # name of the provider that served the latest successful call

    def _rank(self, role, cands):
        pref = self.roles.get(role) or []
        def pidx(p):
            n = p.card.name
            for i, want in enumerate(pref):
                if n == want or n.startswith(want + "/"):
                    return i
            return len(pref)
        order = sorted(cands, key=pidx)
        if self.registry is not None and self.strategy in ("auto", "measured"):
            kind = "critique" if role == "critic" else "planning"
            scores = [self.registry.score(p.card.name, kind) for p in order]
            if all(x is not None for x in scores) or self.strategy == "measured":
                order = sorted(order, key=lambda p: -(self.registry.score(p.card.name, kind) or 0.0))
        return order

    def eligible(self, role, data_class="project", exclude=()):
        now = self.clock()
        out = []
        for p in self.providers:
            if not getattr(p, "can_complete", True) or p.card.name in exclude:
                continue
            if data_class == "private" and p.card.privacy != "local":
                continue  # data-class gating: private data never leaves the machine
            if self.cooling.get(p.card.name, 0) > now:
                continue
            out.append(p)
        return self._rank(role, out)

    def call(self, role, messages, data_class="project", on_event=None, exclude=()):
        errors = []
        for p in self.eligible(role, data_class, exclude):
            try:
                out = p.complete(role, messages)
            except RateLimited as e:
                self.cooling[p.card.name] = self.clock() + self.cooldown_s
                errors.append(f"{p.card.name}: {e}")
                if on_event:
                    on_event("model.call", {"provider": p.card.name, "role": role, "ok": False,
                                            "error": str(e)[:300], "cooldown_s": self.cooldown_s})
                continue
            except ProviderError as e:
                errors.append(f"{p.card.name}: {e}")
                if on_event:
                    on_event("model.call", {"provider": p.card.name, "role": role, "ok": False, "error": str(e)[:300]})
                continue
            self.last_provider = p.card.name
            if on_event:
                on_event("model.call", {"provider": p.card.name, "role": role, "ok": True,
                                        **(getattr(p, "last_meta", None) or {})})
            return out
        raise ProviderError("no provider succeeded: " + "; ".join(errors) if errors else "no eligible provider")
