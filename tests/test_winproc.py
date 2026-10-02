"""No terminal windows. A windowless PRAXIS that starts a console program makes Windows open a visible terminal per call (found on the real PC:
'On it', then a pile of terminals, then nothing). Every child process must go through praxis.winproc."""
import ast
import os
import subprocess
import unittest
from unittest import mock

from praxis import proc, winproc

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "praxis")
LAUNCHERS = {"run", "Popen", "call", "check_call", "check_output", "getoutput", "getstatusoutput"}


def python_files():
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in files:
            if f.endswith(".py"):
                yield os.path.join(base, f)


class NoTerminals(unittest.TestCase):
    def test_no_module_starts_a_process_except_through_winproc(self):
        bad = []
        for path in python_files():
            if path.endswith("winproc.py"):
                continue
            tree = ast.parse(open(path, encoding="utf-8").read())
            for n in ast.walk(tree):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name):
                    if n.func.value.id == "subprocess" and n.func.attr in LAUNCHERS:
                        bad.append(f"{os.path.relpath(path, ROOT)}:{n.lineno} subprocess.{n.func.attr}")
                    if n.func.value.id == "os" and n.func.attr in ("system", "popen", "spawnl", "spawnv", "startfile"):
                        if not path.endswith("opener.py"):
                            bad.append(f"{os.path.relpath(path, ROOT)}:{n.lineno} os.{n.func.attr}")
        self.assertEqual(bad, [], "start processes with praxis.winproc.run/popen (hidden window on Windows)")

    def test_on_windows_every_child_is_started_without_a_console(self):
        with mock.patch.object(winproc, "IS_WINDOWS", True):
            kw = winproc.hidden()
            self.assertTrue(kw["creationflags"] & winproc.CREATE_NO_WINDOW)
            self.assertTrue(winproc.hidden(group=True)["creationflags"] & winproc.CREATE_NEW_PROCESS_GROUP)
            d = winproc.hidden(detached=True)["creationflags"]
            self.assertTrue(d & winproc.DETACHED_PROCESS and d & winproc.CREATE_NO_WINDOW)

    def test_elsewhere_the_flags_are_harmless(self):
        with mock.patch.object(winproc, "IS_WINDOWS", False):
            self.assertEqual(winproc.hidden(), {})
            self.assertEqual(winproc.hidden(group=True), {"start_new_session": True})

    def test_the_model_cli_runner_hides_its_window_and_still_groups_for_killing(self):
        seen = {}
        class P:
            returncode = 0
            def communicate(self, input=None, timeout=None): return ("ok", "")
        def fake(argv, **kw): seen.update(kw); return P()
        with mock.patch.object(winproc, "IS_WINDOWS", True), mock.patch.object(winproc.subprocess, "Popen", fake):
            self.assertEqual(proc.run_cli(["python3", "-c", "1"], "x")[0], "ok")
        self.assertTrue(seen["creationflags"] & winproc.CREATE_NO_WINDOW)
        self.assertTrue(seen["creationflags"] & winproc.CREATE_NEW_PROCESS_GROUP)

    def test_run_and_popen_pass_the_flags_but_let_a_caller_override(self):
        calls = []
        with mock.patch.object(winproc, "IS_WINDOWS", True), mock.patch.object(winproc.subprocess, "run", lambda a, **k: calls.append(k)):
            winproc.run(["x"]); winproc.run(["x"], creationflags=7)
        self.assertTrue(calls[0]["creationflags"] & winproc.CREATE_NO_WINDOW)
        self.assertEqual(calls[1]["creationflags"], 7)


if __name__ == "__main__":
    unittest.main()
