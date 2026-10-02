import os, tempfile, unittest
from praxis.desktop.controller import Controller, workspace_problem
from praxis.events import EventLog
from praxis.executive import Executive, FAILED, VERIFIED
from praxis.router import Router, ScriptedProvider
from praxis.tools import Workspace
from tests.test_executive import plan, W


class SizeGuard(unittest.TestCase):
    def test_size_bytes_counts_and_skips_heavy_dirs(self):
        ws = Workspace(tempfile.mkdtemp())
        for rel, n in (("a.bin", 1000), ("sub/b.bin", 2000), ("node_modules/x/y.bin", 10**6), (".git/pack", 10**6)):
            p = os.path.join(ws.root, rel); os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "wb").write(b"x" * n)
        self.assertEqual(ws.size_bytes(), 3000)            # node_modules / .git are never snapshotted, so never counted

    def test_size_scan_stops_early_once_over_the_limit(self):
        ws = Workspace(tempfile.mkdtemp())
        for i in range(50):
            open(os.path.join(ws.root, f"f{i}"), "wb").write(b"x" * 1000)
        self.assertGreater(ws.size_bytes(stop_after=5000), 5000)   # returns as soon as it is known to be too big

    def test_executive_refuses_an_oversized_workspace_before_touching_anything(self):
        ws, log = tempfile.mkdtemp(), EventLog()
        open(os.path.join(ws, "big.bin"), "wb").write(b"x" * 3_000_000)
        prov = ScriptedProvider([plan([W("s1", "a.txt", "1")], [{"type": "file_exists", "path": "a.txt"}])])
        r = Executive(ws, log, Router([prov]), max_checkpoint_mb=1).run("make a.txt")
        self.assertEqual(r.status, FAILED); self.assertIn("too large", r.reason); self.assertIn("1 MB", r.reason)
        self.assertFalse(os.path.exists(os.path.join(ws, "a.txt")))
        self.assertEqual(os.listdir(os.path.join(ws, ".praxis", "checkpoints")) if os.path.isdir(os.path.join(ws, ".praxis", "checkpoints")) else [], [])
        self.assertEqual(prov.calls, [])                    # not even a model call was spent

    def test_default_limit_allows_normal_projects(self):
        ws, log = tempfile.mkdtemp(), EventLog()
        prov = ScriptedProvider([plan([W("s1", "a.txt", "1")], [{"type": "file_exists", "path": "a.txt"}])])
        self.assertEqual(Executive(ws, log, Router([prov])).run("x").status, VERIFIED)


class WrongFolder(unittest.TestCase):
    def test_home_root_and_system_folders_are_refused(self):
        home = os.path.expanduser("~")
        for p in (home, os.path.dirname(home), "/", os.path.abspath(os.sep)):
            self.assertTrue(workspace_problem(p), p)
        for p in (r"C:\Windows", r"C:\Program Files", "C:\\", "/usr", "/etc", "/bin"):
            self.assertTrue(workspace_problem(p), p)

    def test_normal_project_folders_are_fine(self):
        self.assertIsNone(workspace_problem(tempfile.mkdtemp()))
        self.assertIsNone(workspace_problem(os.path.join(os.path.expanduser("~"), "projects", "demo")))

    def test_controller_refuses_to_open_them(self):
        c = Controller(tempfile.mkdtemp(), stack_factory=lambda w: None, home=tempfile.mkdtemp())
        self.assertFalse(c.open_workspace(os.path.expanduser("~")))
        self.assertIn("home folder", c.refusal.lower())


if __name__ == "__main__":
    unittest.main()
