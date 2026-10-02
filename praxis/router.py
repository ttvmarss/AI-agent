"""Router: vendor-independent model access. Adapters are the only place vendor specifics may live."""
import json
import os
import re
import time
import urllib.request
from dataclasses import dataclass, field


class ProviderError(Exception):
    pass


class RateLimited(ProviderError):
    """Subscription/usage limit hit: router puts the provider on cooldown and falls back.
    `retry_after` (seconds) is used for the cooldown when the provider says when to come back."""

    def __init__(self, msg="", retry_after=None):
        super().__init__(msg)
        self.retry_after = retry_after


class ModelUnavailable(ProviderError):
    """This account/plan/CLI does not offer that model (yet). Long cooldown; the next model in the family serves."""


PRIVACY_RANK = {"local": 0, "cloud": 1, "open": 2}      # what a provider does with your data
GOAL_RANK = {"private": 0, "project": 1, "open": 2}     # what a goal allows


def provider_rank(p):
    return PRIVACY_RANK.get(p.card.privacy, 2)  # an unknown label is treated as the LEAST trusted, never the most


_UNIT = {"ms": 0.001, "millisecond": 0.001, "s": 1, "sec": 1, "second": 1, "m": 60, "min": 60, "minute": 60,
         "h": 3600, "hr": 3600, "hour": 3600}


def parse_reset_seconds(text, now=None):
    """Seconds until a limit resets, read from a provider's own error text; None if it does not say."""
    text = text or ""
    m = re.search(r"(?:in|after)\s+(\d+(?:\.\d+)?)\s*(ms|milliseconds?|secs?|seconds?|mins?|minutes?|hrs?|hours?|s|m|h)\b", text, re.I)
    if m:
        return float(m.group(1)) * _UNIT[m.group(2).lower().rstrip("s") if m.group(2).lower() not in ("s", "ms") else m.group(2).lower()]
    m = re.search(r"reset[s]?\s*(?:at|around)?\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", text, re.I)
    if m:
        now = time.time() if now is None else now
        hour = int(m.group(1)) % 12 + (12 if m.group(3).lower() == "pm" else 0)
        lt = time.localtime(now)
        target = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, hour, int(m.group(2) or 0), 0, 0, 0, -1))
        return target - now if target > now else target + 86400 - now
    return None


def cost_class(p):
    """0 = runs on your machine, 1 = free cloud tier, 2 = paid / subscription. Drives the frugal ladder."""
    explicit = getattr(p, "cost_class", None)
    if explicit is not None:
        return explicit
    if p.card.privacy == "local":
        return 0
    return 1 if getattr(p, "tier", None) == "free" else 2


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
                 role_tiers=None, usage=None, min_quality=0.6, slack=0.25):
        self.usage, self.min_quality, self.slack = usage, min_quality, slack
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

    def _frugal_order(self, cands, kind):
        """Cheapest model that is good enough: local, then free cloud, then subscription models from small to large.
        Models measured below min_quality, or more than `slack` under the best measured one, go to the back."""
        reg = self.registry
        sc = {id(p): (reg.score(p.card.name, kind) if reg is not None else None) for p in cands}
        measured = [v for v in sc.values() if v is not None]
        top = max(measured) if measured else None
        tier_rank = {"local": 0, "free": 1, "fast": 2, "balanced": 3, "best": 4}
        good, weak = [], []
        for p in cands:
            v = sc[id(p)]
            (weak if v is not None and (v < self.min_quality or (top is not None and v < top - self.slack)) else good).append(p)
        key = lambda p: (cost_class(p), tier_rank.get(getattr(p, "tier", None), 3), -(sc[id(p)] if sc[id(p)] is not None else 0.5))
        return sorted(good, key=key) + sorted(weak, key=lambda p: -(sc[id(p)] or 0.0))

    def _rank(self, role, cands):
        if not cands:
            return cands
        kind = "critique" if role == "critic" else "planning"
        if self.strategy == "frugal" and role != "critic":
            return self._frugal_order(cands, kind)
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
            if provider_rank(p) > GOAL_RANK.get(data_class, 1):
                continue  # data-class gating: private = local only; project = + trusted cloud; open = + free tiers
            if self.cooling.get(p.card.name, 0) > now:
                continue
            out.append(p)
        ranked = self._rank(role, out)
        if self.usage is not None:  # a spent budget / exhausted free quota goes to the back (last resort), not away
            ok = [p for p in ranked if self.usage.pressure(p.card.name) < 1.0]
            return ok + [p for p in ranked if p not in ok]
        return ranked

    def call(self, role, messages, data_class="project", on_event=None, exclude=()):
        errors = []
        secrets_found = None
        for p in self.eligible(role, data_class, exclude):
            if provider_rank(p) == 2:  # open tiers may log/train: they never see a credential
                if secrets_found is None:
                    from .redact import find_secrets
                    secrets_found = find_secrets("\n".join(m.get("content", "") for m in messages))
                if secrets_found:
                    errors.append(f"{p.card.name}: skipped (possible secret: {', '.join(secrets_found)})")
                    if on_event:
                        on_event("model.skipped", {"provider": p.card.name, "role": role,
                                                   "reason": f"possible secret in prompt ({', '.join(secrets_found)}); "
                                                             "open tiers never see credentials"})
                    continue
            try:
                out = p.complete(role, messages)
            except (RateLimited, ModelUnavailable) as e:
                wait = UNAVAILABLE_COOLDOWN_S if isinstance(e, ModelUnavailable) else \
                    (getattr(e, "retry_after", None) or parse_reset_seconds(str(e), now=self.clock()) or self.cooldown_s)
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
            if self.usage is not None:
                meta = getattr(p, "last_meta", None) or {}
                self.usage.record(p.card.name, self.clock(), meta.get("cost_usd") or 0,
                                  (meta.get("prompt_tokens") or 0) + (meta.get("completion_tokens") or 0))
            if on_event:
                on_event("model.call", {"provider": p.card.name, "role": role, "ok": True,
                                        **(getattr(p, "last_meta", None) or {})})
            return out
        raise ProviderError("no provider succeeded: " + "; ".join(errors) if errors else "no eligible provider")
