# Implementation map

Inspected: `ttvmarss/jarvis`, branch `claude/document-inspection-64tr61` (newest pushed JARVIS
work, Sep 6). The MENTIS v2 code on the owner's PC was never pushed, so it could not be read.
Everything here is **additive**: no existing file is rewritten.

## What the existing app is

| Area | Existing system |
|---|---|
| Frontend | Vanilla JS in IIFE modules (`static/v2/js/*.js`), no framework, no bundler |
| Backend | Flask + Flask-SocketIO (`async_mode="threading"`), `app.py` |
| AI / model | Claude Agent SDK brain (`jarvis_brain.py`): voice model plus `_utility_call` utility model |
| Agent / tools | Tools in `jarvis_state.TOOLS` → `jarvis_tools.TOOL_HANDLERS`, exposed to the brain as an in-process MCP server |
| Chat | `process_message` turn handler; `speak_sentence` / `response_text` socket events; `chat.js` bubbles |
| Research | `jarvis_research.research()`: single-shot Google-via-CDP search plus a one-paragraph summary; background tasks with a pause flag |
| Events / streaming | Socket.IO emits from `app.socketio` (`hud_update`, `workspace_task`, `mode_change`…) |
| State | `jarvis_state.py`, the leaf module holding all globals |
| Animation | three.js particle orb (`sphere.js`) plus CSS transitions; no animation library |
| Core component | `sphere.js` orb; `standby.js` modes (`mode-standby` / `mode-awake` / `mode-workspace`) |
| Panels | `.panel` HUD cards (`hud.js`), `#workspace-panel` progress card |
| Theme tokens | `:root { --accent #4fd8e8; --accent-warm #e8a94f; --bg; --panel-bg; --panel-border; --text; --text-dim; --danger }`, Consolas |
| Layout | Fixed-position overlays over a full-screen canvas |

## Existing → keep / modify / extend

| Existing | Decision |
|---|---|
| Colour tokens, typography, glass panels, HUD brackets | **Keep.** `research.css` only reads them |
| `sphere.js` orb | **Keep.** Untouched; the workspace shifts and dims it via a body class on the canvas |
| Socket.IO transport (`app.socketio`) | **Extend.** One new server→client event, `research_event`, plus client→server controls |
| `socket.js` (`window.__jarvisSocket`) | **Keep.** `research.js` attaches to the same socket |
| Chat overlay and input | **Keep.** While research is active it moves under the core instead of dimming the screen |
| Tool system | **Extend.** New `deep_research` tool (schema plus handler) |
| `process_message` | **Extend.** One line prepends the newest research artifacts as working memory |
| `jarvis_research.research()` | **Keep** for quick one-shot answers; `deep_research` is the visual path |
| `_utility_call`, `st._wrap_untrusted` | **Reuse.** For query planning and summaries, and to wrap all fetched text |
| `jarvis_memory` | **Reuse.** Artifact summaries are saved to memory |
| HUD `.panels` | **Modify (CSS only).** Hidden while the research workspace is up |

## New components

| New | Purpose |
|---|---|
| `mentis_research/events.py`: `ResearchEventBus` | Typed event vocabulary, seq numbers, replay buffer |
| `models.py` | `ResearchSource` (provenance record, enriched in place), `ContextArtifact`, `ResearchSession` |
| `store.py`: `EvidenceStore` | Sources and artifacts, URL dedup, JSON snapshot per session |
| `planner.py` | Research-intent detection, provider routing, queries, artifact kind |
| `providers/`: `SearchProviderAdapter` | `GitHubProvider`, `WebSearchProvider`, `DocumentationProvider`, `NpmProvider`, `PyPIProvider`, `LocalProjectProvider` |
| `ranker.py`: `ResearchRanker` | Explainable triage and final scoring |
| `artifacts.py`: `ArtifactBuilder` | Selected evidence → `ContextArtifact`; `to_context()` for later prompts |
| `evaluation.py`: `Evaluator` | Next stage: consumes the artifact, checks each candidate against this PC and stack |
| `orchestrator.py`: `ResearchOrchestrator` | Runs the session: search → triage → inspect → verify → select → artifact → evaluate → answer. Handles pause, resume, and stop |
| `flask_bridge.py` | Registers socket handlers and static routes on the existing Flask-SocketIO app |
| `jarvis_integration.py` | The three JARVIS touch points: install, tool, and context block |
| `static/research.js` | Renderer: paced event queue, zone layout engine, cards, artifacts, evaluation matrix, source viewer, controls |
| `static/research.css` | Workspace styles built on the existing tokens; motion tokens |
| `dev/harness.py`, `dev/capture.py` | Run the real JARVIS UI with research injected; automated end-to-end capture |
