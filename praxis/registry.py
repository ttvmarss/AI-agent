"""Capability registry (measured scores) + hardware awareness + Ollama model selection."""
import json
import os
import re
import shutil
import subprocess

from . import winproc
import time


class Registry:
    """{provider_name: {"planning": {"score","n","latency_s","date"}, "critique": {...}}} persisted as JSON."""

    def __init__(self, path=None):
        self.path = path
        self.data = {}
        if path and os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                self.data = json.load(f)

    def score(self, name, kind="planning"):
        e = self.data.get(name, {}).get(kind)
        return e["score"] if e else None

    def cost(self, name, kind="planning"):
        e = self.data.get(name, {}).get(kind) or {}
        return float(e.get("cost_per_task", 0.0))

    def record(self, name, kind, score, n, latency_s, **extra):
        self.data.setdefault(name, {})[kind] = {"score": round(score, 4), "n": n,
                                                "latency_s": round(latency_s, 2),
                                                "date": time.strftime("%Y-%m-%d"), **extra}

    def save(self):
        if self.path:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, sort_keys=True)


def detect_memory_bytes():
    """Memory budget a local model may use: GPU VRAM if present, else a share of system RAM."""
    if shutil.which("nvidia-smi"):
        try:
            out = winproc.run(["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=10).stdout
            mib = sum(int(x) for x in out.split() if x.isdigit())
            if mib:
                return int(mib * 1024 * 1024 * 0.9)
        except Exception:
            pass
    try:
        ram = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError, AttributeError):
        return 0
    return int(ram * 0.6)


def parse_params(details, name=""):
    """'27B' -> 27e9 ; '7.6B' ; '500M'. Falls back to parsing the tag (e.g. qwen3:32b)."""
    for src in (str((details or {}).get("parameter_size", "")), name):
        m = re.search(r"(\d+(?:\.\d+)?)\s*([bm])\b", src.lower())
        if m:
            return float(m.group(1)) * (1e9 if m.group(2) == "b" else 1e6)
    return 0.0


def pick_ollama_model(models, memory_bytes, registry=None, prefer=()):
    """Choose the 'smartest' installed model that fits in memory.

    1. user preference list (exact tags) wins if installed and fits
    2. else highest MEASURED planning score (praxis bench) among models that fit
    3. else the largest parameter count that fits (a prior, not a measurement)
    Embedding models are never candidates.
    """
    cands = []
    for m in models:
        name = m.get("name") or m.get("model")
        if not name or "embed" in name.lower():
            continue
        size = int(m.get("size", 0))
        if memory_bytes and size > memory_bytes:
            continue
        cands.append((name, size, parse_params(m.get("details"), name)))
    if not cands:
        return None
    names = {c[0] for c in cands}
    for want in prefer:
        if want in names:
            return want
    if registry is not None:
        scored = [(registry.score(f"ollama/{n}", "planning"), n) for n, _, _ in cands]
        scored = [(s, n) for s, n in scored if s is not None]
        if scored:
            return max(scored)[1]
    return max(cands, key=lambda c: (c[2], c[1]))[0]


def pick_for_hardware(models, profile, registry=None, prefer=(), min_tps=6.0):
    """Choose the best INSTALLED Ollama model for this machine.

    Fit = weights fit in VRAM + usable RAM. Speed = measured tokens/s if `praxis bench` recorded it, else the
    bandwidth physics estimate (MoE reads only active experts). Among models that are fast enough, a measured
    quality score wins; with no measurements, the catalog's dense-equivalent size is the prior.
    """
    import math
    from .catalog import CATALOG
    from .hardware import GB, estimate_tokens_per_s, fits
    by_tag = {m.tag: m for m in CATALOG}
    cands = []
    for m in models:
        name = m.get("name") or m.get("model")
        if not name or "embed" in name.lower():
            continue
        size = int(m.get("size", 0))
        if size <= 0 or not fits(size, profile):
            continue
        cat = by_tag.get(name) or next((c for t, c in by_tag.items() if name.startswith(t + "-") or t.startswith(name + "-")), None)
        total = cat.total_b if cat else (parse_params(m.get("details"), name) / 1e9 or size / GB * 2)
        active = cat.active_b if cat else total
        entry = (registry.data.get(f"ollama/{name}", {}).get("planning", {}) if registry is not None else {})
        tps = entry.get("tokens_per_s") or estimate_tokens_per_s(size, total, active, profile)
        cands.append({"name": name, "tps": tps, "score": entry.get("score"),
                      "equiv": cat.rank if cat else math.sqrt(total * active)})
    if not cands:
        return None
    names = {c["name"] for c in cands}
    for want in prefer:
        if want in names:
            return want
    usable = [c for c in cands if c["tps"] >= min_tps] or [max(cands, key=lambda c: c["tps"])]
    measured = [c for c in usable if c["score"] is not None]
    if measured:
        return max(measured, key=lambda c: (c["score"], c["tps"]))["name"]
    return max(usable, key=lambda c: (c["equiv"], c["tps"]))["name"]
