import io, unittest, contextlib
from unittest import mock
from praxis import __main__ as cli
from praxis.hardware import GB, GPU, Profile
from praxis.report import hardware_report, ollama_tips, recommendation_report, model_table


def rig(vram=8, bw=224):
    return Profile("windows", "AMD Ryzen 7 7700 8-Core Processor", 16, 32 * GB, 70, [GPU("NVIDIA GeForce RTX 3050", vram * GB, bw)])


class Reports(unittest.TestCase):
    def test_hardware_report_names_the_machine_and_the_bottleneck(self):
        t = hardware_report(rig())
        self.assertIn("RTX 3050", t); self.assertIn("32", t); self.assertIn("Ryzen 7 7700", t)
        self.assertIn("system RAM", t)   # explains that models bigger than VRAM run from RAM

    def test_recommendation_has_exact_pull_commands_and_honest_labels(self):
        t = recommendation_report(rig())
        self.assertIn("ollama pull ", t)
        self.assertIn("estimate", t.lower()); self.assertIn("bench", t.lower())   # never presents priors as facts

    def test_tips_only_for_small_vram_and_use_verified_variable_names(self):
        t = ollama_tips(rig(8))
        for v in ("OLLAMA_FLASH_ATTENTION", "OLLAMA_KV_CACHE_TYPE", "OLLAMA_MAX_LOADED_MODELS"):
            self.assertIn(v, t)
        self.assertEqual(ollama_tips(Profile("linux", "c", 8, 64 * GB, 80, [GPU("RTX 4090", 24 * GB, 1008)])), "")

    def test_model_table_rows_cover_catalog(self):
        from praxis.catalog import CATALOG
        t = model_table(rig())
        for m in CATALOG:
            self.assertIn(m.tag, t)

    def test_6gb_card_is_called_out_as_the_slower_variant(self):
        self.assertIn("6", hardware_report(rig(6, 168)))
        self.assertIn("168", hardware_report(rig(6, 168)))


class CliCommands(unittest.TestCase):
    def run_cli(self, argv, stdin_tty=False):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), mock.patch("praxis.__main__.detect_hardware", return_value=rig()):
            code = cli.main(argv)
        return code, buf.getvalue()

    def test_hardware_command(self):
        code, out = self.run_cli(["hardware", "--workspace", "/tmp/praxis-cli-test"])
        self.assertEqual(code, 0); self.assertIn("RTX 3050", out); self.assertIn("ollama pull", out)

    def test_models_recommend_works_without_ollama_running(self):
        code, out = self.run_cli(["models", "--recommend", "--workspace", "/tmp/praxis-cli-test"])
        self.assertEqual(code, 0); self.assertIn("daily", out.lower()); self.assertIn("ollama pull", out)

    def test_pull_requires_confirmation_non_interactively(self):
        with mock.patch("praxis.providers.OllamaProvider.pull") as pull:
            code, out = self.run_cli(["pull", "granite4.2:3b", "--workspace", "/tmp/praxis-cli-test"])
        pull.assert_not_called()                       # no --yes and no TTY: never starts a multi-GB download silently
        self.assertNotEqual(code, 0)

    def test_pull_with_yes_streams_progress(self):
        def fake_pull(self, tag, on_progress=None):
            on_progress({"status": "pulling x", "total": 100, "completed": 50}); on_progress({"status": "success"}); return True
        with mock.patch("praxis.providers.OllamaProvider.pull", fake_pull), \
             mock.patch("praxis.providers.OllamaProvider.version", return_value="0.9"):
            code, out = self.run_cli(["pull", "granite4.2:3b", "--yes", "--workspace", "/tmp/praxis-cli-test"])
        self.assertEqual(code, 0); self.assertIn("50%", out); self.assertIn("success", out.lower())


if __name__ == "__main__":
    unittest.main()
