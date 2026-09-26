# Integrating into JARVIS / MENTIS

Copy the `mentis_research/` folder next to `app.py`. Then add these four small edits:

**1. `app.py`**, right after `socketio = SocketIO(...)`:
```python
from mentis_research import jarvis_integration as rx
rx.install(app, socketio)
```

**2. `templates/index.html`**, one line in `<head>` and one before `</body>` (after `socket.js`):
```html
<link rel="stylesheet" href="/research-static/research.css?v=1" />
<script src="/research-static/research.js?v=1"></script>
```

**3. Tool registration**:
```python
# jarvis_state.py, append to TOOLS (schema dict is already in the right shape)
from mentis_research.jarvis_integration import TOOL_SCHEMA as _RX_TOOL   # lazy is fine too
TOOLS.append(_RX_TOOL)
# jarvis_tools.py
def _h_deep_research(query):
    from mentis_research.jarvis_integration import handle_deep_research
    return handle_deep_research(query)
TOOL_HANDLERS["deep_research"] = _h_deep_research
```
`check_parity()` stays green because the schema and the handler are added together.
If importing from `jarvis_state` breaks its leaf-module rule, paste the `TOOL_SCHEMA` dict inline instead.

**4. `process_message`**: feed research into the next turn:
```python
from mentis_research import jarvis_integration as rx
augmented_text = f"{profile_block}{memory_block}{session_block}{rx.context_block()}{text}"
```

When research completes, `_on_complete` calls `process_message` with a "research finished"
turn. The brain then answers from the context artifacts and speaks the answer. Artifact summaries also go into memory.

## Configuration (`.env`)

| Var | Default | |
|---|---|---|
| `GITHUB_TOKEN` | none | Strongly recommended: 5000 GitHub API requests/hour instead of 60 |
| `RESEARCH_PROVIDERS` | all | e.g. `github,web,npm,pypi,local,docs` |
| `RESEARCH_LOCAL_ROOT` | app folder | Folder for the local-files provider and the stack check |
| `RESEARCH_HTTP_TIMEOUT_S` | 10 | Per-request timeout |

Snapshots of every session (sources, facts, raw metadata, artifacts) are written to `memory/research/<session>.json`.

## Trying it without the voice stack

```
pip install flask==3.0.3 flask-socketio==5.3.6 requests beautifulsoup4
python dev/harness.py --jarvis-root C:\AI\jarvis
```
Open http://127.0.0.1:5055, press **C**, and ask for research. The page is your real `index.html`
with the two lines injected.
