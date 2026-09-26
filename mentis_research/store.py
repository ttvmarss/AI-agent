"""store.py — EvidenceStore: every source and artifact, with provenance.

In-memory for the live session, plus an append-only JSON snapshot per
session on disk (so artifacts survive a restart and later tools can load
them). Dedup is by canonical URL: the same repository found by two
different queries is ONE source, enriched twice — never two cards.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Dict, List, Optional
from urllib.parse import urlsplit, urlunsplit

from .models import ContextArtifact, ResearchSession, ResearchSource


def canonical_url(url: str) -> str:
    try:
        p = urlsplit(url.strip())
        path = p.path.rstrip("/").lower()
        if path.endswith(".git"):
            path = path[:-4]
        return urlunsplit((p.scheme.lower() or "https", p.netloc.lower().removeprefix("www."), path, "", ""))
    except Exception:  # noqa: BLE001
        return url.strip().lower()


class EvidenceStore:
    def __init__(self, persist_dir: Optional[str] = None) -> None:
        self._lock = threading.RLock()
        self.sessions: Dict[str, ResearchSession] = {}
        self.sources: Dict[str, ResearchSource] = {}
        self.artifacts: Dict[str, ContextArtifact] = {}
        self._by_url: Dict[str, Dict[str, str]] = {}  # session_id -> canonical url -> source_id
        self.persist_dir = persist_dir
        if persist_dir:
            os.makedirs(persist_dir, exist_ok=True)

    # -------------------------------------------------------------- sessions
    def add_session(self, session: ResearchSession) -> None:
        with self._lock:
            self.sessions[session.session_id] = session
            self._by_url.setdefault(session.session_id, {})

    # --------------------------------------------------------------- sources
    def find_duplicate(self, session_id: str, url: str) -> Optional[ResearchSource]:
        with self._lock:
            sid = self._by_url.get(session_id, {}).get(canonical_url(url))
            return self.sources.get(sid) if sid else None

    def add_source(self, src: ResearchSource) -> ResearchSource:
        """Returns the stored source — an existing one when this URL was
        already discovered in this session."""
        with self._lock:
            existing = self.find_duplicate(src.session_id, src.url)
            if existing:
                return existing
            self.sources[src.source_id] = src
            self._by_url.setdefault(src.session_id, {})[canonical_url(src.url)] = src.source_id
            sess = self.sessions.get(src.session_id)
            if sess:
                sess.source_ids.append(src.source_id)
            return src

    def get_source(self, source_id: str) -> Optional[ResearchSource]:
        with self._lock:
            return self.sources.get(source_id)

    def session_sources(self, session_id: str) -> List[ResearchSource]:
        with self._lock:
            sess = self.sessions.get(session_id)
            return [self.sources[s] for s in (sess.source_ids if sess else []) if s in self.sources]

    # ------------------------------------------------------------- artifacts
    def add_artifact(self, art: ContextArtifact) -> None:
        with self._lock:
            self.artifacts[art.id] = art
            sess = self.sessions.get(art.research_session_id)
            if sess:
                sess.artifact_ids.append(art.id)
        self.persist(art.research_session_id)

    def get_artifact(self, artifact_id: str) -> Optional[ContextArtifact]:
        with self._lock:
            return self.artifacts.get(artifact_id)

    def latest_artifacts(self, limit: int = 5) -> List[ContextArtifact]:
        with self._lock:
            return sorted(self.artifacts.values(), key=lambda a: a.created_at, reverse=True)[:limit]

    # ----------------------------------------------------------- persistence
    def persist(self, session_id: str) -> None:
        if not self.persist_dir:
            return
        try:
            with self._lock:
                sess = self.sessions.get(session_id)
                if not sess:
                    return
                snapshot = {
                    "session": sess.to_dict(),
                    "sources": [s.detail() for s in self.session_sources(session_id)],
                    "artifacts": [self.artifacts[a].to_dict() for a in sess.artifact_ids if a in self.artifacts],
                }
            path = os.path.join(self.persist_dir, f"{session_id}.json")
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(snapshot, f, indent=1, default=str)
            os.replace(tmp, path)
        except Exception as e:  # noqa: BLE001 — persistence is best-effort
            print(f"[research] persist failed: {e}")
