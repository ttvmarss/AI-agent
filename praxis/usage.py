"""Usage accounting across ALL workspaces (a global append-only file), so the router knows how much of each scarce
resource (a subscription's window, a free tier's daily quota) is already spent."""
import json
import os
import threading
import time

from .paths import home

WINDOWS = {"5h": 5 * 3600, "24h": 24 * 3600, "7d": 7 * 24 * 3600}
KEEP_S = 8 * 24 * 3600


def _family(name):
    return name.split("/")[0]


class UsageTracker:
    """budgets: {"claude": {"cost_usd_5h": 8, "calls_24h": 400}, "groq/gpt-oss-120b": {...}}
    keys: calls_|cost_usd_|tokens_ + 5h|24h|7d. A family key is a SHARED budget (all its models); an exact model key
    applies to that model alone. 0 / missing = no budget."""

    def __init__(self, budgets=None, path=None, clock=time.time):
        self.budgets, self.path, self.clock = budgets or {}, path, clock
        self.rows = []  # (ts, provider, cost, tokens)
        self._lock = threading.Lock()
        if path and os.path.exists(path):
            cutoff = clock() - KEEP_S
            try:
                with open(path, encoding="utf-8") as f:
                    for line in f:
                        try:
                            r = json.loads(line)
                            if r["ts"] >= cutoff:
                                self.rows.append((r["ts"], r["p"], float(r.get("cost", 0)), int(r.get("tok", 0))))
                        except (ValueError, KeyError, TypeError):
                            continue
            except OSError:
                pass

    def record(self, provider, ts=None, cost=0.0, tokens=0):
        ts = self.clock() if ts is None else ts
        with self._lock:
            self.rows.append((ts, provider, float(cost or 0), int(tokens or 0)))
            if self.path:
                try:
                    os.makedirs(os.path.dirname(self.path), exist_ok=True)
                    with open(self.path, "a", encoding="utf-8") as f:
                        f.write(json.dumps({"ts": ts, "p": provider, "cost": cost or 0, "tok": tokens or 0}) + "\n")
                except OSError:
                    pass

    def used(self, name, window, family=False):
        since = self.clock() - WINDOWS[window]
        calls = cost = tok = 0
        for ts, p, c, t in self.rows:
            if ts >= since and ((_family(p) == name) if family else (p == name)):
                calls, cost, tok = calls + 1, cost + c, tok + t
        return {"calls": calls, "cost": cost, "tokens": tok}

    def pressure(self, provider):
        """0 = untouched, 1 = budget fully spent. Exact-model budget first, then the family's shared budget."""
        worst = 0.0
        for key, family in ((provider, False), (_family(provider), True)):
            if key == provider and family is False and _family(provider) == provider:
                family = True  # a bare family name (e.g. "codex") IS the family
            for k, limit in (self.budgets.get(key) or {}).items():
                if not limit:
                    continue
                kind, _, win = k.rpartition("_")
                if win not in WINDOWS:
                    continue
                u = self.used(key, win, family=family)
                val = {"calls": u["calls"], "cost_usd": u["cost"], "tokens": u["tokens"]}.get(kind, 0)
                worst = max(worst, val / float(limit))
        return worst

    def summary(self, provider):
        fam = _family(provider) == provider
        return {w: self.used(provider, w, family=fam) for w in WINDOWS}
