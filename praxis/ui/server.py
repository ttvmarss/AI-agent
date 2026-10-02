"""The local server that connects the interface to the engine.

  GET  /                 the interface (static files built from /ui)          GET  /api/frames   Server-Sent Events: the engine's state, ~10 per second
  GET  /api/frame        one frame as JSON                                    GET  /api/theme    your ~/.praxis/theme.json (or {})
  POST /api/cmd          one command (submit, stop, approve, ...)

It listens on 127.0.0.1 only, on a random port, and is locked to the one window PRAXIS opens: a random per-run key travels in the first URL, becomes an
HttpOnly SameSite=Strict cookie, and every /api call must carry it. Requests whose Host header is not this server (DNS rebinding), POSTs without the
custom header or from another Origin (cross-site forgery), oversized bodies and malformed commands are all refused. A web page open in some other tab
cannot drive PRAXIS, because PRAXIS can run commands on this computer."""
import hmac
import json
import mimetypes
import os
import posixpath
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .. import paths

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
MAX_BODY = 64 * 1024
COOKIE = "praxis_k"
CMD_SCHEMA = {   # command -> {field: type}; unknown commands and wrongly-typed fields are refused before the session sees them
    "submit": {"text": str}, "stop": {}, "approve": {"id": str, "ok": bool}, "set_data": {"value": str}, "set_strategy": {"value": str},
    "mute": {}, "resume": {}, "undo": {}, "open_workspace": {"path": str}, "quit": {},
}
OPTIONAL = {("mute", "value")}


def validate_command(obj):
    """-> (clean command dict, "") or (None, reason)."""
    if not isinstance(obj, dict):
        return None, "a command is an object"
    kind = obj.get("cmd")
    if kind not in CMD_SCHEMA:
        return None, "unknown command"
    out = {"cmd": kind}
    for field, typ in CMD_SCHEMA[kind].items():
        if field not in obj:
            return None, f"missing {field}"
        if not isinstance(obj[field], typ) or (typ is str and len(obj[field]) > 4100):
            return None, f"bad {field}"
        out[field] = obj[field]
    if kind == "mute" and "value" in obj:
        if not isinstance(obj["value"], bool):
            return None, "bad value"
        out["value"] = obj["value"]
    return out, ""


def theme_override():
    p = os.environ.get("PRAXIS_THEME") or os.path.join(paths.home(), "theme.json")
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


class UiServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, session, host="127.0.0.1", port=0, key=None, static=STATIC):
        self.session, self.key, self.static = session, key or secrets.token_urlsafe(24), static
        self.clients, self.had_client, self.last_client_at = 0, False, time.time()
        self._lock = threading.Lock()
        super().__init__((host, port), Handler)

    @property
    def port(self):
        return self.server_address[1]

    def url(self):
        """The one URL that opens the interface (it carries the key once; the browser keeps it as a cookie afterwards)."""
        return f"http://127.0.0.1:{self.port}/?k={self.key}"

    def client(self, delta):
        with self._lock:
            self.clients += delta
            if delta > 0:
                self.had_client = True
            self.last_client_at = time.time()

    def idle_for(self):
        """Seconds with no interface connected, once one has been (None before the first connection)."""
        with self._lock:
            return None if (self.clients or not self.had_client) else time.time() - self.last_client_at

    def serve_in_thread(self):
        t = threading.Thread(target=self.serve_forever, daemon=True, name="praxis-ui-server")
        t.start()
        return t


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "PRAXIS"
    sys_version = ""

    def log_message(self, *a):
        pass

    # ---- plumbing ----------------------------------------------------------------------------------------------
    def _send(self, code, body=b"", ctype="application/json", headers=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _host_ok(self):
        host = (self.headers.get("Host") or "").lower()
        return host in (f"127.0.0.1:{self.server.port}", f"localhost:{self.server.port}")

    def _cookie_ok(self):
        raw = self.headers.get("Cookie") or ""
        for part in raw.split(";"):
            k, _, v = part.strip().partition("=")
            if k == COOKIE and hmac.compare_digest(v, self.server.key):
                return True
        return False

    def _guard(self, api):
        """Refuse anything that is not our own window talking to us. -> True if the request may proceed."""
        if not self._host_ok():
            self._send(403, {"error": "bad host"})
            return False
        if api and not self._cookie_ok():
            self._send(401, {"error": "not authorised"})
            return False
        return True

    # ---- GET ---------------------------------------------------------------------------------------------------------
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if not self._guard(False):
            return
        u = urlparse(self.path)
        path = u.path
        if path.startswith("/api/"):
            if not self._guard(True):
                return
            if path == "/api/frames":
                return self._sse()
            if path == "/api/frame":
                frame, _ = self.server.session.frame()
                return self._send(200, frame or {})
            if path == "/api/theme":
                return self._send(200, theme_override())
            return self._send(404, {"error": "no such endpoint"})
        q = parse_qs(u.query)
        if "k" in q:                                                  # the first visit: trade the key in the URL for a cookie, then forget it
            if not hmac.compare_digest(q["k"][0], self.server.key):
                return self._send(403, {"error": "bad key"})
            return self._send(302, b"", headers={"Location": "/", "Set-Cookie": f"{COOKIE}={self.server.key}; HttpOnly; SameSite=Strict; Path=/"})
        if not self._cookie_ok():
            return self._send(401, b"Open PRAXIS from its own window (run: praxis).", ctype="text/plain; charset=utf-8")
        self._static(path)

    def _static(self, path):
        rel = posixpath.normpath(path).lstrip("/") or "index.html"
        if rel.startswith("..") or "\\" in rel or "\x00" in rel:
            return self._send(404, b"", ctype="text/plain")
        full = os.path.realpath(os.path.join(self.server.static, rel))
        root = os.path.realpath(self.server.static)
        if not (full == root or full.startswith(root + os.sep)) or not os.path.isfile(full):
            if rel != "index.html" and "." not in os.path.basename(rel):
                full = os.path.join(root, "index.html")
            else:
                return self._send(404, b"not found", ctype="text/plain")
        if not os.path.isfile(full):
            return self._send(503, b"The interface has not been built: run `npm ci && npm run build` in /ui.", ctype="text/plain")
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        with open(full, "rb") as f:
            data = f.read()
        immutable = "/assets/" in path
        self._send(200, data, ctype=ctype, headers={"Cache-Control": "public, max-age=86400, immutable"} if immutable else None)

    def _sse(self):
        srv = self.server
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        srv.client(+1)
        seq = -1
        try:
            while True:
                frame, seq2 = srv.session.wait(seq, 15.0)
                if seq2 == seq or frame is None:
                    self.wfile.write(b": keepalive\n\n")                      # also how a dead client is noticed: the write fails
                else:
                    seq = seq2
                    self.wfile.write(b"data: " + json.dumps(frame, separators=(",", ":")).encode("utf-8") + b"\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass
        finally:
            srv.client(-1)
            self.close_connection = True

    # ---- POST --------------------------------------------------------------------------------------------------------
    def do_POST(self):
        if not self._guard(True):
            return
        if self.path != "/api/cmd":
            return self._send(404, {"error": "no such endpoint"})
        if self.headers.get("X-Praxis") != "1":
            return self._send(403, {"error": "missing header"})
        origin = self.headers.get("Origin")
        if origin and origin not in (f"http://127.0.0.1:{self.server.port}", f"http://localhost:{self.server.port}"):
            return self._send(403, {"error": "cross-origin request refused"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = -1
        if n < 0 or n > MAX_BODY:
            self.close_connection = True                       # the unread body must not be parsed as the next request
            return self._send(413, {"error": "body too large"}, headers={"Connection": "close"})
        raw = self.rfile.read(n) if n else b""
        try:
            obj = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return self._send(400, {"error": "not JSON"})
        cmd, why = validate_command(obj)
        if cmd is None:
            return self._send(400, {"error": why})
        ok, msg = self.server.session.command(cmd)
        self._send(200, {"ok": bool(ok), "message": str(msg)})
