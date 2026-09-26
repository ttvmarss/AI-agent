"""orchestrator.py — ResearchOrchestrator: runs one research session end to end.

    request -> plan -> parallel provider searches (results stream one by one)
            -> triage (weak results rejected early)
            -> inspection, one source at a time (cards enrich in place)
            -> verification -> useful / rejected -> progressive selection
            -> ContextArtifact (research distilled)
            -> evaluation stage consumes the artifact (measured checks)
            -> comparison artifact -> final response -> on_complete hook

Every event is emitted by the code path that performs the action it names.
Pause/stop are honoured at every checkpoint between network calls.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Dict, List, Optional

from .artifacts import ArtifactBuilder, to_context
from .evaluation import Evaluator, host_profile
from .events import ResearchEventBus
from .models import ContextArtifact, ResearchSession, ResearchSource, SourceState, new_id, now
from .planner import LLM, ResearchPlan, make_plan
from .providers import InspectContext, ProviderError, SearchProviderAdapter, build_providers
from .ranker import USEFUL_AT_LEAST, ResearchRanker
from .store import EvidenceStore

STRONG_SELECT_AT = 0.52  # select immediately when a verified source scores this high


class StopResearch(Exception):
    pass


class SessionControl:
    def __init__(self) -> None:
        self.running = threading.Event()
        self.running.set()
        self.stopped = False

    def checkpoint(self) -> None:
        if self.stopped:
            raise StopResearch()
        while not self.running.wait(timeout=0.25):
            if self.stopped:
                raise StopResearch()
        if self.stopped:
            raise StopResearch()


class ResearchOrchestrator:
    def __init__(
        self,
        bus: Optional[ResearchEventBus] = None,
        store: Optional[EvidenceStore] = None,
        providers: Optional[Dict[str, SearchProviderAdapter]] = None,
        llm: Optional[LLM] = None,
        wrap: Optional[Callable[[str, str], str]] = None,
        on_complete: Optional[Callable[[ResearchSession, List[ContextArtifact], str], None]] = None,
        project_root: Optional[str] = None,
        results_per_query: int = 10,
        inspect_n: int = 6,
        select_k: int = 3,
    ) -> None:
        self.bus = bus or ResearchEventBus()
        self.store = store or EvidenceStore()
        self.providers = providers if providers is not None else build_providers()
        self.llm = llm
        self.wrap = wrap
        self.on_complete = on_complete
        self.project_root = project_root
        self.results_per_query = results_per_query
        self.inspect_n = inspect_n
        self.select_k = select_k
        self.controls: Dict[str, SessionControl] = {}
        self._threads: Dict[str, threading.Thread] = {}

    # ----------------------------------------------------------------- API
    def start(self, text: str, task_id: Optional[str] = None, block: bool = False) -> str:
        plan = make_plan(text, list(self.providers), self.llm)
        sess = ResearchSession(
            session_id=new_id("rs"), task_id=task_id or new_id("task"), query=text, title=plan.title, created_at=now()
        )
        self.store.add_session(sess)
        ctl = SessionControl()
        self.controls[sess.session_id] = ctl
        t = threading.Thread(target=self._run, args=(sess, plan, ctl), daemon=True, name=f"research-{sess.session_id}")
        self._threads[sess.session_id] = t
        t.start()
        if block:
            t.join()
        return sess.session_id

    def wait(self, session_id: str, timeout: Optional[float] = None) -> bool:
        t = self._threads.get(session_id)
        if t:
            t.join(timeout)
            return not t.is_alive()
        return True

    def pause(self, session_id: str) -> bool:
        ctl, sess = self.controls.get(session_id), self.store.sessions.get(session_id)
        if not ctl or not sess or sess.status != "running":
            return False
        ctl.running.clear()
        sess.status = "paused"
        self.bus.emit("research.session.paused", session_id)
        self._activity(session_id, "Research paused by you", "control")
        return True

    def resume(self, session_id: str) -> bool:
        ctl, sess = self.controls.get(session_id), self.store.sessions.get(session_id)
        if not ctl or not sess or sess.status != "paused":
            return False
        sess.status = "running"
        ctl.running.set()
        self.bus.emit("research.session.resumed", session_id)
        self._activity(session_id, "Research resumed", "control")
        return True

    def stop(self, session_id: str) -> bool:
        ctl, sess = self.controls.get(session_id), self.store.sessions.get(session_id)
        if not ctl or not sess or sess.status not in ("running", "paused"):
            return False
        sess.status = "stopping"
        ctl.stopped = True
        ctl.running.set()
        return True

    def source_action(self, session_id: str, source_id: str, action: str) -> bool:
        src = self.store.get_source(source_id)
        if not src or src.session_id != session_id:
            return False
        if action == "pin":
            src.meta["pinned"] = True
            self.bus.emit("research.source.metadata_updated", session_id, source=src.card(), changed=["pinned"])
            self._activity(session_id, f"Pinned — {src.title}", "control", source_id)
        elif action == "unpin":
            src.meta["pinned"] = False
            self.bus.emit("research.source.metadata_updated", session_id, source=src.card(), changed=["pinned"])
        elif action == "dismiss":
            src.meta["dismissed"] = True
            if src.state not in (SourceState.REJECTED, SourceState.FAILED):
                src.state = SourceState.REJECTED
                src.reasons.insert(0, "Dismissed by you")
                self.bus.emit("research.source.rejected", session_id, source=src.card(), reasons=src.reasons[:4], by="user")
                self._activity(session_id, f"Dismissed — {src.title}", "control", source_id)
        else:
            return False
        return True

    # ------------------------------------------------------------ helpers
    def _activity(self, sid: str, text: str, kind: str = "info", source_id: Optional[str] = None) -> None:
        self.bus.emit("research.activity", sid, text=text, kind=kind, source_id=source_id)

    def _progress(self, sess: ResearchSession, phase: str, percent: float) -> None:
        counts: Dict[str, int] = {}
        for s in self.store.session_sources(sess.session_id):
            counts[s.state] = counts.get(s.state, 0) + 1
        self.bus.emit(
            "research.progress.updated", sess.session_id, phase=phase, percent=round(max(0, min(100, percent)), 1),
            counts=counts, discovered=sum(counts.values()),
        )

    def _set_stage(self, sess: ResearchSession, stage: str, label: str) -> None:
        sess.stage = stage
        self.bus.emit("stage.changed", sess.session_id, stage=stage, label=label)

    # ---------------------------------------------------------------- run
    def _run(self, sess: ResearchSession, plan: ResearchPlan, ctl: SessionControl) -> None:
        sid = sess.session_id
        bus = self.bus
        ranker = ResearchRanker(plan.keywords)
        artifacts: List[ContextArtifact] = []
        try:
            bus.emit("task.started", sid, task_id=sess.task_id, title=plan.title, query=sess.query)
            bus.emit(
                "research.session.started", sid, title=plan.title, query=sess.query,
                providers=[{"name": p, "label": self.providers[p].label} for p in plan.queries],
                queries=plan.queries, artifact_type=plan.artifact_type, artifact_title=plan.artifact_title,
                criteria=plan.criteria,
            )
            self._set_stage(sess, "research", "RESEARCH")
            self._search_phase(sess, plan, ctl, ranker)

            queue = self._inspection_queue(sess)
            self._inspect_phase(sess, plan, ctl, ranker, queue)

            selected = self._finalize_selection(sess, plan)
            ctl.checkpoint()

            # ------------------------------------------ distil -> artifact
            self._set_stage(sess, "artifact", plan.artifact_title)
            bus.emit("research.artifact.creating", sid, artifact_type=plan.artifact_type, title=plan.artifact_title,
                     source_ids=[s.source_id for s in selected])
            self._activity(sid, f"Distilling {len(selected)} sources into {plan.artifact_title}", "artifact")
            builder = ArtifactBuilder(self.llm, self.wrap)
            art = builder.research_artifact(
                session_id=sid, kind=plan.artifact_type, title=plan.artifact_title, query=sess.query,
                selected=selected, all_sources=self.store.session_sources(sid),
            )
            self.store.add_artifact(art)
            artifacts.append(art)
            bus.emit("research.artifact.created", sid, artifact=art.to_dict())
            self._progress(sess, "artifact", 82)
            ctl.checkpoint()

            # --------------------------------- next stage consumes artifact
            if selected:
                artifacts.append(self._evaluation_phase(sess, plan, ctl, art, selected))

            # ------------------------------------------------ final response
            self._set_stage(sess, "response", "RESPONSE")
            text = self._compose_response(sess, artifacts)
            bus.emit("response.ready", sid, text=text, artifact_ids=[a.id for a in artifacts])
            sess.status, sess.stage = "completed", "done"
            self._progress(sess, "done", 100)
            bus.emit("research.completed", sid, artifact_ids=[a.id for a in artifacts],
                     selected=[s.source_id for s in selected])
            bus.emit("task.completed", sid, task_id=sess.task_id, status="completed")
            self.store.persist(sid)
            if self.on_complete:
                try:
                    self.on_complete(sess, artifacts, text)
                except Exception as e:  # noqa: BLE001
                    print(f"[research] on_complete hook failed: {e}")
        except StopResearch:
            sess.status = "stopped"
            bus.emit("research.session.stopped", sid, stage=sess.stage)
            self._activity(sid, "Research stopped by you", "control")
            bus.emit("task.completed", sid, task_id=sess.task_id, status="stopped")
            self.store.persist(sid)
        except Exception as e:  # noqa: BLE001 — a crashed session must say so, never hang the UI
            sess.status = "failed"
            self._activity(sid, f"Research failed — {type(e).__name__}: {str(e)[:120]}", "error")
            bus.emit("task.completed", sid, task_id=sess.task_id, status="failed", error=str(e)[:200])
            self.store.persist(sid)

    # ------------------------------------------------------------- search
    def _search_phase(self, sess: ResearchSession, plan: ResearchPlan, ctl: SessionControl, ranker: ResearchRanker) -> None:
        sid = sess.session_id
        jobs = [(p, q) for p, qs in plan.queries.items() for q in qs]
        done = {"n": 0}
        lock = threading.Lock()

        def run(provider_name: str, query: str) -> None:
            prov = self.providers[provider_name]
            qid = new_id("q")
            ctl.checkpoint()
            self.bus.emit("tool.started", sid, tool=f"search.{provider_name}", query_id=qid)
            self.bus.emit("research.query.started", sid, query_id=qid, provider=provider_name, label=prov.label, query=query)
            self._activity(sid, f"Searching {prov.label} — “{query}”", "search")
            found = 0
            try:
                for hit in prov.search(query, self.results_per_query):
                    ctl.checkpoint()
                    found += 1
                    src = ResearchSource(
                        source_id=new_id("src"), session_id=sid, provider=provider_name, source_type=hit.source_type,
                        title=hit.title, url=hit.url, retrieved_at=now(), query=query, snippet=hit.snippet,
                        favicon=hit.favicon, image=hit.image, meta=dict(hit.meta), raw_metadata=hit.raw,
                    )
                    stored = self.store.add_source(src)
                    if stored is not src:  # same URL already on screen — enrich, don't duplicate
                        also = stored.meta.setdefault("also_found_by", [])
                        if query not in also:
                            also.append(query)
                        self.bus.emit("research.source.metadata_updated", sid, source=stored.card(), changed=["also_found_by"])
                        continue
                    score, reasons, keep = ranker.triage(src)
                    src.relevance, src.reasons = score, reasons
                    self.bus.emit("research.result.discovered", sid, source=src.card(), query_id=qid)
                    if keep:
                        src.state = SourceState.QUEUED
                        self.bus.emit("research.source.queued", sid, source=src.card())
                    else:
                        src.state = SourceState.REJECTED
                        self.bus.emit("research.source.rejected", sid, source=src.card(), reasons=reasons, by="triage")
                self.bus.emit("research.query.completed", sid, query_id=qid, provider=provider_name, count=found)
                noun = {"repository": "repositories", "package": "packages", "file": "files"}.get(prov.source_type, "results")
                self._activity(sid, f"{found} {noun} discovered on {prov.label}", "result")
            except StopResearch:
                raise
            except ProviderError as e:
                self.bus.emit("research.query.failed", sid, query_id=qid, provider=provider_name, error=str(e))
                self._activity(sid, f"{prov.label} search failed — {e}", "error")
            except Exception as e:  # noqa: BLE001
                self.bus.emit("research.query.failed", sid, query_id=qid, provider=provider_name, error=f"{type(e).__name__}: {e}")
                self._activity(sid, f"{prov.label} search failed — {type(e).__name__}", "error")
            finally:
                self.bus.emit("tool.completed", sid, tool=f"search.{provider_name}", query_id=qid, count=found)
                with lock:
                    done["n"] += 1
                    pct = 30.0 * done["n"] / max(1, len(jobs))
                self._progress(sess, "search", pct)

        with ThreadPoolExecutor(max_workers=max(1, min(4, len(jobs)))) as pool:
            futures = [pool.submit(run, p, q) for p, q in jobs]
            for f in futures:
                f.result()  # re-raises StopResearch

    # --------------------------------------------------------- inspection
    def _inspection_queue(self, sess: ResearchSession) -> List[ResearchSource]:
        queued = [s for s in self.store.session_sources(sess.session_id) if s.state == SourceState.QUEUED]
        queued.sort(key=lambda s: -(s.relevance or 0))
        keep, cut = queued[: self.inspect_n], queued[self.inspect_n:]
        for s in cut:
            s.state = SourceState.REJECTED
            s.reasons.append(f"Ranked below the top {self.inspect_n} — not inspected")
            self.bus.emit("research.source.rejected", sess.session_id, source=s.card(), reasons=s.reasons[-2:], by="cutoff")
        if keep:
            self._activity(sess.session_id, f"{len(keep)} candidates queued for inspection", "info")
        return keep

    def _inspect_phase(self, sess, plan, ctl, ranker, queue: List[ResearchSource]) -> None:
        sid = sess.session_id
        n_sel = 0
        for i, src in enumerate(queue):
            ctl.checkpoint()
            if src.meta.get("dismissed"):
                continue
            prov = self.providers[src.provider]
            src.state, src.inspection_status = SourceState.INSPECTING, "running"
            self.bus.emit("research.source.inspecting", sid, source=src.card())
            self._activity(sid, f"Opening {prov.source_type} — {src.title}", "inspect", src.source_id)

            def step(text: str, _sid=src.source_id) -> None:
                ctl.checkpoint()
                self._activity(sid, text, "inspect", _sid)

            def update(changed: List[str], _src=src) -> None:
                self.bus.emit("research.source.metadata_updated", sid, source=_src.card(), changed=[c for c in changed if c])

            try:
                prov.inspect(src, InspectContext(step=step, update=update, checkpoint=ctl.checkpoint))
                src.inspection_status = "done"
            except StopResearch:
                raise
            except Exception as e:  # noqa: BLE001 — shown honestly on the card
                src.inspection_status = "failed"
                src.state = SourceState.FAILED
                src.error = src.error or f"{type(e).__name__}: {str(e)[:140]}"
                self.bus.emit("research.source.failed", sid, source=src.card(), error=src.error)
                self._activity(sid, f"Could not load {src.title} — {src.error}", "error", src.source_id)
                self._progress(sess, "inspect", 30 + 50 * (i + 1) / max(1, len(queue)))
                continue
            ctl.checkpoint()
            if src.meta.get("dismissed"):
                continue

            twin = self._same_project(src)
            if twin is not None:
                src.state = SourceState.REJECTED
                src.reasons.insert(0, f"Same source repo as {twin.title} ({src.meta.get('github_repo')})")
                self.bus.emit("research.source.rejected", sid, source=src.card(), reasons=src.reasons[:2], by="duplicate")
                self._activity(sid, f"Candidate rejected — {src.title}: duplicate of {twin.title}", "reject", src.source_id)
                self._progress(sess, "inspect", 30 + 50 * (i + 1) / max(1, len(queue)))
                continue

            src.state = SourceState.VERIFYING
            self.bus.emit("research.source.verifying", sid, source=src.card())
            self._activity(sid, f"Verifying license, activity and docs — {src.title}", "verify", src.source_id)
            ok, vreasons = prov.verify(src)
            src.verification_status = "passed" if ok else "failed"
            score, sreasons = ranker.final(src, ok)
            src.relevance = score
            popularity = [r for r in src.reasons if r.endswith(("stars", "weekly downloads"))]
            src.reasons = vreasons + sreasons + popularity
            if ok and score >= USEFUL_AT_LEAST:
                src.state = SourceState.USEFUL
                self.bus.emit("research.source.useful", sid, source=src.card(), score=score)
                self._activity(sid, f"Source verified — {src.title} retained ({score:.2f})", "useful", src.source_id)
                if (score >= STRONG_SELECT_AT or src.meta.get("pinned")) and n_sel < plan.select_k:
                    n_sel += 1
                    self._select(sid, src, "Strong evidence")
            else:
                src.state = SourceState.REJECTED
                why = [r for r in vreasons if any(w in r for w in ("archived", "Stale", "Deprecated", "unknown"))] or [
                    f"Score {score:.2f} below {USEFUL_AT_LEAST}"]
                src.reasons = why + [r for r in src.reasons if r not in why]
                self.bus.emit("research.source.rejected", sid, source=src.card(), reasons=why, by="verification")
                self._activity(sid, f"Candidate rejected — {src.title}: {why[0]}", "reject", src.source_id)
            self._progress(sess, "inspect", 30 + 50 * (i + 1) / max(1, len(queue)))

    def _same_project(self, src: ResearchSource) -> Optional[ResearchSource]:
        """Platform builds / wrappers of one project (same GitHub source repo)
        are one candidate, not three."""
        repo = (src.meta.get("github_repo") or (src.title if src.provider == "github" else "") or "").lower()
        if not repo:
            return None
        for other in self.store.session_sources(src.session_id):
            if other is src or other.state not in (SourceState.USEFUL, SourceState.SELECTED):
                continue
            o = (other.meta.get("github_repo") or (other.title if other.provider == "github" else "") or "").lower()
            if o == repo:
                return other
        return None

    def _select(self, sid: str, src: ResearchSource, why: str) -> None:
        src.state = SourceState.SELECTED
        self.bus.emit("research.source.selected", sid, source=src.card(), why=why)
        self._activity(sid, f"Candidate selected — {src.title}", "select", src.source_id)

    def _finalize_selection(self, sess: ResearchSession, plan: ResearchPlan) -> List[ResearchSource]:
        sid = sess.session_id
        self._set_stage(sess, "selection", "SELECTION")
        srcs = self.store.session_sources(sid)
        selected = [s for s in srcs if s.state == SourceState.SELECTED]
        useful = sorted((s for s in srcs if s.state == SourceState.USEFUL),
                        key=lambda s: (-(1 if s.meta.get("pinned") else 0), -(s.relevance or 0)))
        for s in useful:
            if len(selected) >= plan.select_k:
                break
            self._select(sid, s, "Best remaining verified source")
            selected.append(s)
        selected.sort(key=lambda s: -(s.relevance or 0))
        noun = plan.artifact_title.lower()
        if selected:
            self._activity(sid, f"{len(selected)} strong {'candidate' if len(selected) == 1 else 'candidates'} remain — {noun}", "select")
        else:
            self._activity(sid, "No source survived inspection", "reject")
        self._progress(sess, "selection", 80)
        return selected

    # --------------------------------------------------------- evaluation
    def _evaluation_phase(self, sess, plan, ctl, art: ContextArtifact, selected: List[ResearchSource]) -> ContextArtifact:
        sid = sess.session_id
        self._set_stage(sess, "evaluation", "EVALUATION")
        self._activity(sid, "Measuring this PC for compatibility checks", "bench")
        host = host_profile(self.project_root)
        hw = [f"{host['ram_gb']:g} GB RAM" if host.get("ram_gb") else "RAM unknown",
              f"{host['gpu']} {host['vram_gb']:g} GB" if host.get("gpu") else "no NVIDIA GPU detected"]
        ev = Evaluator(plan.criteria, host)
        self.bus.emit("benchmark.started", sid, artifact_id=art.id, candidates=[s.card() for s in selected],
                      criteria=ev.criteria, host=host)
        self._activity(sid, f"Evaluating {len(selected)} candidates · this PC: {', '.join(hw)}", "bench")
        results: Dict[str, Dict] = {}
        total = len(selected) * len(ev.criteria)
        k = 0
        for src, crit, verdict, detail in ev.run(selected):
            ctl.checkpoint()
            k += 1
            results.setdefault(src.source_id, {})[crit] = (verdict, detail)
            self.bus.emit("benchmark.result", sid, source_id=src.source_id, title=src.title, criterion=crit,
                          verdict=verdict, detail=detail)
            if verdict in ("fail", "caution") or crit == "hardware":
                self._activity(sid, f"{src.title} · {crit}: {detail}", "bench", src.source_id)
            self._progress(sess, "evaluation", 82 + 14 * k / max(1, total))
        comp = Evaluator.comparison_artifact(art, selected, results, host)
        self.bus.emit("research.artifact.creating", sid, artifact_type=comp.type, title=comp.title,
                      source_ids=comp.source_ids, derived_from=[art.id])
        self.store.add_artifact(comp)
        self.bus.emit("research.artifact.created", sid, artifact=comp.to_dict())
        self.bus.emit("benchmark.completed", sid, artifact_id=comp.id)
        self._activity(sid, f"Comparison ready — {comp.findings[0]['title'] if comp.findings else 'no candidates'} ranks first", "artifact")
        return comp

    # ----------------------------------------------------------- response
    def _compose_response(self, sess: ResearchSession, artifacts: List[ContextArtifact]) -> str:
        if self.llm:
            ctx = "\n\n".join(to_context(a, self.wrap) for a in artifacts)
            text = (self.llm(
                "You are the assistant answering the user's research request. Use ONLY the context artifacts. "
                "Name the top pick and why, mention any unknowns honestly, 4 sentences max.",
                f"Request: {sess.query}\n\n{ctx}",
            ) or "").strip()
            if text:
                return text
        comp = next((a for a in artifacts if a.type == "CANDIDATE_COMPARISON"), None)
        first = artifacts[0] if artifacts else None
        if comp and comp.findings:
            top = comp.findings[0]
            parts = [f"Top pick: {top['title']} (fit {top['fit_score']:.2f})."]
            passes = [c for c, v in top["verdicts"].items() if v == "pass"]
            gaps = [c for c, v in top["verdicts"].items() if v in ("fail", "caution", "unknown")]
            if passes:
                parts.append(f"It passes {', '.join(passes)}.")
            if gaps:
                parts.append(f"Check {', '.join(gaps)} before adopting it.")
            if len(comp.findings) > 1:
                parts.append("Runners-up: " + ", ".join(f["title"] for f in comp.findings[1:]) + ".")
            return " ".join(parts)
        return first.summary if first else "Research finished without usable sources."
