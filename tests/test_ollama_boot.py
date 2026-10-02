import os
import unittest
from unittest import mock

from praxis import ollama_boot as ob


class OllamaBoot(unittest.TestCase):
    def test_locality(self):
        for h in ("http://127.0.0.1:11434", "http://localhost:11434", "localhost"):
            self.assertTrue(ob.is_local(h), h)
        self.assertFalse(ob.is_local("http://10.0.0.5:11434"))
        self.assertFalse(ob.is_local("https://ollama.example.com"))

    def test_already_up_does_nothing(self):
        popen = mock.Mock()
        self.assertEqual(ob.ensure(probe=lambda h: True, popen=popen), (True, ""))
        popen.assert_not_called()

    def test_remote_never_started(self):
        popen = mock.Mock()
        ok, note = ob.ensure("http://10.0.0.5:11434", probe=lambda h: False, popen=popen, which=lambda n: "/x/ollama")
        self.assertFalse(ok)
        popen.assert_not_called()

    def test_not_installed(self):
        ok, note = ob.ensure(probe=lambda h: False, which=lambda n: None, popen=mock.Mock())
        self.assertFalse(ok)
        self.assertIn("not installed", note)

    def test_starts_with_small_vram_tuning(self):
        state = {"up": False}
        popen = mock.Mock(side_effect=lambda *a, **k: state.update(up=True))
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PRAXIS_NO_AUTOSTART", None)
            ok, note = ob.ensure(vram_bytes=6 * 2 ** 30, probe=lambda h: state["up"], which=lambda n: "/x/ollama", popen=popen,
                                 sleep=lambda s: None, env={})
        self.assertTrue(ok)
        env = popen.call_args.kwargs["env"]
        self.assertEqual(env["OLLAMA_FLASH_ATTENTION"], "1")
        self.assertEqual(popen.call_args.args[0], ["/x/ollama", "serve"])

    def test_big_gpu_not_tuned_and_launch_failure_reported(self):
        self.assertEqual(ob.tuning(24 * 2 ** 30), {})
        self.assertEqual(ob.tuning(0), {})
        ok, note = ob.ensure(probe=lambda h: False, which=lambda n: "/x/o", popen=mock.Mock(side_effect=OSError("boom")))
        self.assertFalse(ok)
        self.assertIn("boom", note)

    def test_opt_out(self):
        popen = mock.Mock()
        with mock.patch.dict(os.environ, {"PRAXIS_NO_AUTOSTART": "1"}):
            ok, _ = ob.ensure(probe=lambda h: False, which=lambda n: "/x/o", popen=popen)
        self.assertFalse(ok)
        popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
