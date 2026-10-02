import json, os, tempfile, threading, time, types, unittest
from praxis.desktop.controller import Controller
from praxis.desktop.settings import Settings
from praxis.hardware import GB, GPU, Profile
from praxis.registry import Registry
from praxis.router import Router, ScriptedProvider
from praxis.sandbox import Sandbox
from praxis.usage import UsageTracker
from tests.test_executive import plan, W


def fake_stack(responses, agents=None, hook=None):
    class Prov(ScriptedProvider):
        def complete(self, role, messages):
            if hook: hook()
            return super().complete(role, messages)
    prov = Prov(responses, name="scripted")
    cfg = {"limits": {"max_steps": 20, "max_model_calls": 8, "max_cost_usd": 0}, "privacy": {"data_class": "project"}}
    return types.SimpleNamespace(
        providers=[prov], router=Router([prov]), agents=agents or {}, sandbox=Sandbox(), cfg=cfg, registry=Registry(),
        skipped={"codex": "not installed"}, usage=UsageTracker(), profile=Profile("linux", "cpu", 4, 16 * GB, 50, []), prov=prov)


def wait(pred, t=8.0):
    end = time.time() + t
    while time.time() < end:
        if pred(): return True
        time.sleep(0.02)
    return False


def mk(responses, **kw):
    ws, home = tempfile.mkdtemp(), tempfile.mkdtemp()
    st = fake_stack(responses, kw.pop("agents", None), kw.pop("hook", None))
    c = Controller(ws, stack_factory=lambda w: st, home=home, **kw)
    c.start(); assert wait(lambda: c.state == "idle"), c.state
    return c, ws, st


GOOD = plan([W("s1", "a.txt", "1")], [{"type": "file_exists", "path": "a.txt"}])


class FakeAgent:
    can_delegate = True
    def delegate(self, task, cwd):
        open(os.path.join(cwd, "made.txt"), "w").write("x"); return "done"


class Lifecycle(unittest.TestCase):
    def test_starts_idle_and_exposes_stack_info(self):
        c, ws, st = mk([GOOD])
        self.assertEqual(c.info["providers"], ["scripted"]); self.assertEqual(c.info["skipped"], {"codex": "not installed"})
        self.assertEqual(c.info["sandbox"], "none")

    def test_stack_failure_is_reported_not_raised(self):
        def boom(w): raise RuntimeError("no providers")
        c = Controller(tempfile.mkdtemp(), stack_factory=boom, home=tempfile.mkdtemp()); c.start()
        self.assertTrue(wait(lambda: c.state == "error")); self.assertIn("no providers", c.error)

    def test_submit_runs_to_a_verified_view(self):
        c, ws, st = mk([GOOD])
        self.assertTrue(c.submit("make a.txt"))
        self.assertTrue(wait(lambda: c.state == "idle" and c.poll().view.status == "VERIFIED"))
        u = c.poll()
        self.assertEqual(u.view.steps[0].state, "verified"); self.assertTrue(os.path.exists(os.path.join(ws, "a.txt")))
        self.assertEqual(c.verify_log(), (True, None))

    def test_events_are_delivered_incrementally_and_once(self):
        c, ws, st = mk([GOOD]); c.submit("x")
        seen = []
        end = time.time() + 8
        while time.time() < end and not any(e.type == "goal.report" for e in seen):
            seen += c.poll().events; time.sleep(0.02)
        ids = [e.id for e in seen]
        self.assertEqual(ids, sorted(set(ids)))        # no duplicates, in order
        self.assertEqual(c.poll().events, [])          # nothing new on the next poll

    def test_second_submit_while_busy_is_refused(self):
        gate = threading.Event()
        c, ws, st = mk([GOOD], hook=lambda: gate.wait(5))
        self.assertTrue(c.submit("x")); self.assertTrue(wait(lambda: c.state == "working"))
        self.assertFalse(c.submit("y")); gate.set(); self.assertTrue(wait(lambda: c.state == "idle"))


class KillSwitch(unittest.TestCase):
    def test_stop_cancels_rolls_back_and_returns_to_idle(self):
        gate = threading.Event(); started = threading.Event()
        steps = [W("s1", "a.txt", "1"), W("s2", "b.txt", "2", deps=["s1"])]
        c, ws, st = mk([plan(steps, [{"type": "file_exists", "path": "b.txt"}])])
        # stop right after step 1 runs (before step 2)
        real = None
        def wrap():
            ex = c._executive
            r = ex.tools.run
            def hooked(tool, args):
                out = r(tool, args)
                if args.get("path") == "a.txt":
                    started.set(); c.stop()
                return out
            ex.tools.run = hooked
        c._on_executive_built = wrap
        c.submit("x")
        self.assertTrue(wait(lambda: c.state == "idle", 10))
        v = c.poll().view
        self.assertEqual(v.status, "CANCELLED"); self.assertTrue(v.rolled_back)
        self.assertFalse(os.path.exists(os.path.join(ws, "a.txt")))

    def test_stop_while_idle_is_harmless(self):
        c, ws, st = mk([GOOD]); c.stop(); self.assertEqual(c.state, "idle")
        self.assertTrue(c.submit("x")); self.assertTrue(wait(lambda: c.poll().view.status == "VERIFIED"))   # not poisoned


class Approvals(unittest.TestCase):
    PLAN = plan([{"id": "s1", "tool": "agent.delegate", "args": {"agent": "claude", "task": "make made.txt"},
                  "verify": {"type": "file_exists", "path": "made.txt"}, "deps": []}], [{"type": "file_exists", "path": "made.txt"}])

    def test_approval_request_surfaces_and_approve_proceeds(self):
        c, ws, st = mk([self.PLAN], agents={"claude": FakeAgent()})
        c.submit("delegate")
        self.assertTrue(wait(lambda: bool(c.poll().approvals)))
        req = c.poll().approvals[0]
        self.assertEqual(req.tool, "agent.delegate"); self.assertEqual(req.cls, 3)
        self.assertIn("make made.txt", req.args["task"]); self.assertEqual(c.state, "working")
        self.assertEqual(c.poll().view.status, "WAITING FOR YOU")
        c.respond(req.id, True)
        self.assertTrue(wait(lambda: c.poll().view.status == "VERIFIED")); self.assertTrue(os.path.exists(os.path.join(ws, "made.txt")))
        self.assertEqual(c.poll().approvals, [])

    def test_deny_blocks_the_action(self):
        c, ws, st = mk([self.PLAN], agents={"claude": FakeAgent()}); c.submit("d")
        self.assertTrue(wait(lambda: bool(c.poll().approvals))); c.respond(c.poll().approvals[0].id, False)
        self.assertTrue(wait(lambda: c.state == "idle")); self.assertFalse(os.path.exists(os.path.join(ws, "made.txt")))
        self.assertEqual(c.poll().view.status, "FAILED")

    def test_unanswered_approval_times_out_to_deny(self):
        c, ws, st = mk([self.PLAN], agents={"claude": FakeAgent()}, approval_timeout=0.3); c.submit("d")
        self.assertTrue(wait(lambda: c.state == "idle", 6)); self.assertFalse(os.path.exists(os.path.join(ws, "made.txt")))

    def test_stop_while_waiting_for_approval_unblocks_and_cancels(self):
        c, ws, st = mk([self.PLAN], agents={"claude": FakeAgent()}); c.submit("d")
        self.assertTrue(wait(lambda: bool(c.poll().approvals))); c.stop()
        self.assertTrue(wait(lambda: c.state == "idle", 6)); self.assertFalse(os.path.exists(os.path.join(ws, "made.txt")))

    def test_unknown_request_id_is_ignored(self):
        c, ws, st = mk([GOOD]); c.respond("nope", True)   # must not raise


class Recovery(unittest.TestCase):
    def test_unfinished_goal_is_offered_and_resumable(self):
        ws, home = tempfile.mkdtemp(), tempfile.mkdtemp()
        from praxis.events import EventLog
        from praxis.executive import Executive, parse_plan
        os.makedirs(os.path.join(ws, ".praxis"))
        log = EventLog(os.path.join(ws, ".praxis", "events.db"))
        i = log.append("g1", "user", "goal.intent", {"text": "crashed goal"})
        ex0 = Executive(ws, log, Router([]))
        a = log.append("g1", "executive", "plan.accepted", {"plan": parse_plan(GOOD), "initial": True, "tainted": False}, [i])
        log.append("g1", "executive", "checkpoint", {"id": ex0.ws.checkpoint()}, [a])
        log.db.close()
        st = fake_stack([])
        c = Controller(ws, stack_factory=lambda w: st, home=home); c.start(); wait(lambda: c.state == "idle")
        self.assertEqual(c.unfinished(), ["g1"])
        self.assertTrue(c.resume()); self.assertTrue(wait(lambda: c.state == "idle" and c.poll().view.status == "VERIFIED"))
        self.assertEqual(c.unfinished(), [])


class Inspect(unittest.TestCase):
    def test_why_and_memory_search_and_workspace_switch(self):
        c, ws, st = mk([GOOD]); c.submit("create the alpha file"); wait(lambda: c.poll().view.status == "VERIFIED")
        res = [e for e in c.poll().events] or c.all_events()
        tool = next(e for e in c.all_events() if e.type == "tool.result")
        self.assertIn("create the alpha file", c.why(tool.id))
        self.assertEqual(c.memory_search("alpha file")[0]["status"], "VERIFIED")
        ws2 = tempfile.mkdtemp()
        self.assertTrue(c.open_workspace(ws2)); wait(lambda: c.state == "idle")
        self.assertEqual(c.workspace, os.path.realpath(ws2)); self.assertEqual(c.all_events(), [])   # fresh log per workspace

    def test_cannot_switch_workspace_while_working(self):
        gate = threading.Event()
        c, ws, st = mk([GOOD], hook=lambda: gate.wait(5)); c.submit("x"); wait(lambda: c.state == "working")
        self.assertFalse(c.open_workspace(tempfile.mkdtemp())); gate.set()


class SettingsTests(unittest.TestCase):
    def test_recent_workspaces_roundtrip_dedupe_and_cap(self):
        home = tempfile.mkdtemp(); s = Settings(home)
        for i in range(12):
            s.add_recent(f"/w/{i}")
        s.add_recent("/w/3")
        s.save()
        s2 = Settings(home)
        self.assertEqual(s2.recent[0], "/w/3"); self.assertEqual(len(s2.recent), 8); self.assertEqual(len(set(s2.recent)), 8)

    def test_corrupt_settings_file_does_not_crash(self):
        home = tempfile.mkdtemp(); open(os.path.join(home, "desktop.json"), "w").write("{not json")
        self.assertEqual(Settings(home).recent, [])


if __name__ == "__main__":
    unittest.main()


class EscalationWiring(unittest.TestCase):
    """The UI's controller must hand the config's escalation setting to the executive (a weak model's failed work is retried)."""
    BADP = plan([W("s1", "a.txt", "wrong")], [{"type": "file_contains", "path": "a.txt", "text": "RIGHT"}])
    GOODP = plan([W("s1", "a.txt", "RIGHT")], [{"type": "file_contains", "path": "a.txt", "text": "RIGHT"}])

    def stack(self, escalate):
        cheap = ScriptedProvider([self.BADP], name="cheap"); cheap.tier = "free"
        strong = ScriptedProvider([self.GOODP], name="strong"); strong.tier = "best"
        cfg = {"limits": {"max_steps": 20, "max_model_calls": 8, "max_cost_usd": 0}, "privacy": {"data_class": "project"},
               "routing": {"escalate": escalate, "max_escalations": 2}}
        return types.SimpleNamespace(providers=[cheap, strong], router=Router([cheap, strong], {"planner": ["cheap", "strong"]}, None, "config"),
                                     agents={}, sandbox=Sandbox(), cfg=cfg, registry=Registry(), skipped={}, usage=UsageTracker(),
                                     profile=Profile("linux", "cpu", 4, 16 * GB, 50, []), cheap=cheap, strong=strong)

    def run_goal(self, escalate):
        ws, home = tempfile.mkdtemp(), tempfile.mkdtemp()
        st = self.stack(escalate)
        c = Controller(ws, stack_factory=lambda w: st, home=home); c.start()
        assert wait(lambda: c.state == "idle")
        self.assertTrue(c.submit("write RIGHT into a.txt", no_critic=True))
        end = time.time() + 10
        while c.state != "idle" and time.time() < end:
            for req in c.poll().approvals:                       # without escalation the executive falls back to a replan, which asks
                c.respond(req.id, False)                          # the human first: answer as a user pressing Deny would
            time.sleep(0.02)
        self.assertEqual(c.state, "idle")
        return c, ws, st

    def escalations(self, c):
        return [e for e in c.all_events() if e.type == "escalation"]

    def test_a_failed_verification_is_retried_by_the_stronger_model_when_escalation_is_on(self):
        c, ws, st = self.run_goal(True)
        self.assertEqual(c.poll().view.status, "VERIFIED")
        self.assertEqual(len(self.escalations(c)), 1); self.assertEqual(self.escalations(c)[0].payload["from"], "cheap")
        self.assertEqual(open(os.path.join(ws, "a.txt"), encoding="utf-8").read(), "RIGHT")

    def test_with_escalation_off_there_is_no_escalation_and_the_goal_does_not_verify(self):
        c, ws, st = self.run_goal(False)
        self.assertEqual(self.escalations(c), [])                              # the flag really reached the executive
        self.assertEqual(c.poll().view.status, "FAILED")
