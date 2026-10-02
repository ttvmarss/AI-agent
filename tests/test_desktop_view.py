import json, types, unittest
from praxis.events import EventLog
from praxis.desktop.view import ViewFolder, build_view, summarize
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

    def test_hard_deny_verdict_shows_as_denied(self):
        """The Guard's DENY verdict (e.g. a plan capped by untrusted content), distinct from a human refusing an ESCALATE."""
        log = EventLog()
        i = log.append("g", "user", "goal.intent", {"text": "t"})
        a = log.append("g", "executive", "plan.accepted", {"plan": {"steps": [{"id": "s1", "tool": "shell.run", "args": {"cmd": "curl x"}, "deps": [], "verify": {"type": "none"}}], "success": []}, "initial": True, "tainted": True}, [i])
        s = log.append("g", "executive", "step.intent", {"step": "s1", "tool": "shell.run", "args": {}}, [a])
        log.append("g", "guard", "guard.decision", {"step": "s1", "class": 3, "verdict": "DENY", "reason": "capped"}, [s])
        v = build_view(log.all())
        self.assertEqual(v.steps[0].state, "denied"); self.assertTrue(v.tainted)

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




class ActiveProvider(unittest.TestCase):
    """The core visualization lights a provider only while a call to it is really in flight."""

    def test_router_announces_each_attempt_before_making_it(self):
        from praxis.router import Router, ScriptedProvider, ProviderError
        a, b = ScriptedProvider([ProviderError("down")], name="a"), ScriptedProvider(["ok"], name="b")
        ev = []
        Router([a, b], {"planner": ["a", "b"]}).call("planner", [], on_event=lambda t, p: ev.append((t, p["provider"])))
        self.assertEqual([e for e in ev if e[0] in ("model.try", "model.call")],
                         [("model.try", "a"), ("model.call", "a"), ("model.try", "b"), ("model.call", "b")])

    def test_view_marks_the_provider_in_flight_and_clears_it_when_the_call_returns(self):
        log = EventLog()
        i = log.append("g", "user", "goal.intent", {"text": "t"})
        log.append("g", "router", "model.try", {"provider": "groq/x", "role": "planner"}, [i])
        self.assertEqual(build_view(log.all()).active_provider, "groq/x")
        log.append("g", "router", "model.call", {"provider": "groq/x", "role": "planner", "ok": True}, [i])
        self.assertEqual(build_view(log.all()).active_provider, "")
        log.append("g", "router", "model.try", {"provider": "claude/y", "role": "critic"}, [i])
        log.append("g", "router", "model.call", {"provider": "claude/y", "role": "critic", "ok": False, "error": "x"}, [i])
        self.assertEqual(build_view(log.all()).active_provider, "")

    def test_steps_carry_their_dependencies_for_the_graph(self):
        log = EventLog(); i = log.append("g", "user", "goal.intent", {"text": "t"})
        steps = [{"id": "a", "tool": "fs.read", "args": {"path": "x"}, "deps": [], "verify": {"type": "none"}},
                 {"id": "b", "tool": "fs.write", "args": {"path": "y", "content": ""}, "deps": ["a"], "verify": {"type": "none"}}]
        log.append("g", "executive", "plan.accepted", {"plan": {"steps": steps, "success": []}, "initial": True, "tainted": False}, [i])
        v = build_view(log.all())
        self.assertEqual([s.deps for s in v.steps], [[], ["a"]])

    def test_try_events_have_a_quiet_human_summary(self):
        log = EventLog(); i = log.append("g", "router", "model.try", {"provider": "groq/x", "role": "planner"})
        text, level = summarize(log.get(i))
        self.assertIn("groq/x", text); self.assertEqual(level, "info")


class IncrementalFold(unittest.TestCase):
    """The window polls ten times a second, so a poll must cost what is NEW, not what is old (6,000 events took 60 ms per poll)."""

    @staticmethod
    def ev(i, goal, type_, payload=None):
        return types.SimpleNamespace(id=i, goal_id=goal, type=type_, payload=payload or {}, actor="x", ts=0.0)

    def stream(self, r, n_goals=3, steps=4):
        out, i = [], 0
        for g in range(n_goals):
            gid = f"g{g}"
            seq = [("goal.intent", {"text": f"goal {g}"}), ("plan.accepted", {"plan": {"steps": [{"id": f"s{k}", "tool": "fs.write", "args": {"path": f"f{k}"}} for k in range(steps)]}}),
                   ("checkpoint", {"id": "cp"})]
            for k in range(steps):
                seq += [("model.try", {"provider": "claude"}), ("model.call", {"provider": "claude", "cost_usd": 0.01}), ("step.intent", {"step": f"s{k}"}),
                        ("guard.decision", {"step": f"s{k}", "verdict": r.choice(["ALLOW", "ESCALATE", "DENY"]), "class": 2}),
                        ("guard.authorization", {"step": f"s{k}", "verdict": r.choice(["ALLOW", "DENY"])}), ("tool.result", {"step": f"s{k}", "ok": r.random() < .8}),
                        ("verify.result", {"step": f"s{k}", "claim": "c", "passed": r.random() < .7})]
            if r.random() < .5:
                seq.append(("rollback", {}))
            seq.append(("goal.report", {"status": r.choice(["VERIFIED", "FAILED", "UNVERIFIED"]), "reason": "r"}))
            for t, p in seq:
                i += 1; out.append(self.ev(i, gid, t, p))
        return out

    def test_feeding_in_any_chunks_gives_the_same_view_as_folding_everything_at_once(self):
        import random
        for seed in range(60):
            r = random.Random(seed)
            events = self.stream(r)
            whole = build_view(events)
            f = ViewFolder(); k = 0
            while k < len(events):
                n = r.choice([1, 1, 2, 5, 17]); f.feed(events[k:k + n]); k += n
            self.assertEqual(f.view(), whole, seed)
            for cut in (3, 9, 30, len(events) - 2):                                  # and at every moment in between
                self.assertEqual(ViewFolder().feed(events[:cut]).view(), build_view(events[:cut]), (seed, cut))

    def test_a_waiting_adjustment_does_not_leak_into_the_running_fold(self):
        f = ViewFolder()
        f.feed([self.ev(1, "g", "goal.intent", {"text": "x"}), self.ev(2, "g", "plan.accepted", {"plan": {"steps": [{"id": "s", "tool": "shell.run", "args": {"cmd": "x"}}]}}),
                self.ev(3, "g", "checkpoint", {"id": "c"}), self.ev(4, "g", "guard.decision", {"step": "s", "verdict": "ESCALATE", "class": 4})])
        self.assertEqual(f.view().status, "WAITING FOR YOU")
        f.feed([self.ev(5, "g", "guard.authorization", {"step": "s", "verdict": "ALLOW"})])
        self.assertEqual(f.view().status, "RUNNING")

    def test_events_of_other_goals_and_before_any_goal_are_ignored(self):
        f = ViewFolder().feed([self.ev(1, "old", "model.call", {"cost_usd": 5}), self.ev(2, "g", "goal.intent", {"text": "a"}), self.ev(3, "other", "goal.report", {"status": "FAILED"})])
        v = f.view(); self.assertEqual((v.goal_id, v.status, v.cost), ("g", "PLANNING", 0.0))

    def test_a_poll_costs_what_is_new_not_what_is_old_and_never_double_counts(self):
        import tempfile, os, time as _t
        from praxis.desktop.controller import Controller
        from tests.test_desktop_controller import mk, GOOD, wait
        c, ws, st = mk([GOOD])
        log = EventLog(c.db_path)
        log.append("big", "user", "goal.intent", {"text": "long"})
        for i in range(3000):
            log.append("big", "router", "model.try", {"provider": "claude"}); log.append("big", "router", "model.call", {"provider": "claude", "cost_usd": 0.001})
        first = c.poll()                                                               # the first poll folds the log once (and sees every event as new)
        self.assertAlmostEqual(first.view.cost, 3.0, places=6)                         # ...without counting any of them twice
        c._last_id = c._folder_last - 400                                              # the read cursor is rewound (mark_read does this): old events come round again
        again = c.poll()
        self.assertAlmostEqual(again.view.cost, 3.0, places=6)                         # ...and are not counted a second time
        t0 = _t.perf_counter()
        for _ in range(30): u = c.poll()
        per = (_t.perf_counter() - t0) / 30 * 1000
        self.assertLess(per, 8.0, f"{per:.1f} ms per poll on a 6000-event goal")
        self.assertAlmostEqual(u.view.cost, 3.0, places=6)
        log.append("big", "router", "model.call", {"provider": "claude", "cost_usd": 1.0})
        self.assertAlmostEqual(c.poll().view.cost, 4.0, places=6); self.assertAlmostEqual(c.poll().view.cost, 4.0, places=6)     # counted once


if __name__ == "__main__":
    unittest.main()
