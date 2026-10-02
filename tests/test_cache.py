import json, os, tempfile, unittest
from unittest import mock

from praxis import cache, hardware


class Cache(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        p = mock.patch.dict(os.environ, {"PRAXIS_HOME": self.home}); p.start(); self.addCleanup(p.stop)
        os.environ.pop("PRAXIS_NO_CACHE", None)

    def test_a_value_is_computed_once_then_served_from_disk(self):
        calls = []
        f = lambda: calls.append(1) or "answer"
        self.assertEqual(cache.get("k", f), "answer"); self.assertEqual(cache.get("k", f), "answer"); self.assertEqual(len(calls), 1)
        with open(os.path.join(self.home, "cache.json")) as fh:
            self.assertEqual(json.load(fh)["k"]["v"], "answer")

    def test_it_expires_and_a_changed_stamp_recomputes(self):
        calls = []
        f = lambda: calls.append(1) or len(calls)
        t = [1000.0]
        self.assertEqual(cache.get("k", f, ttl_s=100, now=lambda: t[0]), 1)
        t[0] += 50; self.assertEqual(cache.get("k", f, ttl_s=100, now=lambda: t[0]), 1)
        t[0] += 60; self.assertEqual(cache.get("k", f, ttl_s=100, now=lambda: t[0]), 2)                 # expired
        self.assertEqual(cache.get("k", f, ttl_s=100, stamp="new driver", now=lambda: t[0]), 3)          # stamp changed
        self.assertEqual(cache.get("k", f, ttl_s=100, stamp="new driver", now=lambda: t[0]), 3)

    def test_none_is_never_cached_and_failures_are_survivable(self):
        calls = []
        self.assertIsNone(cache.get("n", lambda: calls.append(1))); self.assertIsNone(cache.get("n", lambda: calls.append(1))); self.assertEqual(len(calls), 2)
        with open(os.path.join(self.home, "cache.json"), "w") as f: f.write("{ not json")
        self.assertEqual(cache.get("k", lambda: 5), 5)                                                   # a corrupt file is replaced, not fatal
        with open(os.path.join(self.home, "cache.json"), "w") as f: f.write("[1,2]")
        self.assertEqual(cache.get("k2", lambda: 6), 6)
        with mock.patch.dict(os.environ, {"PRAXIS_HOME": os.path.join(self.home, "file")}):
            open(os.path.join(self.home, "file"), "w").close()                                          # home is a FILE: cannot be written
            self.assertEqual(cache.get("k3", lambda: 7), 7)

    def test_the_cache_can_be_switched_off(self):
        calls = []
        with mock.patch.dict(os.environ, {"PRAXIS_NO_CACHE": "1"}):
            cache.get("k", lambda: calls.append(1) or 1); cache.get("k", lambda: calls.append(1) or 1)
        self.assertEqual(len(calls), 2)

    def test_launching_on_windows_no_longer_starts_powershell_and_nvidia_smi_every_time(self):
        class R:  # a finished process
            def __init__(self, out): self.stdout, self.stderr, self.returncode = out, "", 0
        real_exists = os.path.exists
        calls = []
        def fake_run(argv, **k):
            calls.append(argv[0])
            return R("AMD Ryzen 7 7700X 8-Core Processor\n" if argv[0] == "powershell" else "NVIDIA GeForce RTX 3050, 6144\n")
        with mock.patch.object(hardware.sys, "platform", "win32"), mock.patch.object(hardware.subprocess, "run", fake_run), \
                mock.patch.object(hardware.os.path, "exists", lambda p: False if str(p).startswith("/proc") else real_exists(p)), \
                mock.patch.object(hardware.shutil, "which", lambda n, **k: "C:\\\\nvidia-smi.exe" if n == "nvidia-smi" else None), \
                mock.patch.object(hardware.os.path, "getmtime", lambda p: 1.0), \
                mock.patch.object(hardware, "_ram_bytes", lambda: 32 << 30):
            first = hardware.detect_hardware(); second = hardware.detect_hardware(); third = hardware.detect_hardware()
        self.assertEqual(sorted(calls), ["nvidia-smi", "powershell"])                                    # each asked ONCE across three launches
        self.assertEqual((first.cpu, second.cpu, third.cpu), ("AMD Ryzen 7 7700X 8-Core Processor",) * 3)
        self.assertEqual([g.name for g in third.gpus], ["NVIDIA GeForce RTX 3050"])


if __name__ == "__main__":
    unittest.main()
