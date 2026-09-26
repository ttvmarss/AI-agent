"""models.py — the data shapes every other research module shares.

Plain dataclasses, no behaviour beyond serialisation. A ResearchSource is the
single traceable record for one real result: it is created ONCE when a
provider returns it and then enriched in place as inspection learns more —
the UI mirrors that by updating one card, never spawning a duplicate.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def now() -> float:
    return time.time()


# Card / source lifecycle. The UI maps each state to a position + depth, not
# just a colour (see static/research.js LAYOUT).
class SourceState:
    DISCOVERED = "discovered"
    QUEUED = "queued"
    INSPECTING = "inspecting"
    VERIFYING = "verifying"
    USEFUL = "useful"
    SELECTED = "selected"
    REJECTED = "rejected"
    FAILED = "failed"  # the source itself could not be loaded — shown honestly


@dataclass
class Fact:
    """One extracted fact, always tied to where it came from."""

    label: str
    value: str
    origin: str  # e.g. "npm registry metadata", "README", "GitHub API /releases"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ResearchSource:
    source_id: str
    session_id: str
    provider: str  # "github" | "web" | "npm" | "pypi" | "local" ...
    source_type: str  # "repository" | "package" | "webpage" | "file" ...
    title: str
    url: str
    retrieved_at: float
    query: str = ""
    snippet: str = ""
    favicon: str = ""
    image: str = ""
    # provider-specific metadata; the frontend renders known keys and
    # ignores the rest — it is never coupled to one provider.
    meta: Dict[str, Any] = field(default_factory=dict)
    raw_metadata: Dict[str, Any] = field(default_factory=dict)
    facts: List[Fact] = field(default_factory=list)
    preview: str = ""  # real fetched text excerpt (README / page body)
    state: str = SourceState.DISCOVERED
    inspection_status: str = "pending"  # pending | running | done | failed
    verification_status: str = "pending"  # pending | passed | failed | skipped
    relevance: Optional[float] = None
    reasons: List[str] = field(default_factory=list)
    error: str = ""

    def add_fact(self, label: str, value: Any, origin: str) -> Optional[Fact]:
        if value is None or value == "":
            return None  # never invent: unknown values simply aren't recorded
        for f in self.facts:
            if f.label == label:
                f.value, f.origin = str(value), origin
                return f
        fact = Fact(label=label, value=str(value), origin=origin)
        self.facts.append(fact)
        return fact

    def card(self) -> Dict[str, Any]:
        """The UI-facing projection (no raw metadata — that's fetched on demand)."""
        return {
            "source_id": self.source_id,
            "session_id": self.session_id,
            "provider": self.provider,
            "source_type": self.source_type,
            "title": self.title,
            "url": self.url,
            "retrieved_at": self.retrieved_at,
            "snippet": self.snippet,
            "favicon": self.favicon,
            "image": self.image,
            "meta": self.meta,
            "facts": [f.to_dict() for f in self.facts],
            "state": self.state,
            "inspection_status": self.inspection_status,
            "verification_status": self.verification_status,
            "relevance": self.relevance,
            "reasons": list(self.reasons),
            "error": self.error,
        }

    def detail(self) -> Dict[str, Any]:
        d = self.card()
        d["raw_metadata"] = self.raw_metadata
        d["preview"] = self.preview
        d["query"] = self.query
        return d


@dataclass
class ContextArtifact:
    """Structured working memory produced by a research stage.

    The next stage consumes these directly (see ArtifactBuilder.to_context and
    the evaluation stage in orchestrator.py). Every finding carries the
    source ids it was drawn from, so claims stay traceable.
    """

    id: str
    type: str  # INTEGRATION_CANDIDATES | MODEL_COMPARISON | SOURCE_CONSENSUS ...
    title: str
    research_session_id: str
    summary: str
    findings: List[Dict[str, Any]]  # {title, detail, source_ids[]}
    evidence_ids: List[str]
    source_ids: List[str]
    created_at: float
    confidence_metadata: Dict[str, Any] = field(default_factory=dict)
    derived_from: List[str] = field(default_factory=list)  # parent artifact ids

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ResearchSession:
    session_id: str
    task_id: str
    query: str
    title: str
    created_at: float
    status: str = "running"  # running | paused | stopping | stopped | completed | failed
    stage: str = "research"  # research | selection | artifact | evaluation | response | done
    source_ids: List[str] = field(default_factory=list)
    artifact_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
