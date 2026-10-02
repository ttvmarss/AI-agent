import os, tempfile, time, unittest
from praxis.events import EventLog
from praxis.executive import Executive, VERIFIED
from praxis.router import Router, ScriptedProvider
from praxis.tools import Workspace
from tests.test_executive import plan, W, put


class Skips(unittest.TestCase):
    def test_heavy_dirs_are_not_copied_not_deleted_and_not_in_manifest(self):
        ws = Workspace(tempfile.mkdtemp())
        for d in ("node_modules", ".venv", "__pycache__"):
            os.makedirs(os.path.join(ws.root, d)); put(os.path.join(ws.root, d, "big.bin"), "x" * 10)
        put(os.path.join(ws.root, "a.txt"), "1")
        cid = ws.checkpoint()
        for d in ("node_modules", ".venv", "__pycache__"):
            self.assertFalse(os.path.exists(os.path.join(ws.ckpt_dir, cid, d)))
        put(os.path.join(ws.root, "a.txt"), "2")
        ws.rollback(cid)
        self.assertEqual(open(os.path.join(ws.root, "a.txt")).read(), "1")
        self.assertTrue(os.path.exists(os.path.join(ws.root, "node_modules", "big.bin")))  # untouched by rollback
        self.assertNotIn(os.path.join("node_modules", "big.bin"), ws.manifest())


class Pruning(unittest.TestCase):
    def run_goal(self, ex, n):
        return ex.run(f"create file f{n}.txt")

    def test_keeps_newest_n_finished_and_never_prunes_unfinished(self):
        ws, log = tempfile.mkdtemp(), EventLog()
        resps = [plan([W("s1", f"f{i}.txt", "x")], [{"type": "file_exists", "path": f"f{i}.txt"}]) for i in range(6)]
        ex = Executive(ws, log, Router([ScriptedProvider(resps)]), keep_checkpoints=3)
        # an unfinished goal (died mid-flight) owns an old checkpoint that resume still needs
        g = "dead"; i = log.append(g, "user", "goal.intent", {"text": "x"})
        old = ex.ws.checkpoint(); log.append(g, "executive", "checkpoint", {"id": old}, [i])
        time.sleep(0.01)
        for n in range(6):
            self.assertEqual(self.run_goal(ex, n).status, VERIFIED)
        dirs = os.listdir(ex.ws.ckpt_dir)
        self.assertIn(old, dirs)                 # unfinished goal's checkpoint survives
        self.assertEqual(len(dirs), 3 + 1)       # newest 3 finished + the protected one

    def test_directories_unknown_to_the_log_are_never_deleted(self):
        ws, log = tempfile.mkdtemp(), EventLog()
        ex = Executive(ws, log, Router([ScriptedProvider(
            [plan([W("s1", f"f{i}.txt", "x")], [{"type": "file_exists", "path": f"f{i}.txt"}]) for i in range(3)])]),
            keep_checkpoints=1)
        stranger = ex.ws.checkpoint()   # created outside this log
        for n in range(3):
            self.run_goal(ex, n)
        self.assertIn(stranger, os.listdir(ex.ws.ckpt_dir))

    def test_prune_ignores_path_traversal_ids(self):
        w = Workspace(tempfile.mkdtemp()); victim = os.path.join(w.root, "precious"); os.makedirs(victim)
        w.prune(["../../precious", "..", ""])
        self.assertTrue(os.path.isdir(victim))

    def test_keep_zero_disables_pruning(self):
        ws, log = tempfile.mkdtemp(), EventLog()
        resps = [plan([W("s1", f"f{i}.txt", "x")], [{"type": "file_exists", "path": f"f{i}.txt"}]) for i in range(3)]
        ex = Executive(ws, log, Router([ScriptedProvider(resps)]), keep_checkpoints=0)
        for n in range(3):
            self.run_goal(ex, n)
        self.assertEqual(len(os.listdir(ex.ws.ckpt_dir)), 3)


if __name__ == "__main__":
    unittest.main()
