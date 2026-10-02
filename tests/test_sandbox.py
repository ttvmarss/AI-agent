import os, tempfile, unittest
from praxis.sandbox import BwrapSandbox, DockerSandbox, Sandbox, UnshareSandbox, detect, selftest


class NoIsolation(UnshareSandbox):
    """A backend that claims to be a sandbox but isolates nothing. The self-test must catch it."""
    def wrap(self, argv, ws):
        return list(argv)


class NoStateProtection(UnshareSandbox):
    """Isolates the filesystem and network perfectly but leaves .praxis/ exposed. Must still be rejected."""
    def wrap(self, argv, ws):
        from praxis.sandbox import _UNSHARE_SCRIPT
        script = "\n".join(l for l in _UNSHARE_SCRIPT.splitlines() if "tmpfs tmpfs" not in l)
        return ["unshare", "--user", "--map-root-user", "--mount", "--net", "--pid", "--fork", "--kill-child",
                "sh", "-c", script, "sbx", ws] + list(argv)


class SandboxTests(unittest.TestCase):
    def test_selftest_rejects_backend_that_leaves_praxis_state_exposed(self):
        if not detect().strong:
            self.skipTest("no strong sandbox on this machine")
        ok, details = selftest(NoStateProtection())
        self.assertTrue(details["outside_write_blocked"] and details["network_blocked"])  # everything else is fine...
        self.assertFalse(details["praxis_state_protected"])                              # ...but this one is not
        self.assertFalse(ok)

    def test_selftest_catches_a_backend_that_does_not_isolate(self):
        ok, details = selftest(NoIsolation())
        self.assertFalse(ok)
        self.assertFalse(details["outside_write_blocked"])  # the attack succeeded -> verdict is NOT strong

    def test_real_backend_if_present_passes_its_own_attack(self):
        sb = detect()
        if not sb.strong:
            self.skipTest("no strong sandbox on this machine")
        ok, details = selftest(sb)
        self.assertTrue(ok, details)

    def test_detect_with_no_candidates_is_not_strong(self):
        sb = detect(prefer=())
        self.assertFalse(sb.strong)
        self.assertEqual(sb.kind, "none")
        self.assertEqual(sb.wrap(["ls"], "/x"), ["ls"])

    def test_detect_rejects_backend_that_fails_selftest(self):
        import praxis.sandbox as m
        orig = m.selftest
        m.selftest = lambda sb, python=None: (False, {"fake": False})
        try:
            self.assertFalse(detect(prefer=("unshare", "bwrap", "docker")).strong)
        finally:
            m.selftest = orig

    def test_bwrap_command_shape(self):
        a = BwrapSandbox().wrap(["python3", "x.py"], "/w")
        self.assertEqual(a[0], "bwrap")
        self.assertIn("--unshare-net", a); self.assertIn("--die-with-parent", a)
        i = a.index("--ro-bind"); self.assertEqual(a[i + 1:i + 3], ["/", "/"])      # whole FS read-only
        j = a.index("--bind"); self.assertEqual(a[j + 1:j + 3], ["/w", "/w"])        # only the workspace writable
        self.assertEqual(a[-2:], ["python3", "x.py"])

    def test_docker_command_shape(self):
        a = DockerSandbox("img:1").wrap(["pytest"], "/w")
        self.assertEqual(a[:2], ["docker", "run"])
        self.assertEqual(a[a.index("--network") + 1], "none")
        self.assertIn("--read-only", a); self.assertIn("--pids-limit", a)
        self.assertEqual(a[a.index("-v") + 1], "/w:/work")
        self.assertEqual(a[-2:], ["img:1", "pytest"][-2:] if False else a[-2:])
        self.assertEqual(a[a.index("img:1"):], ["img:1", "pytest"])

    def test_default_sandbox_is_never_strong(self):
        self.assertFalse(Sandbox().strong)


if __name__ == "__main__":
    unittest.main()


class StateIsolation(unittest.TestCase):
    def test_sandboxed_code_cannot_see_or_modify_real_praxis_state(self):
        sb = detect()
        if not sb.strong:
            self.skipTest("no strong sandbox on this machine")
        ws = os.path.realpath(tempfile.mkdtemp())
        os.makedirs(os.path.join(ws, ".praxis")); marker = os.path.join(ws, ".praxis", "events.db")
        with open(marker, "w") as f:
            f.write("REAL-LOG")
        import subprocess
        code = ("import os\n"
                "try: print('SEES', os.path.exists('.praxis/events.db'))\nexcept Exception as e: print('ERR', e)\n"
                "open('.praxis/events.db','w').write('TAMPERED')\n"
                "try: os.remove('.praxis/events.db')\nexcept OSError: pass\n"
                "open('.praxis/new.txt','w').write('x')\n")
        p = subprocess.run(sb.wrap(["python3", "-c", code], ws), capture_output=True, text=True, cwd=ws)
        self.assertIn("SEES False", p.stdout)                         # real state is not even visible
        self.assertEqual(open(marker).read(), "REAL-LOG")             # and untouched on the host
        self.assertFalse(os.path.exists(os.path.join(ws, ".praxis", "new.txt")))

    def test_selftest_includes_the_state_attack(self):
        sb = detect()
        if not sb.strong:
            self.skipTest("no strong sandbox on this machine")
        self.assertIn("praxis_state_protected", selftest(sb)[1])

    def test_all_backends_hide_praxis_dir(self):
        self.assertIn("/w/.praxis", BwrapSandbox().wrap(["x"], "/w"))
        self.assertIn("/work/.praxis", " ".join(DockerSandbox().wrap(["x"], "/w")))
        from praxis.sandbox import _UNSHARE_SCRIPT
        self.assertIn('tmpfs tmpfs "$WS/.praxis"', _UNSHARE_SCRIPT)
