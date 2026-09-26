"""artifacts.py — ArtifactBuilder: selected evidence -> ContextArtifact.

The artifact is the hand-off object: later stages (evaluation, the final
answer, any follow-up turn) consume `to_context(artifact)` instead of
re-reading raw search results. Every finding keeps the source ids it came
from, and evidence ids point at individual facts ("<source_id>#<label>").
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional

from .models import ContextArtifact, ResearchSource, new_id, now

LLM = Callable[[str, str], str]
Wrap = Callable[[str, str], str]

_KEY_FACTS = ("License", "Stars", "Weekly downloads", "Language", "Latest release", "Last push",
              "Min VRAM mentioned", "Min RAM mentioned", "Platforms mentioned", "Requires Python", "Node engine")


def _fact_map(src: ResearchSource) -> Dict[str, str]:
    return {f.label: f.value for f in src.facts}


def _finding_for(src: ResearchSource) -> Dict:
    facts = _fact_map(src)
    bits = [f"{k}: {facts[k]}" for k in _KEY_FACTS if k in facts]
    return {
        "title": src.title,
        "detail": (facts.get("README summary") or src.snippet or "")[:260],
        "key_facts": bits[:6],
        "url": src.url,
        "provider": src.provider,
        "score": src.relevance,
        "reasons": src.reasons[:5],
        "source_ids": [src.source_id],
    }


def _default_wrap(source: str, text: str) -> str:
    return f"<<<BEGIN UNTRUSTED DATA source={source}>>>\n{text}\n<<<END UNTRUSTED DATA>>>"


class ArtifactBuilder:
    def __init__(self, llm: Optional[LLM] = None, wrap: Optional[Wrap] = None) -> None:
        self.llm = llm
        self.wrap = wrap or _default_wrap

    def research_artifact(self, *, session_id: str, kind: str, title: str, query: str,
                          selected: List[ResearchSource], all_sources: List[ResearchSource]) -> ContextArtifact:
        findings = [_finding_for(s) for s in selected]
        evidence = [f"{s.source_id}#{f.label}" for s in selected for f in s.facts if f.label in _KEY_FACTS or f.label == "README summary"]
        rejected = [s for s in all_sources if s.state == "rejected"]
        failed = [s for s in all_sources if s.state == "failed"]
        inspected = [s for s in all_sources if s.inspection_status in ("done", "failed")]
        method = "heuristic"
        summary = ""
        if self.llm and findings:
            body = "\n".join(f"- {f['title']}: {f['detail']} [{'; '.join(f['key_facts'])}]" for f in findings)
            summary = (self.llm(
                "Summarise these research findings in 2-3 plain sentences for the user's request. Use only the "
                "data given. Do not invent numbers. Return ONLY the summary.",
                f"Request: {query}\n\n{self.wrap('research findings', body)}",
            ) or "").strip()
            method = "llm-assisted" if summary else "heuristic"
        if not summary:
            if findings:
                names = ", ".join(f["title"] for f in findings)
                summary = (f"{len(findings)} of {len(all_sources)} discovered sources were retained after "
                           f"inspection: {names}.")
            else:
                summary = f"None of the {len(all_sources)} discovered sources passed inspection."
        return ContextArtifact(
            id=new_id("art"),
            type=kind,
            title=title,
            research_session_id=session_id,
            summary=summary,
            findings=findings,
            evidence_ids=evidence,
            source_ids=[s.source_id for s in selected],
            created_at=now(),
            confidence_metadata={
                "method": method,
                "discovered": len(all_sources),
                "inspected": len(inspected),
                "rejected": len(rejected),
                "failed": len(failed),
                "selected": len(selected),
                "verification": {s.source_id: s.verification_status for s in selected},
            },
        )


def to_context(art: ContextArtifact, wrap: Optional[Wrap] = None) -> str:
    """Compact text form for a model prompt. Findings contain third-party
    text (README summaries), so the whole block is wrapped as untrusted."""
    wrap = wrap or _default_wrap
    lines = [f"[Context artifact {art.id} · {art.type} · {art.title}]", art.summary]
    for i, f in enumerate(art.findings, 1):
        lines.append(f"{i}. {f['title']} ({f.get('url', '')})")
        if f.get("detail"):
            lines.append(f"   {f['detail']}")
        if f.get("key_facts"):
            lines.append("   " + "; ".join(f["key_facts"]))
        if f.get("verdicts"):
            lines.append("   " + "; ".join(f"{k}: {v}" for k, v in f["verdicts"].items()))
    return wrap(f"context artifact {art.type}", "\n".join(lines))
