"""Run PRAXIS's interface: the session (engine glue), the local server, and the app window; and shut all of it down when the window closes."""
import json
import os
import socket
import sys
import time

from .. import paths
from .server import UiServer
from .session import Session
from . import window

GRACE_S = 12.0          # no interface connected for this long (after one was) means the window was closed
NEVER_CONNECTED_S = 90.0


def lock_path():
    return os.path.join(paths.home(), "ui.lock")


def running_instance(path=None, connect=socket.create_connection):
    """-> the URL of an interface that is already running for this user, or None (stale locks are ignored)."""
    try:
        with open(path or lock_path(), encoding="utf-8") as f:
            d = json.load(f)
        with connect(("127.0.0.1", int(d["port"])), timeout=1.0):
            pass
        return d["url"]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def write_lock(url, port, path=None):
    p = path or lock_path()
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"url": url, "port": port, "pid": os.getpid()}, f)
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass
    except OSError:
        pass


def run(controller, voice_factory=None, open_window=window.open_window, show=True, out=print, poll_s=0.5):
    """-> exit code. Blocks until the window is closed (or `quit`)."""
    session = Session(controller, voice_factory=voice_factory).start()
    server = UiServer(session)
    server.serve_in_thread()
    url = server.url()
    write_lock(url, server.port)
    out(f"PRAXIS interface: http://127.0.0.1:{server.port}/  (build running; close its window to quit)")
    proc = open_window(url) if show else None
    started = time.time()
    try:
        while not session.quit_requested.is_set():
            time.sleep(poll_s)
            idle = server.idle_for()
            if idle is not None and idle > GRACE_S:
                break                                                       # the window was closed
            if proc is not None and proc.poll() is not None and time.time() - started > 8 and server.clients == 0:
                break                                                       # its own process ended and nothing is connected
            if not server.had_client and time.time() - started > NEVER_CONNECTED_S:
                out("The interface never connected; shutting down.")
                break
    except KeyboardInterrupt:
        pass
    finally:
        try:
            os.remove(lock_path())
        except OSError:
            pass
        session.close()
        server.shutdown()
        server.server_close()
        try:
            controller.shutdown()
        except Exception:
            pass
    return 0
