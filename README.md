# AI-agent: live visual research for the JARVIS / MENTIS copilot

A drop-in research workspace for the existing JARVIS UI (Flask-SocketIO + three.js orb).
When you ask the copilot to research something, you watch it happen:

- The core acknowledges the request, and a workspace unfolds beside it.
- Real results stream in one card at a time.
- Each candidate is opened and inspected: README, license, releases, and hardware notes appear in the card as they are fetched.
- Weak sources fall back into a set-aside tray, and strong ones move into an evidence cluster next to the core.
- The evidence compresses into a **Context Artifact**.
- An evaluation stage consumes that artifact and checks each candidate against this PC and this project.
- A comparison artifact and the answer follow.

Every visual change is driven by a real backend event. Nothing is simulated.
Unknown data is shown as UNKNOWN. Failed sources and blocked providers are shown as failures.

- Architecture and implementation map: [`docs/IMPLEMENTATION_MAP.md`](docs/IMPLEMENTATION_MAP.md)
- Integration into JARVIS (four small edits): [`docs/INTEGRATION.md`](docs/INTEGRATION.md)
- Recorded end-to-end run: [`docs/capture/research_run.webm`](docs/capture/research_run.webm), plus stills in `docs/capture/`

```
mentis_research/   engine (events, providers, orchestrator, artifacts, evaluation) + static/ UI
dev/harness.py     serves your real JARVIS index.html with the workspace injected
dev/capture.py     drives a real request through Chromium and records it
tests/             pytest suite (no network)
```

```
pip install flask==3.0.3 flask-socketio==5.3.6 requests beautifulsoup4 pytest
python -m pytest -q tests
python dev/harness.py --jarvis-root <path to your jarvis checkout>
```
