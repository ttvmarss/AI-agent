"""One adapter for every OpenAI-compatible chat API (Groq, Cerebras, Gemini, Mistral, NVIDIA, OpenRouter, ...).

Free tiers are rate limited, so the adapter paces itself to the tier's requests-per-minute instead of burning 429s,
reads Retry-After, tells a per-minute limit from a daily quota, and never echoes your key into an error message.
"""
import json
import re
import time
import urllib.error
import urllib.request

from . import proc, secrets
from .router import CapabilityCard, ModelUnavailable, Provider, ProviderError, RateLimited

MAX_WAIT_S = 25          # longer than this and the router should simply try someone else
DAILY = re.compile(r"(per day|daily|\brpd\b|\btpd\b|quota|exceeded your current|insufficient)", re.I)
MODEL_GONE = re.compile(r"(model[^\n]{0,80}(not found|does not exist|decommission|not supported|unavailable)|"
                        r"no such model|unknown model)", re.I)


class OpenAICompatProvider(Provider):
    can_complete = True
    can_delegate = False

    def __init__(self, name, model, base_url, api_key=None, key_env=None, privacy="open", tier="free", rpm=None,
                 max_prompt_tokens=None, timeout=120, clock=time.time, sleep=time.sleep, extra_headers=None):
        self.family, self.model, self.base = name, model, base_url.rstrip("/")
        self.api_key, self.key_env, self.tier = api_key, key_env, tier
        self.rpm, self.max_prompt_tokens, self.timeout = rpm, max_prompt_tokens, timeout
        self._clock, self._sleep, self._last = clock, sleep, None
        self.extra_headers = extra_headers or {}
        self.card = CapabilityCard(f"{name}/{model}", privacy)
        self.last_meta = {}

    # -- plumbing ---------------------------------------------------------------
    def _key(self):
        k = self.api_key or secrets.get(self.family, self.key_env)
        if not k:
            where = f"environment variable {self.key_env} or " if self.key_env else ""
            raise ProviderError(f"{self.family}: no API key. Set {where}`praxis keys set {self.family}`")
        return k

    def _scrub(self, text, key):
        return text.replace(key, "[key]") if key else text

    def _throttle(self):
        if not self.rpm or self._last is None:
            return
        wait = self._last + 60.0 / self.rpm - self._clock()
        if wait <= 0:
            return
        if wait > MAX_WAIT_S:
            raise RateLimited(f"{self.family}: local pacing for {self.rpm} requests/min", retry_after=wait)
        while wait > 0:
            if proc._cancel is not None and proc._cancel.is_set():
                raise ProviderError(f"{self.family}: cancelled")
            step = min(0.2, wait)
            self._sleep(step)
            wait -= step

    def _request(self, method, path, body=None):
        key = self._key()
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json", **self.extra_headers}
        req = urllib.request.Request(self.base + path, method=method, headers=headers,
                                     data=None if body is None else json.dumps(body).encode())
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            raise self._http_error(e, key)
        except Exception as e:
            raise ProviderError(self._scrub(f"{self.family}: {type(e).__name__}: {e}", key))

    def _http_error(self, e, key):
        raw = e.read()[:1500].decode("utf-8", "replace")
        try:
            msg = (json.loads(raw).get("error") or {})
            msg = msg.get("message", raw) if isinstance(msg, dict) else str(msg)
        except ValueError:
            msg = raw
        msg = self._scrub(msg, key)[:300]
        tag = f"{self.family} HTTP {e.code}: {msg}"
        if e.code == 429 or e.code == 402:
            ra = e.headers.get("Retry-After") if e.headers else None
            try:
                wait = float(ra)
            except (TypeError, ValueError):
                wait = 4 * 3600.0 if (e.code == 402 or DAILY.search(msg)) else 60.0
            return RateLimited(tag, retry_after=wait)
        if e.code == 404 or (e.code in (400, 422) and MODEL_GONE.search(msg)):
            return ModelUnavailable(tag)
        if e.code in (401, 403):
            return ProviderError(f"{self.family}: authentication failed (check the key). {msg[:120]}")
        if e.code == 413:
            return ProviderError(f"{tag} (request too large for this tier)")
        return ProviderError(tag)

    # -- API ---------------------------------------------------------------------
    def complete(self, role, messages):
        est = sum(len(m.get("content", "")) for m in messages) // 4
        if self.max_prompt_tokens and est > self.max_prompt_tokens:
            raise ProviderError(f"{self.family}: prompt is about {est} tokens, over this tier's {self.max_prompt_tokens}-token limit")
        self._key()  # fail fast, before pacing
        self._throttle()
        t0 = time.time()
        self._last = self._clock()
        d = self._request("POST", "/chat/completions",
                          {"model": self.model, "messages": messages, "temperature": 0, "stream": False})
        try:
            content = d["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise ProviderError(f"{self.family}: unexpected response shape")
        if isinstance(content, list):
            content = "".join(c.get("text", "") for c in content if isinstance(c, dict))
        content = re.sub(r"<think>.*?</think>", "", content or "", flags=re.S).strip()
        if not content:
            raise ProviderError(f"{self.family}: empty response")
        u = d.get("usage") or {}
        self.last_meta = {"duration_ms": int((time.time() - t0) * 1000), "cost_usd": 0.0,
                          "prompt_tokens": u.get("prompt_tokens"), "completion_tokens": u.get("completion_tokens")}
        return content

    def discover(self, free_only=False):
        """Ask the provider which models it serves (OpenRouter: filter to price 0)."""
        data = self._request("GET", "/models").get("data", [])
        out = []
        for m in data:
            mid = m.get("id") if isinstance(m, dict) else None
            if not mid:
                continue
            if free_only:
                pr = m.get("pricing") or {}
                if not (mid.endswith(":free") or (pr and float(pr.get("prompt", 1) or 0) == 0 and float(pr.get("completion", 1) or 0) == 0)):
                    continue
            out.append(mid)
        return out

    def version(self):
        return f"{self.family} API"
