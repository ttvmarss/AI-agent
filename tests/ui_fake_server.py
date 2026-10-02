"""A real PRAXIS engine (Controller + Session + the local server) on a scripted fake model, for the browser end-to-end tests (ui/e2e/run.mjs).
   python -m tests.ui_fake_server [goal|approval]      prints  READY <url>  then serves until killed."""
import json
import os
import sys
import tempfile
import time

from praxis.ui.server import UiServer
from praxis.ui.session import Session
from tests.test_desktop_controller import GOOD, mk, plan

SCENARIOS = {
    "goal": [GOOD],
    "approval": [plan([{"id": "o", "tool": "desktop.open", "args": {"target": "https://never-heard.example"}, "deps": [], "verify": {"type": "none"}}],
                      [{"type": "file_exists", "path": "nothing"}])],
}


def main(argv):
    scenario = argv[0] if argv else "goal"
    os.environ.setdefault("PRAXIS_HOME", tempfile.mkdtemp())
    c, ws, st = mk(list(SCENARIOS[scenario]))
    def no_voice(*a, **k):
        raise RuntimeError("no microphone in this test")
    s = Session(c, voice_factory=no_voice).start()
    srv = UiServer(s)
    srv.serve_in_thread()
    print("READY", srv.url(), ws, flush=True)
    while True:
        time.sleep(1)


if __name__ == "__main__":
    main(sys.argv[1:])
