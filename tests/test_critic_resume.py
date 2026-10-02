import json, os, subprocess, sys, tempfile, textwrap, unittest
from praxis.events import EventLog
from praxis.executive import Executive, VERIFIED, FAILED
from praxis.router import Router, ScriptedProvider
from tests.test_executive import plan, W, put, get


def two(planner, critic, **kw):
    ws, log = tempfile.mkdtemp(), EventLog()
    a, b = ScriptedProvider(planner, name="alpha"), ScriptedProvider(critic, name="beta")
    ex = Executive(ws, log, Router([a, b], roles={"planner": ["alpha"], "critic": ["beta", "alpha"]}), **kw)
    return ex, ws, log, a, b


GOOD = plan([W("s1", "a.txt", "x")], [{"type": "file_exists", "path": "a.txt"}])


class Critic(unittest.TestCase):
    def test_critic_is_a_different_provider_and_approval_proceeds(self):
        ex, ws, log, a, b = two([GOOD], [json.dumps({"approve": True, "objections": []})])
        r = ex.run("make a.txt")
        self.assertEqual(r.status, VERIFIED)
        self.assertEqual(len(a.calls), 1)       # planner only
        self.assertEqual(b.calls[0][0], "critic")  # critic served by the *other* model
        self.assertTrue(log.all(type_="critic.verdict"))

    def test_objection_triggers_one_revision_that_is_used(self):
        weak = plan([W("s1", "a.txt", "x")], [{"type": "none"}])
        verdict = json.dumps({"approve": False, "objections": [{"issue": "no real success check",
                              "test": "file_exists a.txt"}]})
        ex, ws, log, a, b = two([weak, GOOD], [verdict])
        r = ex.run("make a.txt")
        self.assertEqual(r.status, VERIFIED)           # revision added the real criterion
        self.assertIn("no real success check", json.dumps(a.calls[1][1]))

    def test_critic_skipped_honestly_with_single_provider(self):
        ws, log = tempfile.mkdtemp(), EventLog()
        ex = Executive(ws, log, Router([ScriptedProvider([GOOD])]))
        self.assertEqual(ex.run("x").status, VERIFIED)
        self.assertTrue(log.all(type_="critic.skipped"))

    def test_garbage_critic_output_never_blocks(self):
        ex, ws, log, a, b = two([GOOD], ["lol not json"])
        self.assertEqual(ex.run("x").status, VERIFIED)
        self.assertTrue(log.all(type_="critic.invalid"))

    def test_critic_cannot_loosen_guard(self):
        evil = plan([{"id": "s1", "tool": "shell.run", "args": {"cmd": "touch pwned.txt"},
                      "verify": {"type": "none"}, "deps": []}], [{"type": "file_exists", "path": "pwned.txt"}])
        ex, ws, log, a, b = two([evil], [json.dumps({"approve": True, "objections": []})])
        self.assertEqual(ex.run("x").status, FAILED)
        self.assertFalse(os.path.exists(os.path.join(ws, "pwned.txt")))


class Cost(unittest.TestCase):
    def test_cost_budget_stops_further_model_calls(self):
        class Pricey(ScriptedProvider):
            def complete(self, role, messages):
                self.last_meta = {"cost_usd": 5.0}
                return super().complete(role, messages)
        ws, log = tempfile.mkdtemp(), EventLog()
        p = Pricey(["garbage", GOOD])  # first plan invalid -> would need a 2nd call
        r = Executive(ws, log, Router([p]), max_cost_usd=1.0).run("x")
        self.assertEqual(r.status, FAILED)
        self.assertIn("cost", r.reason.lower())


CRASH_CHILD = textwrap.dedent('''
    import os, sys, json
    sys.path.insert(0, {repo!r})
    from praxis.events import EventLog
    from praxis.executive import Executive
    from praxis.router import Router, ScriptedProvider
    plan = json.dumps({{"steps": [
      {{"id": "s1", "tool": "fs.write", "args": {{"path": "one.txt", "content": "1"}}, "verify": {{"type": "file_exists", "path": "one.txt"}}, "deps": []}},
      {{"id": "s2", "tool": "fs.write", "args": {{"path": "two.txt", "content": "2"}}, "verify": {{"type": "file_exists", "path": "two.txt"}}, "deps": ["s1"]}}],
      "success": [{{"type": "file_exists", "path": "two.txt"}}]}})
    ex = Executive({ws!r}, EventLog({db!r}), Router([ScriptedProvider([plan])]))
    real = ex.tools.run
    def dying(tool, args):
        out = real(tool, args)
        if args.get("path") == "one.txt":
            os._exit(137)            # SIGKILL-equivalent: no cleanup, no finally, no atexit
        return out
    ex.tools.run = dying
    ex.run("write two files")
''')


class Resume(unittest.TestCase):
    def crash(self):
        ws = tempfile.mkdtemp(); db = os.path.join(ws, "events.db")
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        p = subprocess.run([sys.executable, "-c", CRASH_CHILD.format(repo=repo, ws=ws, db=db)])
        self.assertEqual(p.returncode, 137)
        return ws, db

    def test_resume_after_hard_kill_finishes_without_model_call(self):
        ws, db = self.crash()
        self.assertTrue(os.path.exists(os.path.join(ws, "one.txt")))   # half-done state really exists
        self.assertFalse(os.path.exists(os.path.join(ws, "two.txt")))
        log = EventLog(db)
        prov = ScriptedProvider([])  # an empty queue proves resume never calls a model
        ex = Executive(ws, log, Router([prov]))
        self.assertEqual(len(ex.unfinished_goals()), 1)
        r = ex.resume()
        self.assertEqual(r.status, VERIFIED)
        self.assertEqual(get(os.path.join(ws, "one.txt")), "1")
        self.assertEqual(get(os.path.join(ws, "two.txt")), "2")
        self.assertEqual(prov.calls, [])
        self.assertEqual(ex.unfinished_goals(), [])
        self.assertEqual(log.verify_chain(), (True, None))
        self.assertTrue(log.all(type_="goal.resumed"))

    def test_resume_twice_is_a_noop(self):
        ws, db = self.crash()
        ex = Executive(ws, EventLog(db), Router([ScriptedProvider([])]))
        ex.resume()
        self.assertIsNone(ex.resume())

    def test_crash_before_checkpoint_fails_cleanly_and_changes_nothing(self):
        ws, log = tempfile.mkdtemp(), EventLog()
        log.append("g1", "user", "goal.intent", {"text": "x"})  # planning started, process died
        ex = Executive(ws, log, Router([ScriptedProvider([])]))
        r = ex.resume("g1")
        self.assertEqual(r.status, FAILED)
        self.assertIn("before execution", r.reason)

    def test_unapproved_replan_is_never_executed_on_resume(self):
        ws, log = tempfile.mkdtemp(), EventLog()
        g = "g2"
        i = log.append(g, "user", "goal.intent", {"text": "x"})
        p1 = plan([W("s1", "a.txt", "1")], [{"type": "file_exists", "path": "a.txt"}])
        evil = plan([{"id": "e", "tool": "shell.run", "args": {"cmd": "touch pwned"}, "verify": {"type": "none"}, "deps": []}], [])
        from praxis.executive import parse_plan
        a1 = log.append(g, "executive", "plan.accepted", {"plan": parse_plan(p1), "initial": True}, [i])
        c = log.append(g, "executive", "checkpoint", {"id": Executive(ws, log, Router([])).ws.checkpoint()}, [a1])
        log.append(g, "executive", "plan.accepted", {"plan": parse_plan(evil), "initial": False}, [c])  # no approval event
        r = Executive(ws, log, Router([ScriptedProvider([])])).resume(g)
        self.assertEqual(r.status, FAILED)
        self.assertFalse(os.path.exists(os.path.join(ws, "pwned")))


if __name__ == "__main__":
    unittest.main()
