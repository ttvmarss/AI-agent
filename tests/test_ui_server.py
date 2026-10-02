"""The interface's engine side: what a frame says, what a command may do, and who is allowed to talk to the server."""
import http.client
import json
import os
import tempfile
import threading
import time
import unittest
from unittest import mock

from praxis.ui import app as ui_app, model, window
from praxis.ui.server import COOKIE, MAX_BODY, UiServer, validate_command
from praxis.ui.session import Session
from tests.test_desktop_controller import GOOD, W, fake_stack, mk, plan, wait


def session_for(responses=(GOOD,), **kw):
    c, ws, st = mk(list(responses), **kw)
    s = Session(c, voice_factory=kw.get("voice_factory") or (lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no microphone"))), tick_s=0.02)
    return s, c, ws, st


class Commands(unittest.TestCase):
    def test_only_known_well_typed_commands_pass(self):
        good = [{"cmd": "submit", "text": "open chrome"}, {"cmd": "stop"}, {"cmd": "approve", "id": "ab", "ok": True}, {"cmd": "set_data", "value": "private"},
                {"cmd": "set_strategy", "value": "frugal"}, {"cmd": "mute"}, {"cmd": "mute", "value": False}, {"cmd": "resume"}, {"cmd": "undo"},
                {"cmd": "open_workspace", "path": "C:/x"}, {"cmd": "quit"}]
        for c in good:
            clean, why = validate_command(c)
            self.assertEqual(clean, c, why)
        bad = [None, [], "x", {}, {"cmd": "rm -rf"}, {"cmd": "submit"}, {"cmd": "submit", "text": 5}, {"cmd": "submit", "text": "x" * 5000},
               {"cmd": "approve", "id": "a"}, {"cmd": "approve", "id": "a", "ok": "yes"}, {"cmd": "approve", "id": 7, "ok": True}, {"cmd": "mute", "value": "no"},
               {"cmd": "open_workspace", "path": ["x"]}]
        for c in bad:
            self.assertIsNone(validate_command(c)[0], c)

    def test_extra_fields_are_dropped_not_passed_on(self):
        clean, _ = validate_command({"cmd": "stop", "evil": "payload", "__class__": 1})
        self.assertEqual(clean, {"cmd": "stop"})


class Mapping(unittest.TestCase):
    def view(self, status, **kw):
        from praxis.desktop.view import StepView, View
        return View(goal_id="g", goal_text="make a file", status=status, steps=[StepView("s", "fs.write", "a.txt", state="running")], **kw)

    def test_the_state_words_follow_the_real_status(self):
        cases = [("PLANNING", "working", "PLANNING"), ("RUNNING", "working", "RUNNING"), ("VERIFIED", "ok", "VERIFIED"), ("FAILED", "bad", "FAILED"),
                 ("CANCELLED", "stopped", "STOPPED"), ("UNVERIFIED", "stopped", "UNVERIFIED")]
        for status, mode, title in cases:
            m, t, sub, prog = model.mode_for(self.view(status), "working" if status in ("PLANNING", "RUNNING") else "idle")
            self.assertEqual((m, t), (mode, title), status)
        self.assertEqual(model.mode_for(self.view("RUNNING"), "working", waiting=True)[:2], ("waiting", "NEEDS YOU"))
        self.assertEqual(model.mode_for(self.view("RUNNING"), "stopping")[:2], ("stopping", "STOPPING"))
        self.assertEqual(model.mode_for(self.view("IDLE"), "starting")[:2], ("starting", "STARTING"))
        self.assertEqual(model.mode_for(self.view("IDLE"), "error", error="boom")[:3], ("bad", "ERROR", "boom"))

    def test_pipeline_labels_are_the_real_step_summaries_and_unknown_states_are_safe(self):
        from praxis.desktop.view import StepView, View
        v = View(goal_id="g", status="RUNNING", steps=[StepView("a", "shell.run", "python3 hi.py", state="running"), StepView("b", "fs.write", "", state="weird")],
                 evidence=[{"claim": "file_exists hi.py", "passed": True}])
        p = model.pipeline(v)
        self.assertEqual([s["label"] for s in p["steps"]], ["python3 hi.py", "fs.write"])
        self.assertEqual(p["steps"][1]["state"], "pending")
        self.assertEqual(p["checks"], [{"label": "file_exists hi.py", "ok": True}])
        self.assertEqual(p["plan"], "ready")

    def test_approvals_show_a_sentence_and_the_exact_action(self):
        from praxis.desktop.controller import ApprovalRequest
        a = model.approval(ApprovalRequest("id1", "desktop.open", 3, {"target": "https://x.example"}, "Class 3 exceeds auto grant 2"))
        self.assertEqual(a["summary"], "Open https://x.example"); self.assertIn("https://x.example", a["detail"]); self.assertFalse(a["risky"])
        self.assertTrue(model.approval(ApprovalRequest("i", "shell.run", 4, {"cmd": "ls"}, "r"))["risky"])


class SessionFrames(unittest.TestCase):
    def test_the_frame_has_the_contract_the_interface_expects(self):
        s, c, ws, st = session_for()
        s.start()
        self.assertTrue(wait(lambda: (s.frame()[0] or {}).get("mode") == "idle"))
        f, seq = s.frame()
        for key in ("v", "t", "mode", "title", "subtitle", "goal", "progress", "pipeline", "active", "brains", "stats", "voice", "log", "approvals", "settings", "info", "shock"):
            self.assertIn(key, f)
        self.assertEqual(f["v"], 1)
        self.assertEqual(f["settings"], {"data_class": "project", "strategy": "balanced", "models": 1})
        self.assertEqual(f["brains"][0]["family"], "scripted")
        self.assertEqual(f["info"]["workspace_name"], os.path.basename(ws))
        self.assertTrue(any("conversation mind online" in l["text"] for l in f["log"]))
        json.dumps(f)                                                      # and it is plain JSON
        s.close()

    def test_a_goal_walks_through_working_to_verified_with_real_steps_and_one_shock(self):
        s, c, ws, st = session_for()
        s.start(); wait(lambda: (s.frame()[0] or {}).get("mode") == "idle")
        ok, msg = s.command({"cmd": "submit", "text": "make a.txt"})
        self.assertTrue(ok, msg)
        self.assertTrue(wait(lambda: (s.frame()[0] or {}).get("mode") == "ok", 10))
        f, _ = s.frame()
        self.assertEqual(f["title"], "VERIFIED")
        self.assertEqual(f["pipeline"]["steps"][0]["state"], "verified")
        self.assertTrue(f["pipeline"]["checks"][0]["ok"]); self.assertTrue(f["pipeline"]["sealed"])
        self.assertEqual(f["stats"]["steps"], "1/1")
        self.assertEqual(f["shock"], 1)
        time.sleep(0.3)
        self.assertEqual(s.frame()[0]["shock"], 1)                          # one verified goal, one shockwave
        ids = [l["id"] for l in f["log"]]
        self.assertEqual(ids, sorted(set(ids)))
        s.close()

    def test_new_frames_wake_waiting_listeners_and_waiting_times_out_politely(self):
        s, c, ws, st = session_for()
        s.start()
        f, seq = s.frame()
        t0 = time.time()
        f2, seq2 = s.wait(seq, timeout=1.0)
        self.assertGreater(seq2, seq); self.assertLess(time.time() - t0, 0.8)
        s.close()

    def test_commands_do_what_they_say_and_refuse_what_they_should(self):
        s, c, ws, st = session_for()
        s.start(); wait(lambda: (s.frame()[0] or {}).get("mode") == "idle")
        self.assertEqual(s.command({"cmd": "submit", "text": "   "})[0], False)
        self.assertEqual(s.command({"cmd": "stop"}), (False, "nothing is running"))
        self.assertTrue(s.command({"cmd": "set_data", "value": "private"})[0]); self.assertEqual(c.effective_data_class(), "private")
        self.assertFalse(s.command({"cmd": "set_data", "value": "everything"})[0])
        self.assertTrue(s.command({"cmd": "set_strategy", "value": "frugal"})[0]); self.assertEqual(c.stack.router.strategy, "frugal")
        self.assertFalse(s.command({"cmd": "approve", "id": "nope", "ok": True})[0])
        self.assertEqual(s.command({"cmd": "mute"}), (False, "voice is not running"))
        self.assertFalse(s.command({"cmd": "resume"})[0])
        self.assertFalse(s.command({"cmd": "nonsense"})[0])
        self.assertFalse(s.command({"cmd": "open_workspace", "path": ""})[0])
        home = os.path.expanduser("~")
        ok, msg = s.command({"cmd": "open_workspace", "path": home})
        self.assertFalse(ok); self.assertTrue(msg)                              # the home folder is refused, with a reason
        s.close()

    def test_without_a_microphone_the_interface_is_told_to_show_a_typing_line(self):
        s, c, ws, st = session_for()
        s.start()
        self.assertTrue(wait(lambda: (s.frame()[0] or {}).get("info", {}).get("can_type")))
        f, _ = s.frame()
        self.assertEqual(f["voice"]["state"], "offline"); self.assertIn("no microphone", f["voice"]["note"])
        s.close()

    def test_approval_requests_appear_in_the_frame_and_can_be_answered(self):
        steps = [{"id": "o", "tool": "desktop.open", "args": {"target": "https://never-heard.example"}, "deps": [], "verify": {"type": "none"}}]
        s, c, ws, st = session_for([plan(steps, [{"type": "file_exists", "path": "nothing"}])])
        s.start(); wait(lambda: (s.frame()[0] or {}).get("mode") == "idle")
        s.command({"cmd": "submit", "text": "I would like to read a page on the web please"})
        self.assertTrue(wait(lambda: (s.frame()[0] or {}).get("approvals"), 10))
        f, _ = s.frame()
        a = f["approvals"][0]
        self.assertEqual(a["cls"], 3); self.assertIn("https://never-heard.example", a["detail"]); self.assertEqual(f["mode"], "waiting")
        self.assertEqual(s.command({"cmd": "approve", "id": a["id"], "ok": False}), (True, ""))
        self.assertTrue(wait(lambda: not (s.frame()[0] or {}).get("approvals") and s.frame()[0]["mode"] in ("bad", "stopped", "idle"), 10))
        s.close()


class ServerSecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s, cls.c, cls.ws, cls.st = session_for()
        cls.s.start()
        wait(lambda: (cls.s.frame()[0] or {}).get("mode") == "idle")
        cls.static = tempfile.mkdtemp()
        os.makedirs(os.path.join(cls.static, "assets"))
        open(os.path.join(cls.static, "index.html"), "w").write("<html>PRAXIS</html>")
        open(os.path.join(cls.static, "assets", "a.js"), "w").write("console.log(1)")
        open(os.path.join(os.path.dirname(cls.static), "secret.txt"), "w").write("SECRET")
        cls.srv = UiServer(cls.s, static=cls.static)
        cls.srv.serve_in_thread()
        cls.port = cls.srv.port
        cls.cookie = f"{COOKIE}={cls.srv.key}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown(); cls.srv.server_close(); cls.s.close()

    def req(self, method, path, body=None, headers=None, host=0):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        h = {} if host is None else {"Host": f"127.0.0.1:{self.port}" if host == 0 else host}        # host=None: send no Host header at all
        h.update(headers or {})
        conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        for k, v in h.items():
            conn.putheader(k, v)
        data = body if isinstance(body, bytes) else (json.dumps(body).encode() if body is not None else None)
        if data is not None:
            conn.putheader("Content-Length", str(len(data)))
        conn.endheaders(data)
        r = conn.getresponse()
        out = (r.status, r.read(), dict(r.getheaders()))
        conn.close()
        return out

    def test_the_key_url_trades_for_a_cookie_and_then_serves_the_interface(self):
        st, body, h = self.req("GET", f"/?k={self.srv.key}")
        self.assertEqual(st, 302); self.assertIn("HttpOnly", h["Set-Cookie"]); self.assertIn("SameSite=Strict", h["Set-Cookie"])
        self.assertEqual(h["Location"], "/")
        st, body, h = self.req("GET", "/", headers={"Cookie": self.cookie})
        self.assertEqual((st, body), (200, b"<html>PRAXIS</html>")); self.assertIn("frame-ancestors 'none'", h["Content-Security-Policy"])
        st, body, h = self.req("GET", "/assets/a.js", headers={"Cookie": self.cookie})
        self.assertEqual(st, 200); self.assertIn("javascript", h["Content-Type"]); self.assertIn("immutable", h["Cache-Control"])

    def test_without_the_cookie_nothing_is_served_and_a_wrong_key_is_refused(self):
        self.assertEqual(self.req("GET", "/")[0], 401)
        self.assertEqual(self.req("GET", "/api/frame")[0], 401)
        self.assertEqual(self.req("GET", "/api/theme")[0], 401)
        self.assertEqual(self.req("GET", "/?k=wrong")[0], 403)
        self.assertEqual(self.req("GET", "/api/frame", headers={"Cookie": f"{COOKIE}=wrong"})[0], 401)
        self.assertEqual(self.req("POST", "/api/cmd", {"cmd": "stop"}, {"X-Praxis": "1"})[0], 401)

    def test_a_request_for_another_hostname_is_refused_so_dns_rebinding_fails(self):
        for host in ("evil.example", f"evil.example:{self.port}", f"127.0.0.1.evil.example:{self.port}", "", None):
            self.assertEqual(self.req("GET", "/api/frame", headers={"Cookie": self.cookie}, host=host)[0], 403, host)
        self.assertEqual(self.req("GET", "/api/frame", headers={"Cookie": self.cookie}, host=f"localhost:{self.port}")[0], 200)

    def test_a_forged_cross_site_post_is_refused_even_with_the_cookie(self):
        base = {"Cookie": self.cookie, "Content-Type": "application/json"}
        self.assertEqual(self.req("POST", "/api/cmd", {"cmd": "stop"}, base)[0], 403)                                        # no custom header
        self.assertEqual(self.req("POST", "/api/cmd", {"cmd": "stop"}, {**base, "X-Praxis": "1", "Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.req("POST", "/api/cmd", {"cmd": "stop"}, {**base, "X-Praxis": "1", "Origin": f"http://127.0.0.1:{self.port}"})[0], 200)

    def test_commands_are_validated_before_the_session_sees_them(self):
        base = {"Cookie": self.cookie, "X-Praxis": "1"}
        st, body, _ = self.req("POST", "/api/cmd", {"cmd": "rm -rf /"}, base); self.assertEqual(st, 400)
        st, body, _ = self.req("POST", "/api/cmd", b"not json", base); self.assertEqual(st, 400)
        st, body, _ = self.req("POST", "/api/cmd", b"\xff\xfe", base); self.assertEqual(st, 400)
        st, body, _ = self.req("POST", "/api/cmd", b"x" * (MAX_BODY + 10), base); self.assertEqual(st, 413)
        st, body, _ = self.req("POST", "/api/cmd", {"cmd": "set_data", "value": "private"}, base)
        self.assertEqual((st, json.loads(body)), (200, {"ok": True, "message": ""}))
        st, body, _ = self.req("POST", "/api/cmd", {"cmd": "stop"}, base)
        self.assertEqual(json.loads(body)["ok"], False)                                    # nothing is running: a clean refusal, not an error
        self.assertEqual(self.req("POST", "/api/other", {}, base)[0], 404)

    def test_paths_cannot_escape_the_static_folder(self):
        h = {"Cookie": self.cookie}
        for p in ("/../secret.txt", "/..%2fsecret.txt", "/%2e%2e/secret.txt", "/assets/../../secret.txt", "//etc/passwd", "/..\\secret.txt", "/%00"):
            st, body, _ = self.req("GET", p, headers=h)
            self.assertNotIn(b"SECRET", body, p)
        self.assertEqual(self.req("GET", "/missing.js", headers=h)[0], 404)
        st, body, _ = self.req("GET", "/some/route", headers=h)                              # an app route falls back to the interface
        self.assertEqual(body, b"<html>PRAXIS</html>")

    @unittest.skipIf(os.name == "nt", "symlinks need privileges on Windows")
    def test_a_symlink_inside_the_static_folder_cannot_lead_outside_it(self):
        secret = os.path.join(os.path.dirname(self.static), "secret.txt")
        link = os.path.join(self.static, "assets", "leak.txt")
        if not os.path.lexists(link):
            os.symlink(secret, link)
        st, body, _ = self.req("GET", "/assets/leak.txt", headers={"Cookie": self.cookie})
        self.assertNotIn(b"SECRET", body)

    def test_the_frame_and_theme_endpoints(self):
        h = {"Cookie": self.cookie}
        st, body, _ = self.req("GET", "/api/frame", headers=h)
        self.assertEqual((st, json.loads(body)["v"]), (200, 1))
        d = tempfile.mkdtemp(); p = os.path.join(d, "theme.json"); open(p, "w").write('{"colors": {"jarvis": "#ff00ff"}}')
        with mock.patch.dict(os.environ, {"PRAXIS_THEME": p}):
            self.assertEqual(json.loads(self.req("GET", "/api/theme", headers=h)[1]), {"colors": {"jarvis": "#ff00ff"}})
        open(p, "w").write("{broken")
        with mock.patch.dict(os.environ, {"PRAXIS_THEME": p}):
            self.assertEqual(json.loads(self.req("GET", "/api/theme", headers=h)[1]), {})       # a broken override never breaks the interface

    def test_the_event_stream_delivers_frames_counts_clients_and_notices_when_they_leave(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.putrequest("GET", "/api/frames", skip_host=True)
        conn.putheader("Host", f"127.0.0.1:{self.port}"); conn.putheader("Cookie", self.cookie); conn.endheaders()
        r = conn.getresponse()
        self.assertEqual((r.status, r.getheader("Content-Type")), (200, "text/event-stream"))
        line = r.fp.readline()
        self.assertTrue(line.startswith(b"data: "), line)
        self.assertEqual(json.loads(line[6:])["v"], 1)
        self.assertTrue(wait(lambda: self.srv.clients == 1))
        r.close(); conn.close()                                                           # the window really goes away
        self.assertTrue(wait(lambda: self.srv.clients == 0, 20), "the server must notice the window closing")
        self.assertIsNotNone(self.srv.idle_for())


class Launching(unittest.TestCase):
    def test_browsers_are_found_best_first_and_missing_ones_skipped(self):
        with mock.patch.object(window, "IS_WINDOWS", True), mock.patch.object(window, "IS_MAC", False):
            found = window.find_browsers(exists=lambda p: "Edge" in p or "Chrome" in p, which=lambda n: None,
                                         environ={"ProgramFiles(x86)": r"C:\PF86", "ProgramFiles": r"C:\PF", "LOCALAPPDATA": r"C:\L"}, winreg=mock.Mock(side_effect=ImportError))
            self.assertEqual([k for _, k in found][0], "edge")
            self.assertIn("chrome", [k for _, k in found])
            self.assertNotIn("brave", [k for _, k in found])
            self.assertEqual(window.find_browsers(exists=lambda p: False, which=lambda n: None, environ={}), [])

    def test_the_app_window_is_chromeless_on_a_private_profile(self):
        cmd = window.command("/x/chrome", "http://127.0.0.1:1/?k=a", "/p")
        self.assertEqual(cmd[0], "/x/chrome"); self.assertIn("--app=http://127.0.0.1:1/?k=a", cmd); self.assertIn("--user-data-dir=/p", cmd)

    def test_it_falls_back_to_the_default_browser_and_says_so(self):
        out, opened = [], []
        r = window.open_window("http://127.0.0.1:1/", browsers=[], open_default=opened.append, out=out.append)
        self.assertIsNone(r); self.assertEqual(opened, ["http://127.0.0.1:1/"]); self.assertIn("default browser", out[0])
        def boom(*a, **k): raise OSError("cannot")
        out.clear()
        with mock.patch.dict(os.environ, {"PRAXIS_HOME": tempfile.mkdtemp()}):
            r = window.open_window("u", browsers=[("/x/edge", "edge")], popen=boom, open_default=opened.append, out=out.append)
        self.assertIsNone(r); self.assertIn("could not start edge", out[0])

    def test_a_running_instance_is_found_and_a_stale_lock_is_ignored(self):
        d = tempfile.mkdtemp(); p = os.path.join(d, "ui.lock")
        self.assertIsNone(ui_app.running_instance(p))
        ui_app.write_lock("http://127.0.0.1:9/?k=x", 9, p)
        self.assertIsNone(ui_app.running_instance(p, connect=mock.Mock(side_effect=OSError("refused"))))        # nothing listening: stale
        ok = mock.MagicMock()
        self.assertEqual(ui_app.running_instance(p, connect=lambda *a, **k: ok), "http://127.0.0.1:9/?k=x")
        open(p, "w").write("{broken"); self.assertIsNone(ui_app.running_instance(p))

    def test_run_serves_until_the_window_is_closed_and_then_shuts_everything_down(self):
        c, ws, st = mk([GOOD])
        opened = []
        def fake_window(url):
            opened.append(url)
            def client():
                time.sleep(0.2)
                import urllib.request
                from urllib.parse import urlparse
                u = urlparse(url)
                conn = http.client.HTTPConnection(u.hostname, u.port, timeout=5)
                conn.request("GET", "/?k=" + u.query[2:]); r = conn.getresponse(); cookie = r.getheader("Set-Cookie").split(";")[0]; r.read()
                conn.close()
                conn = http.client.HTTPConnection(u.hostname, u.port, timeout=5)
                conn.request("GET", "/api/frames", headers={"Cookie": cookie}); r = conn.getresponse(); r.fp.readline()
                time.sleep(0.3)
                r.close(); conn.close()                                          # the window closes
            threading.Thread(target=client, daemon=True).start()
            return None
        with mock.patch.object(ui_app, "GRACE_S", 0.6), mock.patch.dict(os.environ, {"PRAXIS_HOME": tempfile.mkdtemp()}):
            t0 = time.time()
            rc = ui_app.run(c, open_window=fake_window, out=lambda *a: None, poll_s=0.05)
        self.assertEqual(rc, 0); self.assertEqual(len(opened), 1); self.assertLess(time.time() - t0, 15)
        self.assertFalse(os.path.exists(ui_app.lock_path()))


if __name__ == "__main__":
    unittest.main()
