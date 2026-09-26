"""dev/harness.py — run the research workspace inside the REAL JARVIS UI
without the voice stack, the brain, or Windows.

    python dev/harness.py --jarvis-root C:\\AI\\jarvis           (your checkout)
    python dev/harness.py --jarvis-root ../jarvis --port 5055

It serves the project's own templates/index.html and static/ (orb, HUD,
chat) and injects research.css/research.js — the same two lines the real
integration adds. Research requests typed into the chat (press C) start a
REAL research session. There is no LLM here, so the final answer is the
engine's deterministic summary of the artifacts; in JARVIS the brain
writes that answer instead (see jarvis_integration._on_complete).
"""

from __future__ import annotations

import argparse
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, render_template_string  # noqa: E402
from flask_socketio import SocketIO  # noqa: E402

from mentis_research import EvidenceStore, ResearchOrchestrator, needs_research  # noqa: E402
from mentis_research.flask_bridge import register  # noqa: E402
from mentis_research.providers import build_providers  # noqa: E402

INJECT_HEAD = '<link rel="stylesheet" href="/research-static/research.css?v=1" />'
INJECT_BODY = '<script src="/research-static/research.js?v=1"></script>'

FALLBACK_SHELL = """<!DOCTYPE html><html><head><meta charset="utf-8"><title>MENTIS research harness</title>
<style>:root{--accent:#4fd8e8;--accent-warm:#e8a94f;--bg:#05080a;--panel-bg:rgba(10,20,24,.72);
--panel-border:rgba(79,216,232,.35);--text:#d8f4f7;--text-dim:#7fa6ab;--danger:#e85a4f}
html,body{margin:0;height:100%;background:var(--bg);color:var(--text);font-family:Consolas,monospace;overflow:hidden}
#orb-canvas{position:fixed;inset:0;display:flex;align-items:center;justify-content:center}
#orb-canvas i{width:340px;height:340px;border-radius:50%;background:radial-gradient(circle,rgba(79,216,232,.5),rgba(79,216,232,.05) 60%,transparent 70%)}
#chat-overlay{position:fixed;left:24px;right:24px;bottom:20px;z-index:20;display:flex;flex-direction:column}
#chat-thread{max-width:640px;display:flex;flex-direction:column;gap:6px}#chat-input-row{max-width:640px}
#chat-input{width:100%;padding:10px;border-radius:8px;border:1px solid var(--panel-border);background:rgba(10,20,24,.85);color:var(--text)}
.bubble{padding:8px 12px;border-radius:10px;font-size:13px}.bubble.user{align-self:flex-end;background:rgba(232,169,79,.18)}
.bubble.assistant{background:rgba(79,216,232,.12)}</style>
{{ head|safe }}</head><body class="mode-awake"><div id="orb-canvas"><i></i></div>
<div id="chat-overlay" class="open"><div id="chat-thread"></div><div id="chat-input-row">
<input id="chat-input" placeholder="Ask for research and press Enter"/></div></div>
<script src="https://cdn.jsdelivr.net/npm/socket.io-client@4.7.5/dist/socket.io.min.js"></script>
<script>const s=io();window.__jarvisSocket=s;const t=document.getElementById('chat-thread');
function b(c,x){const d=document.createElement('div');d.className='bubble '+c;d.textContent=x;t.appendChild(d)}
s.on('user_text',p=>b('user',p.text));s.on('speak_sentence',p=>b('assistant',p.text));s.on('response_text',p=>b('assistant',p.text));
document.getElementById('chat-input').addEventListener('keydown',e=>{if(e.key==='Enter'&&e.target.value.trim()){s.emit('user_message',{text:e.target.value});e.target.value=''}});</script>
{{ body|safe }}</body></html>"""


def build_app(jarvis_root: str | None, providers: list[str] | None, project_root: str | None):
    if jarvis_root:
        jarvis_root = os.path.abspath(jarvis_root)
        app = Flask(__name__, template_folder=os.path.join(jarvis_root, "templates"),
                    static_folder=os.path.join(jarvis_root, "static"), static_url_path="/static")
    else:
        app = Flask(__name__)
    socketio = SocketIO(app, async_mode="threading", cors_allowed_origins="*")

    def on_complete(sess, artifacts, text):
        # No brain here: the answer is shown by the workspace itself when the
        # (paced) response.ready event is rendered. In JARVIS the brain speaks
        # it instead — see jarvis_integration._on_complete.
        print(f"[harness] research {sess.session_id} complete: {text}")

    orch = ResearchOrchestrator(
        store=EvidenceStore(persist_dir=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".research_sessions")),
        providers=build_providers(providers),
        on_complete=on_complete,
        project_root=project_root or jarvis_root,
    )
    register(app, socketio, orch)

    @app.route("/")
    def index():
        if jarvis_root and os.path.isfile(os.path.join(jarvis_root, "templates", "index.html")):
            with open(os.path.join(jarvis_root, "templates", "index.html"), encoding="utf-8") as f:
                html = f.read()
            html = html.replace("</head>", INJECT_HEAD + "\n</head>", 1)
            html = html.replace("</body>", INJECT_BODY + "\n</body>", 1)
            return render_template_string(html)
        return render_template_string(FALLBACK_SHELL, head=INJECT_HEAD, body=INJECT_BODY)

    @app.route("/favicon.ico")
    def favicon():
        return "", 204

    @socketio.on("connect")
    def _connect():
        socketio.emit("mode_change", {"mode": "awake"})

    @socketio.on("user_message")
    def _user_message(data):
        text = ((data or {}).get("text") or "").strip()
        if not text:
            return
        socketio.emit("user_text", {"text": text})
        if needs_research(text):
            threading.Thread(target=orch.start, args=(text,), daemon=True).start()
        else:
            msg = "Harness has no brain attached — ask me to research, compare or evaluate something."
            socketio.emit("speak_sentence", {"audio_b64": None, "text": msg})
            socketio.emit("response_text", {"text": msg})

    @socketio.on("speech_done")
    def _speech_done(_d=None):
        return None

    return app, socketio, orch


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jarvis-root", default=os.environ.get("JARVIS_ROOT"))
    ap.add_argument("--project-root", default=None, help="host project for stack/local-file checks")
    ap.add_argument("--providers", default=os.environ.get("RESEARCH_PROVIDERS", ""))
    ap.add_argument("--port", type=int, default=5055)
    args = ap.parse_args()
    provs = [p.strip() for p in args.providers.split(",") if p.strip()] or None
    app, socketio, _ = build_app(args.jarvis_root, provs, args.project_root)
    print(f"[harness] http://127.0.0.1:{args.port}  (jarvis root: {args.jarvis_root or 'fallback shell'})")
    socketio.run(app, host="127.0.0.1", port=args.port, allow_unsafe_werkzeug=True)


if __name__ == "__main__":
    main()
