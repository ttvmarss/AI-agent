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


class ModelUnavailable(ProviderError):
    """This account/plan/CLI does not offer that model (yet). Long cooldown; the next model in the family serves."""


def family(name):
    """'claude/opus' -> 'claude'. A critic must come from a different FAMILY, not merely a different model id."""
    return name.split("/")[0]


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


EPSILON = 0.05            # scores closer than this are "equally good": then the cheaper model wins
UNAVAILABLE_COOLDOWN_S = 6 * 3600
STRIKE_COOLDOWN_S = 600


class Router:
    """Hard filters first (privacy, cooldown, exclusions), then ranking.

    Ranking: if EVERY candidate has a measured score (praxis bench), pick the cheapest model within EPSILON of the
    best score, then the rest by score. Otherwise: family preference order for the role, and within a family the
    role's preferred tier (planner -> balanced, critic -> best by default). Every call is reported via `on_event`.
    """

    def __init__(self, providers, roles=None, registry=None, strategy="auto", cooldown_s=900, clock=time.time,
                 role_tiers=None):
        self.providers = providers
        self.roles = roles or {}
        self.role_tiers = role_tiers or {}
        self.registry = registry
        self.strategy = strategy
        self.cooldown_s = cooldown_s
        self.clock = clock
        self.cooling = {}          # provider name -> resume timestamp
        self.last_provider = None  # name of the provider that served the latest successful call
        self.fails = {}            # consecutive unexplained failures per provider

    def _measured_order(self, cands, kind):
        sc = {p.card.name: self.registry.score(p.card.name, kind) or 0.0 for p in cands}
        top = max(sc.values())
        pool = [p for p in cands if sc[p.card.name] >= top - EPSILON]
        first = min(pool, key=lambda p: (self.registry.cost(p.card.name, kind), -sc[p.card.name]))
        rest = sorted((p for p in cands if p is not first), key=lambda p: -sc[p.card.name])
        return [first] + rest

    def _rank(self, role, cands):
        if not cands:
            return cands
        kind = "critique" if role == "critic" else "planning"
        if self.registry is not None and self.strategy in ("auto", "measured"):
            have = [self.registry.score(p.card.name, kind) is not None for p in cands]
            if all(have) or (self.strategy == "measured" and any(have)):
                return self._measured_order(cands, kind)
        pref, tiers = self.roles.get(role) or [], self.role_tiers.get(role) or []

        def key(p):
            fam = family(p.card.name)
            fi = pref.index(fam) if fam in pref else len(pref)
            tier = getattr(p, "tier", None)
            return (fi, tiers.index(tier) if tier in tiers else len(tiers))
        return sorted(cands, key=key)

    def eligible(self, role, data_class="project", exclude=()):
        now = self.clock()
        out = []
        for p in self.providers:
            if not getattr(p, "can_complete", True) or p.card.name in exclude or family(p.card.name) in exclude:
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
            except (RateLimited, ModelUnavailable) as e:
                wait = UNAVAILABLE_COOLDOWN_S if isinstance(e, ModelUnavailable) else self.cooldown_s
                self.cooling[p.card.name] = self.clock() + wait
                errors.append(f"{p.card.name}: {e}")
                if on_event:
                    on_event("model.call", {"provider": p.card.name, "role": role, "ok": False,
                                            "error": str(e)[:300], "cooldown_s": wait})
                continue
            except ProviderError as e:
                n = self.fails[p.card.name] = self.fails.get(p.card.name, 0) + 1
                if n >= 2:  # two strikes: stop paying the timeout on every call
                    self.cooling[p.card.name] = self.clock() + STRIKE_COOLDOWN_S
                errors.append(f"{p.card.name}: {e}")
                if on_event:
                    on_event("model.call", {"provider": p.card.name, "role": role, "ok": False, "error": str(e)[:300]})
                continue
            self.fails[p.card.name] = 0
            self.last_provider = p.card.name
            if on_event:
                on_event("model.call", {"provider": p.card.name, "role": role, "ok": True,
                                        **(getattr(p, "last_meta", None) or {})})
            return out
        raise ProviderError("no provider succeeded: " + "; ".join(errors) if errors else "no eligible provider")
