"""events.py — ResearchEventBus: the ONLY way research state reaches the UI.

Every visual change in the research workspace is driven by one of these
events, and every event is emitted by code that just did (or just observed)
the thing it describes. There are no timers here and no synthetic events.

Each event gets a monotonically increasing `seq` so the frontend can detect
gaps and replay (a reconnecting client asks for everything after its last
seq — see flask_bridge.py `research_replay`).
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Callable, Deque, Dict, List, Optional

# The full vocabulary. Emitting anything else raises in tests (and is
# dropped with a log line at runtime) so the contract stays explicit.
EVENT_TYPES = frozenset(
    {
        "task.started",
        "task.completed",
        "research.session.started",
        "research.session.paused",
        "research.session.resumed",
        "research.session.stopped",
        "research.query.started",
        "research.query.completed",
        "research.query.failed",
        "research.result.discovered",
        "research.source.queued",
        "research.source.inspecting",
        "research.source.metadata_updated",
        "research.source.verifying",
        "research.source.useful",
        "research.source.rejected",
        "research.source.selected",
        "research.source.failed",
        "research.progress.updated",
        "research.activity",
        "research.artifact.creating",
        "research.artifact.created",
        "research.completed",
        "stage.changed",
        "benchmark.started",
        "benchmark.result",
        "benchmark.completed",
        "tool.started",
        "tool.completed",
        "response.ready",
    }
)

Listener = Callable[[Dict[str, Any]], None]


class ResearchEventBus:
    def __init__(self, history: int = 4000, strict: bool = False) -> None:
        self._lock = threading.Lock()
        self._seq = 0
        self._listeners: List[Listener] = []
        self._history: Deque[Dict[str, Any]] = deque(maxlen=history)
        self._strict = strict

    def subscribe(self, fn: Listener) -> Callable[[], None]:
        with self._lock:
            self._listeners.append(fn)

        def _unsub() -> None:
            with self._lock:
                if fn in self._listeners:
                    self._listeners.remove(fn)

        return _unsub

    def emit(self, type_: str, session_id: Optional[str] = None, **data: Any) -> Optional[Dict[str, Any]]:
        if type_ not in EVENT_TYPES:
            if self._strict:
                raise ValueError(f"unknown research event type: {type_}")
            print(f"[research] dropped unknown event type {type_!r}")
            return None
        with self._lock:
            self._seq += 1
            event = {"seq": self._seq, "type": type_, "ts": time.time(), "session_id": session_id, "data": data}
            self._history.append(event)
            listeners = list(self._listeners)
        for fn in listeners:
            try:
                fn(event)
            except Exception as e:  # noqa: BLE001 — a broken listener must never stop research
                print(f"[research] listener error on {type_}: {e}")
        return event

    def since(self, seq: int, session_id: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            return [
                e for e in self._history if e["seq"] > seq and (session_id is None or e["session_id"] == session_id)
            ]

    @property
    def last_seq(self) -> int:
        with self._lock:
            return self._seq
