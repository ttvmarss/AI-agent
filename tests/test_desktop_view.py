import json, unittest
from praxis.events import EventLog
from praxis.desktop.view import build_view, summarize
from praxis.desktop.telemetry import parse_cpu_stat, parse_nvidia_usage, cpu_percent
from praxis.executive import Executive
from praxis.router import Router, ScriptedProvider
import tempfile
from tests.test_executive import plan, W


def run_goal(responses, approver=None, **kw):
    ws, log = tempfile.mkdtemp(), EventLog()
    ex = Executive(ws, log, Router([ScriptedProvider(responses)]), approver=approver, **kw)
    rep = ex.run("make files")
    return ex, ws, log, rep


class Summaries(unittest.TestCase):
    def test_every_event_type_the_executive_emits_has_a_human_summary(self):
        steps = [W("s1", "a.txt", "1"), {"id": "s2", "tool": "shell.run", "args": {"cmd": "touch x"},
                                         "verify": {"type": "none"}, "deps": ["s1"]}]
        ex, ws, log, rep = run_goal([plan(steps, [{"type": "file_exists", "path": "a.txt"}])])
        for e in log.all():
            text, level = summarize(e)
            self.assertTrue(text and level in ("info", "ok", "warn", "bad"), (e.type, text, level))
            self.assertNotIn("{", text)  # no raw JSON dumps in the activity feed

    def test_guard_denial_is_bad_and_explains_why(self):
        steps = [{"id": "s1", "tool": "shell.run", "args": {"cmd": "curl http://x"}, "verify": {"type": "none"}, "deps": []}]
        ex, ws, log, rep = run_goal([plan(steps, [{"type": "none"}])])
        g = [summarize(e) for e in log.all(type_="guard.decision")][0]
        self.assertEqual(g[1], "bad"); self.assertIn("Class 3", g[0]); self.assertIn("ESCALATE", g[0])

    def test_unknown_event_type_still_renders(self):
        log = EventLog(); i = log.append("g", "x", "mystery.event", {"a": 1})
        text, level = summarize(log.get(i))
        self.assertIn("mystery.event", text)


class View(unittest.TestCase):
    def test_happy_path_view(self):
        steps = [W("s1", "a.txt", "1"), W("s2", "b.txt", "2", deps=["s1"])]
        ex, ws, log, rep = run_goal([plan(steps, [{"type": "file_exists", "path": "b.txt"}])])
        v = build_view(log.all())
        self.assertEqual(v.status, "VERIFIED"); self.assertEqual(v.goal_text, "make files")
        self.assertEqual([s.id for s in v.steps], ["s1", "s2"])
        self.assertTrue(all(s.state == "verified" for s in v.steps))
        self.assertTrue(all(e["passed"] for e in v.evidence)); self.assertGreaterEqual(len(v.evidence), 3)
        self.assertEqual(v.steps[0].cls, 2)

    def test_denied_step_and_rollback_show_in_view(self):
        steps = [W("s1", "a.txt", "1"), {"id": "s2", "tool": "shell.run", "args": {"cmd": "rm -rf ."},
                                         "verify": {"type": "none"}, "deps": ["s1"]}]
        ex, ws, log, rep = run_goal([plan(steps, [{"type": "none"}])])
        v = build_view(log.all())
        self.assertEqual(v.status, "FAILED"); self.assertTrue(v.rolled_back)
        states = {s.id: s.state for s in v.steps}
        self.assertEqual(states["s2"], "denied"); self.assertEqual(states["s1"], "rolled back")  # s1 ran, then was undone

    def test_running_goal_shows_current_phase(self):
        log = EventLog()
        i = log.append("g", "user", "goal.intent", {"text": "t"})
        v = build_view(log.all()); self.assertEqual(v.status, "PLANNING")
        a = log.append("g", "executive", "plan.accepted", {"plan": {"steps": [{"id": "s1", "tool": "fs.read", "args": {"path": "a"}, "deps": [], "verify": {"type": "none"}}], "success": []}, "initial": True, "tainted": False}, [i])
        c = log.append("g", "executive", "checkpoint", {"id": "c"}, [a])
        log.append("g", "executive", "step.intent", {"step": "s1", "tool": "fs.read", "args": {"path": "a"}}, [a])
        v = build_view(log.all()); self.assertEqual(v.status, "RUNNING")
        self.assertEqual(v.steps[0].state, "running")

    def test_view_tracks_only_the_latest_goal_but_knows_cost(self):
        log = EventLog()
        log.append("g1", "user", "goal.intent", {"text": "old"})
        log.append("g2", "user", "goal.intent", {"text": "new"})
        log.append("g2", "router", "model.call", {"provider": "claude", "ok": True, "cost_usd": 0.05})
        log.append("g2", "router", "model.call", {"provider": "claude", "ok": True, "cost_usd": 0.02})
        v = build_view(log.all()); self.assertEqual(v.goal_text, "new"); self.assertAlmostEqual(v.cost, 0.07)

    def test_waiting_for_human_when_escalated_without_authorization(self):
        log = EventLog()
        i = log.append("g", "user", "goal.intent", {"text": "t"})
        a = log.append("g", "executive", "plan.accepted", {"plan": {"steps": [{"id": "s1", "tool": "shell.run", "args": {"cmd": "curl x"}, "deps": [], "verify": {"type": "none"}}], "success": []}, "initial": True, "tainted": False}, [i])
        s = log.append("g", "executive", "step.intent", {"step": "s1", "tool": "shell.run", "args": {}}, [a])
        log.append("g", "guard", "guard.decision", {"step": "s1", "class": 3, "verdict": "ESCALATE", "reason": "x"}, [s])
        self.assertEqual(build_view(log.all()).status, "WAITING FOR YOU")

    def test_empty_log(self):
        v = build_view([]); self.assertEqual(v.status, "IDLE"); self.assertEqual(v.steps, [])


class Telemetry(unittest.TestCase):
    def test_cpu_stat_and_percent(self):
        a = parse_cpu_stat("cpu  100 0 100 800 0 0 0 0 0 0\ncpu0 1 2 3 4"); b = parse_cpu_stat("cpu  150 0 150 900 0 0 0 0 0 0")
        self.assertAlmostEqual(cpu_percent(a, b), 50.0)         # 100 busy ticks of 200 total
        self.assertEqual(cpu_percent(a, a), 0.0)

    def test_nvidia_usage(self):
        g = parse_nvidia_usage("NVIDIA GeForce RTX 3050, 37, 3100, 8192, 61\n")
        self.assertEqual(g[0]["util"], 37); self.assertEqual(g[0]["vram_used_gb"], round(3100 / 1024, 2))
        self.assertEqual(g[0]["temp"], 61); self.assertEqual(parse_nvidia_usage(""), [])


if __name__ == "__main__":
    unittest.main()
