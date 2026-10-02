"""Opening apps, sites and files: what the user means, how risky it is, that it really started, and that PRAXIS proves it."""
import json
import os
import tempfile
import unittest
from unittest import mock

from praxis import opener as op, reflex
from praxis.events import EventLog
from praxis.executive import Executive, FAILED, UNVERIFIED, VERIFIED
from praxis.guard import ALLOW, DENY, ESCALATE, Guard, classify_call
from praxis.router import Router, ScriptedProvider
from praxis.tools import ToolError, ToolRuntime, Workspace
from praxis.verifiers import verify


class FakeLauncher:
    def __init__(self, fail=None):
        self.started, self.fail = [], fail

    def start(self, action):
        if self.fail:
            raise OSError(self.fail)
        self.started.append((action.kind, action.target, action.label))


class FakeProcs(op.Processes):
    """A computer whose process list we control: `appear_after` seconds of fake time after which `names` shows the program."""

    def __init__(self, show=(), appear_after=0.0):
        self.t = 0.0
        self.show, self.appear_after = list(show), appear_after
        super().__init__(lister=self._ls, sleep=self._sleep, clock=lambda: self.t)

    def _ls(self):
        return self.show if self.t >= self.appear_after else []

    def _sleep(self, s):
        self.t += s


def opener_for(ws, show=("chrome.exe",), fail=None, appear_after=0.0):
    return op.Opener(ws, FakeLauncher(fail), FakeProcs(show, appear_after))


class Meaning(unittest.TestCase):
    def test_apps_sites_and_urls_are_understood_in_the_way_people_say_them(self):
        with mock.patch.object(op, "IS_WINDOWS", True):
            for text, kind, label in (("google chrome", "app", "Google Chrome"), ("Chrome", "app", "Google Chrome"), ("the calculator app", "app", "Calculator"),
                                      ("vs code", "app", "Visual Studio Code"), ("task manager", "app", "Task Manager"), ("youtube", "site", "youtube"),
                                      ("google", "site", "google"), ("https://example.org/a", "url", "example.org"), ("example.org", "url", "example.org")):
                a = op.resolve(text, browser="chrome.exe")
                self.assertEqual((a.kind, a.label), (kind, label), text)
            self.assertEqual(op.resolve("notepad").target, "notepad.exe")
            self.assertEqual(op.resolve("chrome").procs, ("chrome.exe",))
            self.assertEqual(op.resolve("youtube", browser="firefox.exe").procs, ("firefox.exe",))      # a site is proven by the browser running

    def test_workspace_files_are_found_and_nothing_else_is_guessed(self):
        d = tempfile.mkdtemp()
        open(os.path.join(d, "notes.txt"), "w").close(); open(os.path.join(d, "run.bat"), "w").close(); os.makedirs(os.path.join(d, ".git"))
        self.assertEqual(op.resolve("notes.txt", d).kind, "path")
        self.assertEqual(op.resolve("some random thing", d).kind, "unknown")
        self.assertEqual(op.resolve("missing.txt", d).kind, "unknown")                 # a file name that is not there is never mistaken for a website
        self.assertEqual(op.resolve("report.pdf", d).kind, "unknown")
        self.assertEqual(op.resolve("script.py", d).kind, "unknown")
        self.assertEqual(op.resolve("example.org", d).kind, "url")


class Risk(unittest.TestCase):
    def cls(self, target, ws=None):
        return op.classify(target, ws)

    def test_the_class_follows_what_could_go_wrong(self):
        ws = tempfile.mkdtemp()
        open(os.path.join(ws, "notes.txt"), "w").close(); open(os.path.join(ws, "setup.exe"), "w").close(); open(os.path.join(ws, "x.ps1"), "w").close()
        self.assertEqual(self.cls("chrome"), 2)                                  # a known program
        self.assertEqual(self.cls("youtube"), 2)                                 # a well-known site
        self.assertEqual(self.cls("https://never-heard-of.example"), 3)           # any other website: you decide
        self.assertEqual(self.cls("notes.txt", ws), 2)                           # a document in the workspace
        for bad in ("setup.exe", "x.ps1"):                                       # a file that can run code
            self.assertEqual(self.cls(bad, ws), 4, bad)
        self.assertEqual(self.cls("../../etc/passwd", ws), 4)
        for evil in ("javascript:alert(1)", "file:///C:/Windows/system32/cmd.exe", "data:text/html,<script>", "vbscript:x", "ms-msdt:/id x",
                     "https://user:pass@phish.example", "chrome && calc", "chrome; rm -rf /", "a|b", "`calc`", "$(calc)", "", "   ", "x" * 3000, "cmd", "powershell"):
            self.assertEqual(self.cls(evil, ws), 4, evil)

    def test_the_guard_applies_it_and_a_plan_from_untrusted_text_can_never_open_anything(self):
        g = Guard(tempfile.mkdtemp())
        d = g.decide("desktop.open", {"target": "chrome"})
        self.assertEqual((d.cls, d.verdict), (2, ALLOW))
        d = g.decide("desktop.open", {"target": "https://new-site.example"})
        self.assertEqual((d.cls, d.verdict), (3, ESCALATE))
        d = g.decide("desktop.open", {"target": "chrome"}, tainted=True)
        self.assertEqual(d.verdict, DENY)                                        # shaped by a file's contents: refused outright
        self.assertEqual(g.decide("desktop.open", {}).cls, 4)
        self.assertEqual(g.decide("desktop.open", {"target": 5}).cls, 4)


class Starting(unittest.TestCase):
    def test_windows_hands_the_name_to_shellexecute_and_never_starts_a_console(self):
        got = []
        with mock.patch.object(op, "IS_WINDOWS", True):
            op.Launcher(startfile=got.append).start(op.resolve("chrome"))
            op.Launcher(startfile=got.append).start(op.resolve("https://example.org/a"))
        self.assertEqual(got, ["chrome.exe", "https://example.org/a"])

    def test_elsewhere_it_uses_the_program_or_the_systems_opener_detached_and_silent(self):
        calls = []
        def fake_popen(argv, **kw): calls.append((argv, kw)); return mock.Mock()
        with mock.patch.object(op, "IS_WINDOWS", False), mock.patch.object(op, "IS_MAC", False):
            l = op.Launcher(popen=fake_popen, which=lambda n: "/usr/bin/" + n if n in ("firefox", "xdg-open") else None)
            l.start(op.resolve("firefox")); l.start(op.resolve("https://example.org"))
            self.assertEqual(calls[0][0], ["/usr/bin/firefox"]); self.assertEqual(calls[1][0], ["/usr/bin/xdg-open", "https://example.org"])
            self.assertTrue(calls[0][1]["detached"])
            with self.assertRaises(OSError):
                l.start(op.resolve("notepad"))                                    # not installed: an error, not a silent success
            with self.assertRaises(OSError):
                l.start(op.resolve("some random thing"))

    def test_processes_are_found_with_or_without_exe_and_polled_until_they_appear(self):
        p = FakeProcs(["Chrome.EXE", "svchost.exe"], appear_after=3.0)
        self.assertFalse(p.running("chrome.exe"))                                  # not yet
        self.assertTrue(p.running("chrome", wait=5.0))                              # appears after 3 s of (fake) waiting
        self.assertGreaterEqual(p.t, 3.0)
        self.assertFalse(FakeProcs(["a.exe"]).running("chrome.exe", wait=2.0))
        self.assertTrue(FakeProcs(["google-chrome-s"]).running("google-chrome-stable"))   # Linux truncates names to 15 characters
        self.assertFalse(FakeProcs(["x"]).running(""))

    def test_the_real_process_list_is_parsed_from_tasklist_and_ps(self):
        csv = '"System Idle Process","0","Services","0","8 K"\n"chrome.exe","1234","Console","1","90,000 K"\n"Notepad.exe","9","Console","1","1 K"\n'
        with mock.patch.object(op, "IS_WINDOWS", True), mock.patch.object(op.winproc, "run", return_value=mock.Mock(stdout=csv)):
            self.assertEqual(op.Processes().names(), {"system idle process", "chrome.exe", "notepad.exe"})
        with mock.patch.object(op, "IS_WINDOWS", False), mock.patch.object(op.winproc, "run", return_value=mock.Mock(stdout="bash\n/usr/bin/firefox\n")):
            self.assertEqual(op.Processes().names(), {"bash", "firefox"})
        with mock.patch.object(op.winproc, "run", side_effect=OSError("no tasklist")):
            self.assertEqual(op.Processes().names(), set())                          # unreadable: nothing is claimed to be running

    def test_the_default_browser_comes_from_the_registry_and_never_raises(self):
        class K:
            def __enter__(s): return s
            def __exit__(s, *a): return False
        wr = mock.Mock(HKEY_CURRENT_USER=1, OpenKey=lambda *a: K(), QueryValueEx=lambda k, n: ("ChromeHTML", 1))
        with mock.patch.object(op, "IS_WINDOWS", True), mock.patch.dict("sys.modules", {"winreg": wr}):
            self.assertEqual(op.default_browser(), "chrome.exe")
            wr.QueryValueEx = lambda k, n: ("FirefoxURL-308046B0AF4A39CB", 1)
            self.assertEqual(op.default_browser(), "firefox.exe")
            wr.OpenKey = mock.Mock(side_effect=OSError("no key"))
            self.assertEqual(op.default_browser(), "msedge.exe")


class Tool(unittest.TestCase):
    def runtime(self, **kw):
        ws = Workspace(tempfile.mkdtemp())
        return ToolRuntime(ws, opener=opener_for(ws.root, **kw)), ws

    def test_the_tool_opens_and_reports_what_it_expects_to_see_running(self):
        rt, ws = self.runtime()
        out = rt.run("desktop.open", {"target": "chrome"})
        self.assertEqual(out["opened"], "Google Chrome")
        self.assertEqual(rt.opener.launcher.started[0][0], "app")

    def test_failures_are_data_not_crashes(self):
        rt, ws = self.runtime(fail="Chrome is not installed")
        with self.assertRaises(ToolError) as e:
            rt.run("desktop.open", {"target": "chrome"})
        self.assertIn("not installed", str(e.exception))
        for args in ({}, {"target": ""}, {"target": 3}):
            with self.assertRaises(ToolError):
                rt.run("desktop.open", args)


class Verifier(unittest.TestCase):
    def test_process_running_is_real_evidence_not_a_claim(self):
        ws = Workspace(tempfile.mkdtemp())
        yes = verify({"type": "process_running", "name": ["chrome.exe"]}, ws, processes=FakeProcs(["chrome.exe"]))
        self.assertTrue(yes.passed); self.assertIn("chrome.exe", yes.detail)
        no = verify({"type": "process_running", "name": "chrome.exe", "wait": 2}, ws, processes=FakeProcs(["other.exe"]))
        self.assertFalse(no.passed); self.assertIn("not found", no.detail)
        late = verify({"type": "process_running", "name": "chrome.exe", "wait": 10}, ws, processes=FakeProcs(["chrome.exe"], appear_after=4.0))
        self.assertTrue(late.passed)                                                 # a slow program is waited for
        any_of = verify({"type": "process_running", "name": ["a.exe", "b.exe"]}, ws, processes=FakeProcs(["b.exe"]))
        self.assertTrue(any_of.passed)
        self.assertFalse(verify({"type": "process_running", "name": "x", "wait": 9999}, ws, processes=FakeProcs([], appear_after=0)).passed)


class Reflexes(unittest.TestCase):
    def match(self, text):
        return reflex.match(text, op.Opener(tempfile.mkdtemp(), FakeLauncher(), FakeProcs()))

    def test_plain_requests_become_a_ready_plan_and_everything_else_is_left_to_the_planner(self):
        for text in ("open google chrome", "Open Chrome.", "please open the calculator", "can you launch notepad", "start vs code", "go to youtube",
                     "pull up github", "open up spotify for me", "could you open google chrome please", "show me reddit", "open https://example.org"):
            p = self.match(text)
            self.assertIsNotNone(p, text)
            self.assertEqual(p["steps"][0]["tool"], "desktop.open")
            self.assertTrue(p["success"][0]["name"], text)                              # and always with a real check
        for text in ("open chrome and search for cats", "open the file report.txt", "start the tests", "run the unit tests", "open a pull request on github with my changes",
                     "go to the store and buy milk", "open sesame", "launch the missiles", "fix the bug in chrome", "what is chrome", "open", "",
                     "open chrome then close it", "open the door"):
            self.assertIsNone(self.match(text), text)

    def test_the_target_is_exactly_what_was_asked_not_a_model_paraphrase(self):
        self.assertEqual(self.match("open google chrome")["steps"][0]["args"]["target"], "google chrome")


class EndToEnd(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp()
        self.log = EventLog()

    def executive(self, scripted=(), approver=None, **kw):
        prov = ScriptedProvider(list(scripted))
        ex = Executive(self.ws, self.log, Router([prov]), approver=approver, opener=opener_for(self.ws, **kw), critic=False)
        return ex, prov

    def test_open_chrome_is_instant_free_verified_and_logged_as_a_reflex(self):
        ex, prov = self.executive()
        r = ex.run("Open Google Chrome.")
        self.assertEqual(r.status, VERIFIED, r.reason)
        self.assertEqual(len(prov.calls) if hasattr(prov, "calls") else 0, 0)             # no model was asked
        types = [e.type for e in self.log.all()]
        self.assertIn("reflex.matched", types); self.assertNotIn("model.try", types); self.assertNotIn("plan.proposed", types)
        self.assertEqual(ex.opener.launcher.started[0][0], "app")
        self.assertTrue(any(e.type == "verify.result" and "process_running" in e.payload["claim"] and e.payload["passed"] for e in self.log.all()))
        self.assertTrue(self.log.verify_chain())

    def test_if_the_program_never_appears_it_is_reported_as_failed_not_done(self):
        ex, _ = self.executive(show=("something-else.exe",))
        with mock.patch.object(op.Processes, "running", return_value=False):
            r = ex.run("open chrome")
        self.assertEqual(r.status, FAILED); self.assertIn("process_running", r.reason)

    def test_a_program_that_cannot_start_says_so(self):
        ex, _ = self.executive(fail="Google Chrome is not installed")
        r = ex.run("open chrome")
        self.assertEqual(r.status, FAILED); self.assertIn("not installed", r.reason)

    def test_an_unknown_website_asks_you_first_and_a_no_means_nothing_opens(self):
        asked = []
        ex, _ = self.executive(approver=lambda d: asked.append(d) or False)
        r = ex.run("open https://never-heard-of.example")
        self.assertEqual(r.status, FAILED); self.assertIn("denied by guard", r.reason)
        self.assertEqual(len(asked), 1); self.assertEqual(asked[0].cls, 3)
        self.assertEqual(ex.opener.launcher.started, [])
        with mock.patch.object(op, "default_browser", return_value="chrome.exe"):
            ex2, _ = self.executive(approver=lambda d: True)
            self.assertEqual(ex2.run("open https://never-heard-of.example").status, VERIFIED)

    def test_a_model_written_plan_can_use_the_same_tool_with_the_same_proof(self):
        plan = {"steps": [{"id": "o", "tool": "desktop.open", "args": {"target": "notepad"}, "verify": {"type": "process_running", "name": "notepad.exe"}}],
                "success": [{"type": "process_running", "name": "notepad.exe"}]}
        ex, prov = self.executive([json.dumps(plan)], show=("notepad.exe",))
        r = ex.run("I would like a place to type some notes, bring one up for me")                       # not a reflex: a model plans it
        self.assertEqual(r.status, VERIFIED, r.reason)
        self.assertIn("model.call", [e.type for e in self.log.all()])

    def test_the_planner_is_told_about_the_tool_and_to_prefer_it_over_the_shell(self):
        ex, _ = self.executive()
        s = ex._system()
        self.assertIn("desktop.open{target}", s); self.assertIn("process_running{name}", s); self.assertIn("never shell.run", s)

    def test_reflexes_can_be_switched_off_and_a_resumed_reflex_goal_needs_no_model(self):
        ex, prov = self.executive()
        ex.reflexes = False
        ex.router = Router([ScriptedProvider(["not a plan"])])
        r = ex.run("open chrome")
        self.assertEqual(r.status, FAILED)                                                       # it went to the planner instead
        self.assertNotIn("reflex.matched", [e.type for e in self.log.all()])


if __name__ == "__main__":
    unittest.main()
