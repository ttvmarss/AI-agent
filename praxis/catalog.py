"""Curated Ollama candidates with PROVENANCE. Every row was read from the model's Ollama library tag page on `checked`.

`recommend()` ranks them for a hardware profile using the physics estimate in hardware.py. Quality is judged by
`rank`: a published benchmark where one exists (secondary sources, labeled), else `equiv` (sqrt(total*active), the usual dense-equivalent rule of thumb for MoE).
It is a PRIOR. `praxis bench --all-ollama` measures real quality and speed, and measured scores always win.
"""
import math
from dataclasses import dataclass

from .hardware import GB, estimate_tokens_per_s, fits

CHECKED = "2026-10-02"


@dataclass(frozen=True)
class Model:
    tag: str
    size_gb: float       # download size of this exact tag (q4_K_M-class), per ollama.com
    total_b: float       # total parameters (billions)
    active_b: float      # active parameters per token (== total for dense)
    ctx_k: int
    focus: str           # "agentic-coding" | "general" | "small"
    source: str
    checked: str = CHECKED
    lcb: float | None = None       # published LiveCodeBench v6 % (third-party aggregators / vendor numbers: SECONDARY evidence)
    evidence: str = ""

    @property
    def equiv(self):
        return math.sqrt(self.total_b * self.active_b)

    @property
    def moe(self):
        return self.active_b < self.total_b

    @property
    def rank(self):
        """Quality prior. A published benchmark outranks the size heuristic (so evidence ranks above guesses);
        among equals a coding-focused build wins. `praxis bench` measurements override all of this."""
        base = 100 + self.lcb if self.lcb else self.equiv
        return base + (0.01 if self.focus == "agentic-coding" else 0)


_BENCH = "LiveCodeBench v6 as reported by third-party aggregators (morphllm.com, insiderllm.com, 2026-10): secondary evidence"


def _m(tag, size, total, active, ctx, focus, lcb=None, evidence=""):
    return Model(tag, size, total, active, ctx, focus, f"https://ollama.com/library/{tag.split(':')[0]}/tags",
                 lcb=lcb, evidence=evidence or (_BENCH if lcb else ""))


CATALOG = [
    _m("qwen3.6:35b-a3b", 24, 35, 3, 256, "general", lcb=80.4),
    _m("qwen3.6:35b-a3b-coding", 23.5, 35, 3, 256, "agentic-coding", lcb=80.4,
       evidence="coding-tuned variant of qwen3.6:35b-a3b: base-model score assumed (the variant itself is unmeasured)"),
    _m("gpt-oss:20b", 14, 21, 3.6, 128, "general"),
    _m("gemma4:26b-a4b", 18, 26, 4, 256, "general", lcb=77.1),
    _m("gemma4:12b", 8.0, 12, 12, 256, "general"),
    _m("laguna-xs-2.1", 20, 33, 3, 256, "agentic-coding"),
    _m("north-mini-code-1.0", 19, 30, 3, 488, "agentic-coding"),
    _m("nemotron-3.5-lightning:30b-a3b", 25, 30, 3, 1000, "general"),
    _m("qwen3.8:27b", 18, 27, 27, 256, "general"),
    _m("qwen3.6:27b", 17, 27, 27, 256, "general", lcb=83.9),
    _m("gemma4:31b", 20, 31, 31, 256, "general"),
    _m("granite4.2:30b", 18, 30, 30, 128, "general"),
    _m("granite4.2:8b", 5.3, 8, 8, 128, "small"),
    _m("lfm2.5:8b", 5.2, 8, 1, 125, "small"),
    _m("granite4.2:3b", 2.2, 3, 3, 128, "small"),
]


@dataclass
class Pick:
    model: Model
    tps: float
    vram_only: bool

    @property
    def pull_cmd(self):
        return f"ollama pull {self.model.tag}"


def _score(profile):
    out = []
    for m in CATALOG:
        size = m.size_gb * GB
        if not fits(size, profile):
            continue
        out.append(Pick(m, estimate_tokens_per_s(size, m.total_b, m.active_b, profile), fits(size, profile, True)))
    return out


def recommend(profile, daily_min_tps=8.0, fast_min_tps=15.0, deep_min_tps=2.0):
    """{'daily','fast','deep'} -> Pick or None.
    daily: best quality that is still interactive.  fast: best that fits fully in VRAM (or a quick CPU model).
    deep: best quality that merely runs (background / hard problems; may be slow)."""
    picks = _score(profile)
    by_quality = sorted(picks, key=lambda p: (-p.model.rank, -p.tps))
    daily = next((p for p in by_quality if p.tps >= daily_min_tps), None) or \
        max(picks, key=lambda p: p.tps, default=None)
    vram = [p for p in by_quality if p.vram_only and p.tps >= fast_min_tps]
    fast = vram[0] if vram else next((p for p in by_quality if p.tps >= fast_min_tps and p.model.size_gb <= 6), None)
    deep = next((p for p in by_quality if p.tps >= deep_min_tps), None) or daily
    return {"daily": daily, "fast": fast, "deep": deep}
