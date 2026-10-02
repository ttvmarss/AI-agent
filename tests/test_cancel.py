import json, os, stat, tempfile, threading, time, unittest
from praxis import proc
from praxis.events import EventLog
from praxis.executive import Executive, VERIFIED
from praxis.router import ProviderError, Router, ScriptedProvider
from tests.test_executive import plan, W, put

CANCELLED = "CANCELLED"


class SlowProvider(ScriptedProvider):
    def __init__(self, answers, hook=None):
        super().__init__(answers, name="slow"); self.hook = hook

    def complete(self, role, messages):
        if self.hook: self.hook()
        return super().complete(role, messages)


class CancelTests(unittest.TestCase):
    def test_cancel_before_start_makes_no_model_call(self):
        ws, log = tempfile.mkdtemp(), EventLog()
        prov = ScriptedProvider([plan([W("s1", "a.txt", "x")], [{"type": "file_exists", "path": "a.txt"}])])
        ex = Executive(ws, log, Router([prov]))
        ex.cancel()
        r = ex.run("x")
        self.assertEqual(r.status, CANCELLED)
        self.assertEqual(prov.calls, [])
        self.assertEqual(log.verify_chain(), (True, None))

    def test_cancel_mid_execution_rolls_everything_back(self):
        ws, log = tempfile.mkdtemp(), EventLog()
        steps = [W("s1", "a.txt", "1"), W("s2", "b.txt", "2", deps=["s1"]), W("s3", "c.txt", "3", deps=["s2"])]
        ex = Executive(ws, log, Router([ScriptedProvider([plan(steps, [{"type": "file_exists", "path": "c.txt"}])])]))
        real = ex.tools.run
        def hooked(tool, args):
            out = real(tool, args)
            if args.get("path") == "a.txt":
                ex.cancel()                     # the human hits Stop after step 1
            return out
        ex.tools.run = hooked
        r = ex.run("x")
        self.assertEqual(r.status, CANCELLED)
        self.assertTrue(r.rolled_back)
        for n in "abc":
            self.assertFalse(os.path.exists(os.path.join(ws, f"{n}.txt")))
        self.assertEqual(len([e for e in log.all(type_="tool.result")]), 1)   # steps 2 and 3 never ran
        self.assertTrue(log.all(type_="goal.cancelled"))
        self.assertEqual(log.verify_chain(), (True, None))

    def test_executive_is_reusable_after_a_cancel(self):
        ws, log = tempfile.mkdtemp(), EventLog()
        good = plan([W("s1", "a.txt", "1")], [{"type": "file_exists", "path": "a.txt"}])
        ex = Executive(ws, log, Router([ScriptedProvider([good])]))
        ex.cancel(); self.assertEqual(ex.run("x").status, CANCELLED)
        ex.reset_cancel()
        ex.router.providers[0].queue.append(good)
        self.assertEqual(ex.run("y").status, VERIFIED)

    def test_cancelled_goals_are_finished_not_resumable(self):
        ws, log = tempfile.mkdtemp(), EventLog()
        ex = Executive(ws, log, Router([ScriptedProvider([])])); ex.cancel(); ex.run("x")
        self.assertEqual(ex.unfinished_goals(), [])


class KillSlowCLI(unittest.TestCase):
    def test_cancel_terminates_a_running_subprocess_promptly(self):
        d = tempfile.mkdtemp(); p = os.path.join(d, "slowcli")
        open(p, "w").write("#!/bin/sh\nsleep 30\n"); os.chmod(p, 0o755)
        ev = threading.Event(); proc.set_cancel(ev)
        threading.Timer(0.6, ev.set).start()
        t0 = time.time()
        try:
            with self.assertRaises(ProviderError) as cm:
                proc.run_cli([p], "", (), timeout=60)
        finally:
            proc.set_cancel(None)
        self.assertLess(time.time() - t0, 5)
        self.assertIn("cancel", str(cm.exception).lower())


if __name__ == "__main__":
    unittest.main()
