"""jarvis_integration.py — the thin adapter that plugs the research engine
into the JARVIS / MENTIS app (Flask-SocketIO + jarvis_state + jarvis_brain).

Three touch points, all additive (see docs/INTEGRATION.md):

  1. app.py, after `socketio = SocketIO(...)`:
         from mentis_research import jarvis_integration as rx
         rx.install(app, socketio)

  2. jarvis_state.TOOLS: append rx.TOOL_SCHEMA
     jarvis_tools.TOOL_HANDLERS: add "deep_research": rx.handle_deep_research

  3. app.process_message, when building augmented_text, prepend
         rx.context_block()
     so the newest research artifacts feed the next turn.

Follows the project principles: lazy imports of jarvis_* (no cycles), fail
soft everywhere, untrusted text wrapped with st._wrap_untrusted.
"""

from __future__ import annotations

import os
import sys
from typing import List, Optional

from .flask_bridge import latest_context, register
from .models import ContextArtifact, ResearchSession
from .orchestrator import ResearchOrchestrator
from .store import EvidenceStore

_orch: Optional[ResearchOrchestrator] = None

TOOL_SCHEMA = {
    "name": "deep_research",
    "description": (
        "Open the live research workspace and research a question across GitHub, the web, package "
        "registries and project files: discovers sources, inspects each one (README, license, releases, "
        "hardware notes), keeps the strong ones, and distils them into a context artifact the user can see. "
        "Use for any request to research, compare, evaluate or find the best options. Returns immediately; "
        "the findings are delivered as a follow-up turn when research completes."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "The user's research request, in full."}},
        "required": ["query"],
    },
}


def _llm(system: str, user: str) -> str:
    try:
        from jarvis_brain import _utility_call

        return _utility_call(system, user, max_tokens=400, timeout=25.0)
    except Exception:  # noqa: BLE001 — engine falls back to heuristics
        return ""


def _wrap(source: str, text: str) -> str:
    try:
        import jarvis_state as st

        return st._wrap_untrusted(source, text)
    except Exception:  # noqa: BLE001
        return f"<<<BEGIN UNTRUSTED DATA source={source}>>>\n{text}\n<<<END UNTRUSTED DATA>>>"


def _on_complete(sess: ResearchSession, artifacts: List[ContextArtifact], text: str) -> None:
    """The next Copilot stage: hand the artifacts to the brain as a normal
    turn so JARVIS speaks the answer (and memory saves it)."""
    try:
        import jarvis_state as st

        if st.memory is not None and artifacts:
            st.memory.save(f"Research '{sess.query}': {artifacts[-1].summary}", project=st.active_project)
    except Exception:  # noqa: BLE001
        pass
    try:
        import app as jarvis_app

        jarvis_app.process_message(
            f"[Research session {sess.session_id} finished. Answer my original request using the context "
            f"artifacts above; cite the top pick and any unknowns.]\nOriginal request: {sess.query}"
        )
    except Exception as e:  # noqa: BLE001
        print(f"[research] could not hand results to the brain: {e}", file=sys.stderr)


def _followup(prompt: str) -> None:
    try:
        import app as jarvis_app

        jarvis_app.process_message(prompt)
    except Exception as e:  # noqa: BLE001
        print(f"[research] follow-up failed: {e}", file=sys.stderr)


def install(app, socketio, project_root: Optional[str] = None) -> ResearchOrchestrator:
    global _orch
    root = project_root or os.path.dirname(os.path.abspath(getattr(sys.modules.get("__main__"), "__file__", None) or "app.py"))
    _orch = ResearchOrchestrator(
        store=EvidenceStore(persist_dir=os.path.join(root, "memory", "research")),
        llm=_llm,
        wrap=_wrap,
        on_complete=_on_complete,
        project_root=root,
    )
    register(app, socketio, _orch, on_followup=_followup)
    print("[research] live research workspace registered")
    return _orch


def handle_deep_research(query: str) -> str:
    if _orch is None:
        return "The research workspace isn't running, sir."
    sid = _orch.start(query)
    return f"Research workspace open (session {sid}). I'll report back when the sources are in, sir."


def context_block() -> str:
    if _orch is None:
        return ""
    try:
        block = latest_context(_orch, limit=2)
        return f"[Research artifacts — working memory]\n{block}\n\n" if block else ""
    except Exception:  # noqa: BLE001
        return ""
