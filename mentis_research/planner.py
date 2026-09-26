"""planner.py — turns a user request into a research plan.

Decides (1) whether a request needs the research workspace at all, (2) which
queries to run on which providers, and (3) what kind of ContextArtifact the
research should distil into. Deterministic by default; if an `llm` callable
is supplied (JARVIS passes jarvis_brain._utility_call), it is asked for
better search queries and falls back to the heuristic on any failure.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

LLM = Callable[[str, str], str]  # (system, user) -> text

_RESEARCH_TRIGGERS = re.compile(
    r"\b(research|investigate|look\s+into|find\s+(?:me\s+)?(?:the\s+)?(?:best|good|top)|compare|evaluate|"
    r"survey|which\s+(?:\w+\s+){0,3}(?:should|could|would|is\s+best)|what\s+are\s+the\s+best|alternatives?\s+to|"
    r"search\s+(?:github|the\s+web|npm|pypi|online|for))\b",
    re.I,
)

_STOP = set(
    """a an the and or of for to in on with by from at as is are be can could would should will may might our my your
    their its it this that these those what which who whom how why when where do does did done please research
    investigate look into find me best good top compare evaluate determine check checking see whether if any some
    also them they there then than more most very really just about project projects improve improving useful add
    adds anything something things thing make makes use using used copilot jarvis mentis assistant pc computer
    machine mine us we i you out up could want need needs like tell give show list run open source opensource
    licenses license licensing capabilities capability compatibility compatible hardware requirements""".split()
)

# words that must be kept even though they look generic
_KEEP = {"open-source", "llm", "ai", "gpu", "cpu"}


@dataclass
class ResearchPlan:
    title: str
    queries: Dict[str, List[str]]  # provider -> queries
    artifact_type: str
    artifact_title: str
    keywords: List[str]
    criteria: List[str] = field(default_factory=list)
    select_k: int = 3
    inspect_n: int = 6


def needs_research(text: str) -> bool:
    return bool(_RESEARCH_TRIGGERS.search(text or ""))


def keywords(text: str, limit: int = 6) -> List[str]:
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9+#.\-]*", text.lower())
    out: List[str] = []
    for w in words:
        w = w.strip(".-")
        if (w in _KEEP or (len(w) > 2 and w not in _STOP)) and w not in out:
            out.append(w)
    return out[:limit]


def _artifact_kind(text: str) -> tuple:
    t = text.lower()
    if re.search(r"\b(integrat\w*|improve (?:our|my|the)|add to (?:our|my)|could improve|use in our)\b", t):
        return "INTEGRATION_CANDIDATES", "INTEGRATION CANDIDATES"
    if re.search(r"\b(security|vulnerab\w*|cve|exploit)\b", t):
        return "SECURITY_FINDINGS", "SECURITY FINDINGS"
    if re.search(r"\b(bug|error|crash|stack ?trace|exception)\b", t):
        return "BUG_EVIDENCE", "BUG EVIDENCE"
    if re.search(r"\b(model|models|llm|llms)\b", t) and re.search(r"\b(compare|best|vs|which)\b", t):
        return "MODEL_COMPARISON", "MODEL COMPARISON"
    if re.search(r"\b(docs|documentation|api reference|how to)\b", t):
        return "DOCUMENTATION_SUMMARY", "DOCUMENTATION SUMMARY"
    if re.search(r"\b(competitor|competition|market)\b", t):
        return "COMPETITOR_ANALYSIS", "COMPETITOR ANALYSIS"
    if re.search(r"\b(design|brand|ui|ux|style)\b", t):
        return "DESIGN_REQUIREMENTS", "DESIGN REQUIREMENTS"
    if re.search(r"\b(best|compare|alternatives?|options?|which)\b", t):
        return "IMPLEMENTATION_OPTIONS", "IMPLEMENTATION OPTIONS"
    return "SOURCE_CONSENSUS", "SOURCE CONSENSUS"


def _criteria(text: str) -> List[str]:
    t = text.lower()
    wanted = []
    for key, pat in (
        ("license", r"licen[sc]"),
        ("hardware", r"hardware|gpu|vram|ram|pc|machine|laptop|run locally|local"),
        ("maintenance", r"maintain|active|recent|updated"),
        ("adoption", r"popular|stars|downloads|adoption|community"),
        ("stack", r"compatib|integrat|our copilot|python|javascript|node|stack"),
    ):
        if re.search(pat, t):
            wanted.append(key)
    # sensible defaults — every evaluation covers these, requested or not
    for key in ("license", "maintenance", "adoption", "stack", "hardware"):
        if key not in wanted:
            wanted.append(key)
    return wanted


def _route(text: str, available: List[str]) -> List[str]:
    t = text.lower()
    chosen: List[str] = []

    def want(name: str) -> None:
        if name in available and name not in chosen:
            chosen.append(name)

    if re.search(r"\bgithub|repo|repositor|open[- ]?source\b", t):
        want("github")
    if re.search(r"\bnpm|node|javascript|typescript|js\b", t):
        want("npm")
    if re.search(r"\bpypi|pip|python\b", t):
        want("pypi")
    if re.search(r"\bdocs?\b|documentation|official", t):
        want("docs")
    if re.search(r"\bour (?:code|project|files|repo)|local|codebase|in (?:our|my) project\b", t):
        want("local")
    if not chosen:
        for n in ("github", "web"):
            want(n)
    # always include the general web when it's available and nothing web-ish is picked
    if "web" in available and not any(c in ("web", "docs") for c in chosen):
        want("web")
    # when the request is about packages/tools and only a subset is reachable,
    # also try the package registries (real lookups, cheap)
    for n in ("npm", "pypi"):
        if n in available and re.search(r"\b(tool|library|libraries|package|sdk|framework|agent|model|llm|ai)\b", t):
            want(n)
    return chosen or available[:2]


def _llm_queries(llm: LLM, text: str, providers: List[str]) -> Optional[Dict[str, List[str]]]:
    try:
        raw = llm(
            "You plan web research. Return ONLY compact JSON: an object mapping each provider name to a list "
            "of at most 2 short search queries suited to that provider's search syntax. No prose.",
            f"Providers: {', '.join(providers)}\nRequest: {text}",
        )
        m = re.search(r"\{.*\}", raw or "", re.S)
        if not m:
            return None
        data = json.loads(m.group(0))
        out = {p: [str(q)[:120] for q in (data.get(p) or [])][:2] for p in providers}
        return out if any(out.values()) else None
    except Exception:  # noqa: BLE001 — planning falls back to heuristics
        return None


def make_plan(text: str, available: List[str], llm: Optional[LLM] = None) -> ResearchPlan:
    kws = keywords(text)
    providers = _route(text, available)
    base = " ".join(kws[:4]) or text[:60]
    queries: Dict[str, List[str]] = {}
    for p in providers:
        if p == "github":
            queries[p] = [base]
        elif p == "pypi":
            queries[p] = [" ".join(kws)]  # exact-name lookups of each keyword
        elif p == "local":
            queries[p] = [" ".join(kws[:3])]
        else:
            queries[p] = [base]
    if llm is not None:
        better = _llm_queries(llm, text, [p for p in providers if p not in ("pypi", "local")])
        if better:
            for p, qs in better.items():
                if qs:
                    queries[p] = qs
    kind, kind_title = _artifact_kind(text)
    title = " ".join(w.upper() for w in kws[:4]) or "RESEARCH"
    return ResearchPlan(
        title=title,
        queries=queries,
        artifact_type=kind,
        artifact_title=kind_title,
        keywords=kws,
        criteria=_criteria(text),
    )
