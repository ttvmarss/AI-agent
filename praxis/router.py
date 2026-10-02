"""Router: vendor-independent model access. Adapters are the only place vendor specifics may live."""
import json
import os
import urllib.request
from dataclasses import dataclass, field


class ProviderError(Exception):
    pass


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
    """Hard filters first (privacy), then ordered fallback chain. Every call is logged by the caller."""

    def __init__(self, providers):
        self.providers = providers

    def call(self, role, messages, data_class="project", on_event=None):
        errors = []
        for p in self.providers:
            if data_class == "private" and p.card.privacy != "local":
                continue  # data-class gating: private data never leaves the machine
            try:
                out = p.complete(role, messages)
                if on_event:
                    on_event("model.call", {"provider": p.card.name, "role": role, "ok": True})
                return out
            except ProviderError as e:
                errors.append(f"{p.card.name}: {e}")
                if on_event:
                    on_event("model.call", {"provider": p.card.name, "role": role, "ok": False, "error": str(e)})
        raise ProviderError("no provider succeeded: " + "; ".join(errors) if errors else "no eligible provider")
