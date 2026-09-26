"""mentis_research — live, event-driven visual research for the JARVIS/MENTIS copilot.

Backend:  ResearchOrchestrator -> providers (GitHub, web, docs, npm, PyPI,
          local files) -> SourceInspector steps -> ResearchRanker ->
          ArtifactBuilder -> Evaluator; every step published on the
          ResearchEventBus and streamed over the app's existing Socket.IO.
Frontend: static/research.js + research.css render the workspace from those
          events only.
"""

from .events import EVENT_TYPES, ResearchEventBus
from .models import ContextArtifact, ResearchSession, ResearchSource, SourceState
from .orchestrator import ResearchOrchestrator
from .planner import make_plan, needs_research
from .store import EvidenceStore

__all__ = [
    "EVENT_TYPES",
    "ContextArtifact",
    "EvidenceStore",
    "ResearchEventBus",
    "ResearchOrchestrator",
    "ResearchSession",
    "ResearchSource",
    "SourceState",
    "make_plan",
    "needs_research",
]
