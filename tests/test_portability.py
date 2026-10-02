import os, sys, tempfile, unittest
from unittest import mock
from praxis import proc
from praxis.sandbox import detect, DockerSandbox
from praxis.tools import Workspace


class PythonName(unittest.TestCase):
    def test_python_and_python3_resolve_to_the_running_interpreter_when_unsandboxed(self):
        ws = Workspace(tempfile.mkdtemp())          # Windows often has no `python3`; sys.executable always exists
        out = ws.shell_run("python3 -c pass") if False else None
        with open(os.path.join(ws.root, "t.py"), "w") as f:
            f.write("import sys; print(sys.executable)")
        for name in ("python3", "python"):
            r = ws.shell_run(f"{name} t.py")
            self.assertEqual(r["returncode"], 0)
            self.assertEqual(os.path.realpath(r["output"].strip()), os.path.realpath(sys.executable))


class WindowsResolution(unittest.TestCase):
    def test_which_resolves_cmd_shims_before_popen(self):
        d = tempfile.mkdtemp(); shim = os.path.join(d, "claude.cmd")
        open(shim, "w").write("@echo off\necho hi\n")
        with mock.patch("praxis.proc.shutil.which", return_value=shim) as w, \
             mock.patch("praxis.proc.subprocess.Popen", side_effect=FileNotFoundError) as popen:
            with self.assertRaises(Exception):
                proc.run_cli(["claude", "-p"], "x", (), 5)
        self.assertEqual(popen.call_args[0][0][0], shim)   # the resolved full path, not the bare name


class SandboxPlatform(unittest.TestCase):
    def test_docker_is_allowed_on_windows_but_namespace_backends_are_not(self):
        import praxis.sandbox as m
        calls = []
        with mock.patch.object(m.sys, "platform", "win32"), mock.patch.object(m.shutil, "which", lambda b: b), \
             mock.patch.object(m, "selftest", lambda sb, python=None: (calls.append(sb.kind) or True, {})):
            sb = m.detect()
        self.assertEqual(calls, ["docker"])            # bwrap/unshare never even attempted on Windows
        self.assertTrue(sb.strong); self.assertEqual(sb.kind, "docker")

    def test_docker_windows_path_mount(self):
        a = DockerSandbox().wrap(["python3", "x.py"], r"C:\Users\me\proj")
        self.assertIn(r"C:\Users\me\proj:/work", a)


if __name__ == "__main__":
    unittest.main()
