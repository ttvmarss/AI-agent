import json, os, stat, tempfile, unittest
from praxis.config import Stack, load_config
from praxis.hardware import GB, GPU, Profile
from praxis.providers import ClaudeCLI, CodexCLI, DroidCLI, OllamaProvider
from praxis.registry import Registry, pick_for_hardware
from praxis.router import ModelUnavailable, ProviderError, Router, ScriptedProvider
from tests.test_providers import FakeBin, MSGS, serve, TAGS


def rig(vram=8, ram=32):
    return Profile("windows", "Ryzen 7 7700", 16, ram * GB, 70, [GPU("RTX 3050", vram * GB, 224)] if vram else [])


def tags(*rows):
    return {"models": [{"name": n, "size": int(s * GB), "details": {"parameter_size": f"{p}B"}} for n, s, p in rows]}


class ModelUnavailableDetection(FakeBin):
    def test_claude_unrecognized_model(self):
        self.install("claude", "print('[claude-code:unrecognized_model] {\"model\":\"x\"}')\nsys.exit(1)")
        with self.assertRaises(ModelUnavailable):
            ClaudeCLI(model="x").complete("planner", MSGS)

    def test_claude_unrecognized_model_even_with_exit_zero(self):
        self.install("claude", "print('[claude-code:unrecognized_model] {}')")
        with self.assertRaises(ModelUnavailable):
            ClaudeCLI(model="x").complete("planner", MSGS)

    def test_codex_and_droid_model_errors(self):
        for name, cls in (("codex", CodexCLI), ("droid", DroidCLI)):
            self.install(name, "sys.stderr.write('Error: model gpt-9 not found or you do not have access'); sys.exit(1)")
            with self.assertRaises(ModelUnavailable):
                cls(model="gpt-9").complete("planner", MSGS)

    def test_model_flag_and_naming(self):
        self.install("claude", "print(json.dumps({'is_error':False,'result':'x'}))")
        c = ClaudeCLI(model="claude-opus-5-5", tier="balanced")
        c.complete("planner", MSGS)
        a = self.recorded()["argv"]
        self.assertEqual(a[a.index("--model") + 1], "claude-opus-5-5")
        self.assertEqual(c.card.name, "claude/claude-opus-5-5"); self.assertEqual(c.tier, "balanced")
        self.assertEqual(ClaudeCLI().card.name, "claude")


class RouterRobustness(unittest.TestCase):
    def test_repeated_unexplained_failures_trigger_a_short_cooldown(self):
        t = [0.0]
        bad = ScriptedProvider([ProviderError("weird"), ProviderError("weird"), "BAD-BACK"], name="bad")
        ok = ScriptedProvider(["ok"] * 6, name="ok")
        r = Router([bad, ok], {"planner": ["bad", "ok"]}, clock=lambda: t[0])
        self.assertEqual(r.call("planner", []), "ok"); self.assertEqual(r.call("planner", []), "ok")  # 2 failures
        self.assertEqual(r.call("planner", []), "ok")
        self.assertEqual(len(bad.calls), 2)       # benched after two strikes: no third wasted attempt
        t[0] += 3600
        self.assertEqual(r.call("planner", []), "BAD-BACK")

    def test_success_resets_the_failure_streak(self):
        bad = ScriptedProvider([ProviderError("x"), "fine", ProviderError("x"), "fine"], name="bad")
        r = Router([bad], {"planner": ["bad"]})
        for _ in range(2):
            with self.assertRaises(ProviderError): r.call("planner", [])
            self.assertEqual(r.call("planner", []), "fine")


class HardwarePicker(unittest.TestCase):
    def test_prefers_moe_that_is_fast_enough_over_dense_that_is_slow(self):
        models = tags(("qwen3.6:35b-a3b", 24, 35), ("qwen3.6:27b", 17, 27), ("granite4.2:3b", 2.2, 3))
        self.assertEqual(pick_for_hardware(models["models"], rig(8)), "qwen3.6:35b-a3b")

    def test_big_gpu_picks_dense_27b(self):
        models = tags(("qwen3.6:35b-a3b", 24, 35), ("qwen3.6:27b", 17, 27))
        p = Profile("linux", "cpu", 32, 128 * GB, 90, [GPU("RTX 4090", 24 * GB, 1008)])
        self.assertEqual(pick_for_hardware(models["models"], p), "qwen3.6:27b")

    def test_skips_what_does_not_fit_and_embedding_models(self):
        models = tags(("mistral-medium:128b", 75, 128), ("nomic-embed-text", 0.3, 0.137), ("granite4.2:3b", 2.2, 3))
        self.assertEqual(pick_for_hardware(models["models"], rig(8)), "granite4.2:3b")

    def test_measured_beats_prior_but_only_if_it_meets_the_speed_floor(self):
        models = tags(("qwen3.6:35b-a3b", 24, 35), ("granite4.2:8b", 5.3, 8))
        reg = Registry()
        reg.record("ollama/granite4.2:8b", "planning", 0.95, 12, 3, tokens_per_s=40)
        reg.record("ollama/qwen3.6:35b-a3b", "planning", 0.60, 12, 9, tokens_per_s=14)
        self.assertEqual(pick_for_hardware(models["models"], rig(8), reg), "granite4.2:8b")   # measured quality wins
        reg.record("ollama/granite4.2:8b", "planning", 0.99, 12, 90, tokens_per_s=1.5)        # but not if unusably slow
        self.assertEqual(pick_for_hardware(models["models"], rig(8), reg), "qwen3.6:35b-a3b")

    def test_prefer_list_wins_if_it_fits(self):
        models = tags(("qwen3.6:35b-a3b", 24, 35), ("laguna-xs-2.1", 20, 33))
        self.assertEqual(pick_for_hardware(models["models"], rig(8), prefer=["laguna-xs-2.1"]), "laguna-xs-2.1")

    def test_nothing_fits_returns_none(self):
        self.assertIsNone(pick_for_hardware(tags(("big:70b", 45, 70))["models"], rig(0, 16)))


class OllamaWithHardware(unittest.TestCase):
    def server(self, models, reply='{"ok":1}'):
        def route(h, m, path, body):
            h.server.reqs.append((m, path, body))
            if path == "/api/version": h._send({"version": "0.9"})
            elif path == "/api/tags": h._send(models)
            elif path == "/api/chat":
                h._send({"message": {"content": reply}, "total_duration": 2_000_000_000,
                         "eval_count": 120, "eval_duration": 4_000_000_000})
            elif path == "/api/pull":
                lines = [{"status": "pulling manifest"}, {"status": "pulling abc", "total": 100, "completed": 40},
                         {"status": "pulling abc", "total": 100, "completed": 100}, {"status": "success"}]
                data = ("\n".join(json.dumps(l) for l in lines) + "\n").encode()
                h.send_response(200); h.send_header("content-length", str(len(data))); h.end_headers(); h.wfile.write(data)
        srv, url = serve(route); self.addCleanup(srv.shutdown); return srv, url

    def test_selects_with_profile_and_measures_tokens_per_second(self):
        srv, url = self.server(tags(("qwen3.6:35b-a3b", 24, 35), ("qwen3.6:27b", 17, 27)))
        p = OllamaProvider(url, profile=rig(8))
        p.complete("planner", MSGS)
        self.assertEqual(p.model, "qwen3.6:35b-a3b")
        self.assertAlmostEqual(p.last_meta["tokens_per_s"], 30.0, places=1)   # 120 tokens / 4 s, measured not guessed

    def test_pull_streams_progress_and_reports_success(self):
        srv, url = self.server(tags())
        seen = []
        ok = OllamaProvider(url).pull("granite4.2:3b", seen.append)
        self.assertTrue(ok)
        self.assertEqual(seen[-1]["status"], "success")
        self.assertTrue(any(s.get("completed") == 40 for s in seen))
        body = [b for m, path, b in srv.reqs if path == "/api/pull"][0]
        self.assertEqual(body["model"], "granite4.2:3b"); self.assertTrue(body["stream"])

    def test_pull_failure_is_an_error_not_a_hang(self):
        with self.assertRaises(ProviderError):
            OllamaProvider("http://127.0.0.1:9", timeout=2).pull("x:1b")


class StackVariants(unittest.TestCase):
    def setUp(self):
        self.bin = tempfile.mkdtemp()
        for name in ("claude", "codex", "droid"):
            p = os.path.join(self.bin, name)
            open(p, "w").write("#!/bin/sh\necho x\n"); os.chmod(p, 0o755)
        self._path = os.environ["PATH"]; os.environ["PATH"] = self.bin + os.pathsep + self._path

    def tearDown(self):
        os.environ["PATH"] = self._path

    def test_claude_gets_one_instance_per_tier_with_verified_ids(self):
        cfg = load_config()
        cfg["providers"]["ollama"]["enabled"] = False
        st = Stack(cfg, Registry(), detect_sandbox=False)
        names = [p.card.name for p in st.providers if p.card.name.startswith("claude")]
        self.assertEqual(sorted(names), ["claude/claude-fable-5-1", "claude/claude-opus-5-5", "claude/claude-sonnet-5-5"])
        tiers = {p.card.name: p.tier for p in st.providers}
        self.assertEqual(tiers["claude/claude-fable-5-1"], "best"); self.assertEqual(tiers["claude/claude-opus-5-5"], "balanced")

    def test_every_installed_family_has_a_default_instance_and_delegates_once(self):
        cfg = load_config(); cfg["providers"]["ollama"]["enabled"] = False
        st = Stack(cfg, Registry(), detect_sandbox=False)
        fams = {p.card.name.split("/")[0] for p in st.providers}
        self.assertEqual(fams, {"claude", "codex", "droid"})
        self.assertEqual(sorted(st.agents), ["claude", "codex", "droid"])   # one delegate per family, not per model
        self.assertEqual(st.agents["claude"].tier, "balanced")

    def test_hardware_override_reaches_ollama(self):
        cfg = load_config(); cfg["hardware"].update(vram_gb=8, ram_gb=32, gpu_name="RTX 3050", ram_bw_gbps=70)
        st = Stack(cfg, Registry(), detect_sandbox=False)
        self.assertEqual(st.profile.vram_total, 8 * GB); self.assertEqual(st.profile.ram_bytes, 32 * GB)

    def test_small_vram_gets_smaller_context_window(self):
        cfg = load_config(); cfg["hardware"].update(vram_gb=8, ram_gb=32)
        self.assertEqual(Stack(cfg, Registry(), detect_sandbox=False).ollama_num_ctx, 8192)
        cfg["hardware"].update(vram_gb=24)
        self.assertEqual(Stack(cfg, Registry(), detect_sandbox=False).ollama_num_ctx, 16384)


if __name__ == "__main__":
    unittest.main()
