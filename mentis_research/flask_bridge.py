"""flask_bridge.py — wires the research engine onto the EXISTING Flask +
Socket.IO server (no new transport, no polling).

Server -> client:  "research_event"   one event per emit, in seq order
Client -> server:  "research_start"          {text}
                   "research_control"        {session_id, action: pause|resume|stop}
                   "research_source_action"  {session_id, source_id, action: pin|unpin|dismiss}
                   "research_source_detail"  {source_id}            -> ack(detail)
                   "research_replay"         {since}                -> ack([events])
                   "research_followup"       {session_id, source_ids[], text}
Static:            /research-static/research.css|research.js
"""

from __future__ import annotations

import os
import sys
import threading
from typing import Callable, Optional

from flask import jsonify, send_from_directory

from .artifacts import to_context
from .orchestrator import ResearchOrchestrator

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


def register(app, socketio, orchestrator: ResearchOrchestrator,
             on_followup: Optional[Callable[[str], None]] = None) -> None:
    bus = orchestrator.bus
    store = orchestrator.store

    def forward(event):
        socketio.emit("research_event", event)

    bus.subscribe(forward)

    @app.route("/research-static/<path:filename>")
    def _research_static(filename):
        return send_from_directory(STATIC_DIR, filename)

    @app.route("/research/artifacts/<artifact_id>")
    def _research_artifact(artifact_id):
        art = store.get_artifact(artifact_id)
        return (jsonify(art.to_dict()), 200) if art else (jsonify({"error": "not found"}), 404)

    @app.route("/research/sessions/<session_id>")
    def _research_session(session_id):
        sess = store.sessions.get(session_id)
        if not sess:
            return jsonify({"error": "not found"}), 404
        return jsonify({
            "session": sess.to_dict(),
            "sources": [s.card() for s in store.session_sources(session_id)],
            "artifacts": [store.artifacts[a].to_dict() for a in sess.artifact_ids if a in store.artifacts],
        })

    @socketio.on("research_start")
    def _start(data):
        try:
            text = ((data or {}).get("text") or "").strip()
            if text:
                threading.Thread(target=orchestrator.start, args=(text,), daemon=True).start()
        except Exception as e:  # noqa: BLE001
            print(f"[research] start error: {e}", file=sys.stderr)

    @socketio.on("research_control")
    def _control(data):
        try:
            sid, action = (data or {}).get("session_id"), (data or {}).get("action")
            fn = {"pause": orchestrator.pause, "resume": orchestrator.resume, "stop": orchestrator.stop}.get(action)
            return {"ok": bool(fn and sid and fn(sid))}
        except Exception as e:  # noqa: BLE001
            print(f"[research] control error: {e}", file=sys.stderr)
            return {"ok": False}

    @socketio.on("research_source_action")
    def _source_action(data):
        try:
            d = data or {}
            return {"ok": orchestrator.source_action(d.get("session_id"), d.get("source_id"), d.get("action"))}
        except Exception as e:  # noqa: BLE001
            print(f"[research] source action error: {e}", file=sys.stderr)
            return {"ok": False}

    @socketio.on("research_source_detail")
    def _detail(data):
        src = store.get_source((data or {}).get("source_id", ""))
        return src.detail() if src else {"error": "not found"}

    @socketio.on("research_replay")
    def _replay(data):
        return bus.since(int((data or {}).get("since") or 0))

    @socketio.on("research_followup")
    def _followup(data):
        try:
            d = data or {}
            srcs = [store.get_source(s) for s in d.get("source_ids") or []]
            srcs = [s for s in srcs if s]
            question = (d.get("text") or "").strip() or "Tell me more about this source."
            block = followup_context(srcs, orchestrator.wrap)
            prompt = f"{block}\n\n{question}" if block else question
            if on_followup:
                threading.Thread(target=on_followup, args=(prompt,), daemon=True).start()
            else:
                orchestrator.start(f"{question} {' '.join(s.title for s in srcs)}")
        except Exception as e:  # noqa: BLE001
            print(f"[research] followup error: {e}", file=sys.stderr)


def followup_context(sources, wrap=None) -> str:
    if not sources:
        return ""
    lines = []
    for s in sources:
        facts = "; ".join(f"{f.label}: {f.value}" for f in s.facts[:10])
        lines.append(f"- {s.title} ({s.url}) [{s.provider}] {facts}")
    body = "\n".join(lines)
    if wrap:
        return wrap("research sources the user selected", body)
    return f"<<<BEGIN UNTRUSTED DATA source=research sources>>>\n{body}\n<<<END UNTRUSTED DATA>>>"


def latest_context(orchestrator: ResearchOrchestrator, limit: int = 2) -> str:
    """Context block of the newest artifacts — prepend to the next turn so
    research becomes working memory for later tools."""
    arts = orchestrator.store.latest_artifacts(limit)
    return "\n\n".join(to_context(a, orchestrator.wrap) for a in arts)
