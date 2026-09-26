"""ranker.py — ResearchRanker: explainable scoring from gathered facts.

Two passes:
  triage(src)  — right after discovery, from search-result metadata only.
                 Clearly irrelevant / dead results are rejected early.
  final(src)   — after inspection + verification, adding README evidence.

Every score comes with human-readable reasons (shown on the card and in the
source viewer). No hidden weighting that the UI can't explain.
"""

from __future__ import annotations

import math
import re
from typing import List, Tuple

from .models import ResearchSource

TRIAGE_REJECT_BELOW = 0.18
USEFUL_AT_LEAST = 0.40


def _terms(text: str) -> set:
    return set(re.findall(r"[a-z0-9][a-z0-9+#-]{1,}", (text or "").lower()))


def _popularity(src: ResearchSource) -> Tuple[float, str]:
    m = src.meta
    if isinstance(m.get("stars"), int):
        s = m["stars"]
        return min(1.0, math.log10(s + 1) / 5.0), f"{s:,} stars"
    if isinstance(m.get("weekly_downloads"), int):
        d = m["weekly_downloads"]
        return min(1.0, math.log10(d + 1) / 6.0), f"{d:,} weekly downloads"
    return 0.0, ""


class ResearchRanker:
    def __init__(self, keywords: List[str]) -> None:
        self.kw = [k.lower() for k in keywords if k]

    def _overlap(self, text: str) -> float:
        if not self.kw:
            return 0.5
        t = _terms(text)
        joined = (text or "").lower()
        hit = sum(1 for k in self.kw if k in t or k in joined)
        return hit / len(self.kw)

    def triage(self, src: ResearchSource) -> Tuple[float, List[str], bool]:
        """Returns (score, reasons, keep)."""
        m = src.meta
        blob = " ".join([src.title, src.snippet, " ".join(m.get("topics") or []), " ".join(m.get("keywords") or [])])
        rel = self._overlap(blob)
        pop, pop_reason = _popularity(src)
        score = 0.7 * rel + 0.3 * pop
        reasons = [f"Query match {round(rel * 100)}%"]
        if pop_reason:
            reasons.append(pop_reason)
        keep = True
        if m.get("archived"):
            keep, score = False, score * 0.3
            reasons.append("Archived repository")
        if m.get("deprecated"):
            keep, score = False, score * 0.3
            reasons.append("Deprecated package")
        if src.provider != "local" and rel == 0:
            keep = False
            reasons.append("No overlap with the request")
        elif score < TRIAGE_REJECT_BELOW:
            keep = False
            reasons.append("Weak relevance signal")
        return round(score, 3), reasons, keep

    def final(self, src: ResearchSource, verified: bool) -> Tuple[float, List[str]]:
        m = src.meta
        base = src.relevance or 0.0
        readme_rel = self._overlap(src.preview[:8000]) if src.preview else 0.0
        pop, _ = _popularity(src)
        age = m.get("days_since_update")
        fresh = 0.5 if age is None else max(0.0, 1.0 - age / 730.0)
        from .providers.base import license_class

        lic = {"permissive": 1.0, "other": 0.6, "copyleft": 0.45, "unknown": 0.25}[license_class(m.get("license"))]
        if src.provider == "local":
            lic = 1.0
        docs = min(1.0, (m.get("readme_chars") or 0) / 4000.0)
        score = 0.30 * base + 0.25 * readme_rel + 0.15 * pop + 0.12 * fresh + 0.10 * lic + 0.08 * docs
        if not verified:
            score *= 0.5
        reasons = [f"Documentation relevance {round(readme_rel * 100)}%"]
        return round(score, 3), reasons
