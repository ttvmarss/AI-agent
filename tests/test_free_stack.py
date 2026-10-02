import contextlib, io, os, tempfile, unittest
from unittest import mock
from praxis import __main__ as cli, secrets
from praxis.catalog import CATALOG, recommend
from praxis.config import Stack, load_config
from praxis.free_tiers import DISCONTINUED, PRESETS, preset
from praxis.hardware import GB, GPU, Profile
from praxis.openai_compat import OpenAICompatProvider
from praxis.providers import OllamaProvider
from praxis.registry import Registry


def stack(env=None, **cfg_over):
    cfg = load_config()
    cfg["providers"]["ollama"]["enabled"] = False
    for name in ("claude", "codex", "droid"):
        cfg["providers"][name]["enabled"] = False
    for k, v in cfg_over.items():
        cfg["providers"].setdefault(k, {}).update(v)
    with mock.patch.dict(os.environ, env or {}):
        return Stack(cfg, Registry(), detect_sandbox=False)


class Isolated(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(); os.environ["PRAXIS_HOME"] = self.home
        for k in list(os.environ):
            if k.endswith("_API_KEY"):
                os.environ.pop(k)
        self.addCleanup(lambda: os.environ.pop("PRAXIS_HOME", None))


class Presets(unittest.TestCase):
    def test_every_preset_has_provenance_and_a_valid_privacy_class(self):
        for p in PRESETS:
            self.assertTrue(p.source.startswith("http") and p.checked and p.signup_url.startswith("http"), p.id)
            self.assertIn(p.privacy, ("cloud", "open"), p.id)
            self.assertTrue(p.base_url.startswith("https://") or p.kind == "ollama-cloud", p.id)

    def test_data_terms_drive_the_privacy_class(self):
        # free tiers whose own terms allow training / human review / logging are 'open'; documented no-training are 'cloud'
        for pid in ("gemini", "mistral", "nvidia", "openrouter"):
            self.assertEqual(preset(pid).privacy, "open", pid)
        for pid in ("groq", "cerebras", "ollama-cloud"):
            self.assertEqual(preset(pid).privacy, "cloud", pid)

    def test_dead_free_paths_are_listed_with_dates_not_silently_omitted(self):
        names = " ".join(d.name for d in DISCONTINUED).lower()
        for needle in ("gemini cli", "qwen code", "github models"):
            self.assertIn(needle, names)
        self.assertTrue(all(d.ended and d.source.startswith("http") for d in DISCONTINUED))

    def test_documented_limits_are_encoded(self):
        self.assertEqual((preset("groq").rpm, preset("groq").rpd, preset("groq").tpd), (30, 1000, 200_000))
        self.assertEqual(preset("cerebras").rpm, 5)
        self.assertEqual(preset("cerebras").tpd, 1_000_000)
        self.assertTrue(preset("groq").max_prompt_tokens and preset("groq").max_prompt_tokens <= 8000)   # 8K tokens/minute


class FreeStack(Isolated):
    def test_no_keys_means_skipped_with_the_exact_fix_not_a_crash(self):
        st = stack()
        self.assertEqual(st.providers, [])
        self.assertIn("praxis keys set groq", st.skipped["groq"])

    def test_keys_in_env_or_file_instantiate_one_provider_per_model(self):
        secrets.set("cerebras", "csk-123456789012")
        st = stack(env={"GROQ_API_KEY": "gsk_abcdefghijkl"})
        names = sorted(p.card.name for p in st.providers)
        self.assertIn("groq/openai/gpt-oss-120b", names); self.assertIn("cerebras/gpt-oss-120b", names)
        g = next(p for p in st.providers if p.card.name == "groq/openai/gpt-oss-120b")
        self.assertIsInstance(g, OpenAICompatProvider)
        self.assertEqual((g.card.privacy, g.tier, g.rpm), ("cloud", "free", 30))

    def test_open_tiers_are_open_class(self):
        st = stack(env={"GEMINI_API_KEY": "AIza" + "x" * 35})
        g = next(p for p in st.providers if p.card.name.startswith("gemini/"))
        self.assertEqual(g.card.privacy, "open")

    def test_ollama_cloud_uses_the_cloud_host_with_a_key_and_a_fixed_model(self):
        st = stack(env={"OLLAMA_API_KEY": "ollama-key-123456"})
        o = next(p for p in st.providers if p.card.name.startswith("ollama-cloud/"))
        self.assertIsInstance(o, OllamaProvider)
        self.assertEqual(o.host, "https://ollama.com"); self.assertEqual(o.card.privacy, "cloud"); self.assertEqual(o.tier, "free")
        self.assertEqual(o.api_key, "ollama-key-123456"); self.assertEqual(o.resolve_model(), "gpt-oss:120b")

    def test_budgets_are_derived_from_the_documented_free_limits(self):
        st = stack(env={"GROQ_API_KEY": "gsk_abcdefghijkl"})
        self.assertEqual(st.usage.budgets["groq"]["calls_24h"], 900)          # 90% of the 1,000/day limit
        self.assertEqual(st.usage.budgets["groq"]["tokens_24h"], 180_000)

    def test_user_budget_overrides_the_derived_one(self):
        cfg = load_config(); cfg["budgets"] = {"groq": {"calls_24h": 10}}
        for n in ("claude", "codex", "droid", "ollama"):
            cfg["providers"][n]["enabled"] = False
        with mock.patch.dict(os.environ, {"GROQ_API_KEY": "gsk_abcdefghijkl"}):
            st = Stack(cfg, Registry(), detect_sandbox=False)
        self.assertEqual(st.usage.budgets["groq"]["calls_24h"], 10)

    def test_disabled_preset_is_not_built_even_with_a_key(self):
        st = stack(env={"GROQ_API_KEY": "gsk_abcdefghijkl"}, groq={"enabled": False})
        self.assertFalse(any(p.card.name.startswith("groq/") for p in st.providers))

    def test_free_families_are_in_the_default_role_orders(self):
        roles = load_config()["roles"]
        for fam in ("groq", "cerebras", "ollama-cloud", "gemini", "mistral", "nvidia", "openrouter"):
            self.assertIn(fam, roles["planner"]); self.assertIn(fam, roles["critic"])

    def test_a_project_folder_cannot_inject_a_free_provider_endpoint(self):
        ws = tempfile.mkdtemp()
        open(os.path.join(ws, "praxis.toml"), "w").write('[providers.groq]\nbase_url = "https://evil.example/v1"\nenabled = true\n')
        self.assertNotIn("base_url", load_config(ws)["providers"]["groq"])


class LocalCatalog(unittest.TestCase):
    def test_new_local_models_have_provenance(self):
        tags = {m.tag: m for m in CATALOG}
        for t in ("gpt-oss:20b", "gemma4:26b-a4b", "gemma4:12b"):
            self.assertIn(t, tags); self.assertTrue(tags[t].source.startswith("https://ollama.com/library/"), t)
        self.assertEqual((tags["gpt-oss:20b"].total_b, tags["gpt-oss:20b"].size_gb), (21, 14))
        self.assertLess(tags["gemma4:26b-a4b"].active_b, 5)

    def test_published_benchmarks_outrank_the_size_prior(self):
        tags = {m.tag: m for m in CATALOG}
        self.assertEqual(tags["qwen3.6:35b-a3b"].lcb, 80.4); self.assertEqual(tags["qwen3.6:27b"].lcb, 83.9)
        self.assertGreater(tags["qwen3.6:35b-a3b"].rank, tags["laguna-xs-2.1"].rank)   # evidence beats an unmeasured size prior

    def test_3050_rig_still_gets_the_qwen_moe_and_the_new_models_fit(self):
        p = Profile("windows", "Ryzen 7 7700", 16, 32 * GB, 70, [GPU("RTX 3050", 8 * GB, 224)])
        self.assertIn("qwen3.6:35b-a3b", recommend(p)["daily"].model.tag)
        from praxis.catalog import _score
        fits = {x.model.tag for x in _score(p)}
        self.assertTrue({"gpt-oss:20b", "gemma4:26b-a4b"} <= fits)


class FreeCli(Isolated):
    def run_cli(self, argv, stdin_tty=False):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = cli.main(argv)
        return code, buf.getvalue()

    def test_free_lists_status_limits_privacy_and_the_dead_paths(self):
        code, out = self.run_cli(["free", "--workspace", tempfile.mkdtemp()])
        self.assertEqual(code, 0)
        for needle in ("groq", "cerebras", "gemini", "OPEN", "no key", "30/min", "Discontinued", "Gemini CLI", "2026-06-18"):
            self.assertIn(needle, out)

    def test_keys_set_list_remove_never_print_the_secret(self):
        with mock.patch("getpass.getpass", return_value="gsk_supersecretvalue123"):
            code, out = self.run_cli(["keys", "set", "groq", "--workspace", tempfile.mkdtemp()])
        self.assertEqual(code, 0); self.assertNotIn("supersecret", out)
        code, out = self.run_cli(["keys", "list", "--workspace", tempfile.mkdtemp()])
        self.assertIn("groq", out); self.assertNotIn("supersecret", out); self.assertIn("gsk_...e123", out)
        self.run_cli(["keys", "remove", "groq", "--workspace", tempfile.mkdtemp()])
        self.assertEqual(secrets.names(), [])

    def test_unknown_key_name_is_refused(self):
        code, out = self.run_cli(["keys", "set", "bogus", "--workspace", tempfile.mkdtemp()])
        self.assertNotEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
