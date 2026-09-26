"""Unit tests for the research engine. Network-free: the stub provider below
exists ONLY in tests to drive the orchestrator deterministically — the app
never ships or falls back to it."""

import threading
import time

import pytest

from mentis_research import EVENT_TYPES, EvidenceStore, ResearchEventBus, ResearchOrchestrator, make_plan, needs_research
from mentis_research.evaluation import check
from mentis_research.models import ResearchSource
from mentis_research.providers.base import Hit, ProviderError, SearchProviderAdapter, extract_text_facts, license_class
from mentis_research.store import canonical_url


class StubProvider(SearchProviderAdapter):
    name = "stub"
    label = "Stub"
    source_type = "repository"

    def __init__(self, hits, fail_inspect=(), gate=None):
        self.hits, self.fail_inspect, self.gate = hits, set(fail_inspect), gate

    def search(self, query, limit):
        for h in self.hits[:limit]:
            if self.gate:
                self.gate.wait(5)
            yield h

    def inspect(self, src, ctx):
        ctx.step(f"Reading README — {src.title}")
        if src.title in self.fail_inspect:
            raise ProviderError("HTTP 404")
        src.preview = f"{src.title} is a local coding agent llm tool. Requires 8 GB VRAM. Runs on Windows and Linux. " * 20
        src.meta["readme_chars"] = len(src.preview)
        ctx.update(extract_text_facts(src, src.preview, "README"))


def hit(name, stars=5000, lic="MIT", days=10, archived=False, url=None):
    return Hit(title=name, url=url or f"https://github.com/o/{name}", source_type="repository",
               snippet=f"{name} local coding agent llm", meta={"stars": stars, "license": lic, "days_since_update": days,
                                                               "archived": archived, "language": "Python", "topics": ["llm"]})


def run(hits, **kw):
    bus = ResearchEventBus(strict=True)
    events = []
    bus.subscribe(events.append)
    orch = ResearchOrchestrator(bus=bus, store=EvidenceStore(), providers={"github": StubProvider(hits, **kw)}, project_root=".")
    sid = orch.start("Research open-source local coding agent llm tools on GitHub that could improve our copilot", block=True)
    return orch, sid, events


def types(events):
    return [e["type"] for e in events]


def test_needs_research_and_plan():
    assert needs_research("Research the best open-source coding models for my PC")
    assert needs_research("compare ollama vs llama.cpp")
    assert not needs_research("open notepad")
    plan = make_plan("Research open-source AI projects on GitHub that could improve our Copilot", ["github", "web", "npm"])
    assert "github" in plan.queries
    assert plan.artifact_type == "INTEGRATION_CANDIDATES"


def test_full_session_event_order_and_artifacts():
    hits = [hit("alpha"), hit("beta", stars=900), hit("gamma", archived=True), hit("delta"), hit("zzz", stars=0)]
    hits[4].snippet = "unrelated"
    hits[4].meta["topics"] = []
    orch, sid, events = run(hits)
    t = types(events)
    assert all(x in EVENT_TYPES for x in t)
    assert t[0] == "task.started" and t[-1] == "task.completed"
    # progressive: every card is discovered before it is inspected
    for e in events:
        if e["type"] == "research.source.inspecting":
            src_id = e["data"]["source"]["source_id"]
            first = next(i for i, x in enumerate(events) if x["type"] == "research.result.discovered" and x["data"]["source"]["source_id"] == src_id)
            assert first < events.index(e)
    # archived repo rejected at triage
    rej = [e["data"]["source"]["title"] for e in events if e["type"] == "research.source.rejected"]
    assert "gamma" in rej
    arts = orch.store.latest_artifacts(5)
    kinds = {a.type for a in arts}
    assert {"INTEGRATION_CANDIDATES", "CANDIDATE_COMPARISON"} <= kinds
    comp = next(a for a in arts if a.type == "CANDIDATE_COMPARISON")
    first = next(a for a in arts if a.type == "INTEGRATION_CANDIDATES")
    assert comp.derived_from == [first.id]  # the next stage consumed the artifact
    for f in first.findings:  # provenance
        assert f["source_ids"] and orch.store.get_source(f["source_ids"][0]).url.startswith("https://")
    assert "response.ready" in t


def test_no_results_means_no_cards():
    orch, sid, events = run([])
    assert "research.result.discovered" not in types(events)
    art = next(a for a in orch.store.latest_artifacts(5))
    assert art.findings == [] and art.source_ids == []


def test_inspection_failure_is_reported_not_hidden():
    orch, sid, events = run([hit("alpha"), hit("broken")], fail_inspect=["broken"])
    failed = [e for e in events if e["type"] == "research.source.failed"]
    assert failed and failed[0]["data"]["source"]["title"] == "broken"
    assert "404" in failed[0]["data"]["error"]


def test_duplicate_urls_update_in_place():
    orch, sid, events = run([hit("alpha"), hit("alpha-dup", url="https://github.com/o/alpha/")])
    discovered = [e for e in events if e["type"] == "research.result.discovered"]
    assert len(discovered) == 1
    assert canonical_url("https://www.GitHub.com/o/alpha.git/") == canonical_url("https://github.com/o/alpha")


def test_metadata_updates_enrich_existing_card():
    orch, sid, events = run([hit("alpha")])
    ups = [e for e in events if e["type"] == "research.source.metadata_updated"]
    assert ups
    ids = {e["data"]["source"]["source_id"] for e in ups}
    assert len(ids) == 1
    labels = {f["label"] for f in ups[-1]["data"]["source"]["facts"]}
    assert "Min VRAM mentioned" in labels


def test_pause_blocks_and_stop_ends_without_artifact():
    gate = threading.Event()
    bus = ResearchEventBus(strict=True)
    events = []
    bus.subscribe(events.append)
    orch = ResearchOrchestrator(bus=bus, providers={"github": StubProvider([hit("a"), hit("b"), hit("c")], gate=gate)}, project_root=".")
    sid = orch.start("research local coding agent llm tools on github")
    time.sleep(0.2)
    assert orch.pause(sid)
    gate.set()
    time.sleep(0.8)
    n = len([e for e in events if e["type"] == "research.result.discovered"])
    time.sleep(0.8)
    assert len([e for e in events if e["type"] == "research.result.discovered"]) == n  # nothing moved while paused
    assert orch.resume(sid)
    assert orch.stop(sid)
    assert orch.wait(sid, 5)
    t = types(events)
    assert "research.session.stopped" in t
    assert "research.artifact.created" not in t


def test_unknown_is_never_invented():
    src = ResearchSource(source_id="s", session_id="x", provider="npm", source_type="package", title="p", url="u", retrieved_at=0)
    assert check("hardware", src, {"ram_gb": 32, "vram_gb": None})[0] == "unknown"
    assert check("license", src, {})[0] == "unknown"
    assert check("maintenance", src, {})[0] == "unknown"
    assert src.add_fact("Stars", None, "x") is None and src.facts == []
    assert license_class("GPL-3.0") == "copyleft" and license_class("MIT") == "permissive"


def test_strict_bus_rejects_unknown_events():
    with pytest.raises(ValueError):
        ResearchEventBus(strict=True).emit("research.fake")
