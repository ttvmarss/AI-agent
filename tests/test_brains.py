"""Devin (the `devin` CLI from Devin Desktop) and Factory (droid) as brains: how PRAXIS calls them, finds them and wires them in.
Tested against fake programs that follow the documented interfaces (docs.devin.ai/cli/reference/commands, docs.factory.ai droid-exec);
the real programs were not available here."""
import os, stat, sys, tempfile, unittest
from unittest import mock

from praxis import discover
from praxis.config import Stack, load_config
from praxis.providers import DevinCLI, DevinProvider
from praxis.registry import Registry
from praxis.router import ProviderError, RateLimited
from tests.test_providers import FakeBin, MSGS


def make_stack(env=None, **devin):
    cfg = load_config()
    cfg["providers"]["ollama"]["enabled"] = False
    for n in ("claude", "codex", "droid"):
        cfg["providers"][n]["enabled"] = False
    cfg["providers"]["devin"].update(devin)
    with mock.patch.dict(os.environ, env or {}):
        return Stack(cfg, Registry(), detect_sandbox=False)


class DevinCLITests(FakeBin):
    OK = "print('\\x1b[1mDEVIN-ANSWER\\x1b[0m')"

    def test_planning_call_is_noninteractive_readonly_and_in_an_empty_folder(self):
        self.install("devin", self.OK)
        d = DevinCLI()
        self.assertEqual(d.complete("planner", MSGS), "DEVIN-ANSWER")               # colour codes are stripped
        r = self.recorded(); a = r["argv"]
        self.assertIn("--print", a)
        self.assertEqual(a[a.index("--permission-mode") + 1], "normal")              # it cannot ask in print mode, so nothing is edited
        self.assertEqual(a[a.index("--respect-workspace-trust") + 1], "false")       # print mode cannot show the trust prompt
        self.assertNotEqual(os.path.realpath(r["cwd"]), os.path.realpath(os.getcwd()))
        self.assertNotIn("USER-PROMPT", " ".join(a))                                 # the prompt is in a file, not on the command line
        self.assertEqual(r["stdin"], "")

    def test_the_prompt_file_holds_system_and_user_text(self):
        self.install("devin", "print(open(sys.argv[sys.argv.index('--prompt-file') + 1]).read())")
        out = DevinCLI().complete("planner", MSGS)
        self.assertIn("SYS-PROMPT", out); self.assertIn("USER-PROMPT", out)

    def test_delegate_may_edit_inside_the_workspace_only(self):
        self.install("devin", self.OK)
        ws = tempfile.mkdtemp()
        DevinCLI().delegate("make a.txt", ws)
        r = self.recorded(); a = r["argv"]
        self.assertEqual(a[a.index("--permission-mode") + 1], "accept-edits")
        self.assertEqual(os.path.realpath(r["cwd"]), os.path.realpath(ws))

    def test_a_model_is_passed_only_when_chosen(self):
        self.install("devin", self.OK)
        DevinCLI().complete("planner", MSGS); self.assertNotIn("--model", self.recorded()["argv"])
        DevinCLI(model="adaptive").complete("planner", MSGS); a = self.recorded()["argv"]; self.assertEqual(a[a.index("--model") + 1], "adaptive")

    def test_an_older_cli_without_prompt_file_gets_the_prompt_inline(self):
        self.install("devin", "if '--prompt-file' in sys.argv:\n    sys.stderr.write('error: unexpected argument --prompt-file'); sys.exit(2)\nprint('INLINE ' + sys.argv[sys.argv.index('-p') + 1][:40])")
        out = DevinCLI().complete("planner", MSGS)
        self.assertTrue(out.startswith("INLINE ")); self.assertIn("SYS-PROMPT", out)

    def test_limits_and_empty_answers_are_reported_properly(self):
        self.install("devin", "sys.stderr.write('You have reached your usage limit'); sys.exit(1)")
        with self.assertRaises(RateLimited): DevinCLI().complete("planner", MSGS)
        self.install("devin", "print('   ')")
        with self.assertRaises(ProviderError): DevinCLI().complete("planner", MSGS)
        self.install("devin", "sys.stderr.write('boom'); sys.exit(3)")
        with self.assertRaises(ProviderError): DevinCLI().delegate("x", tempfile.mkdtemp())

    def test_version(self):
        self.install("devin", "print('devin 1.2.3')")
        self.assertEqual(DevinCLI().version(), "devin 1.2.3")


class Discovery(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.local = os.path.join(self.root, "AppData", "Local")
        self.env = {"LOCALAPPDATA": self.local, "USERPROFILE": os.path.join(self.root, "u"), "PATH": ""}

    def touch(self, *parts):
        p = os.path.join(*parts); os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w").write("x"); os.chmod(p, 0o755); return p

    def test_the_desktop_app_itself_is_never_mistaken_for_the_cli(self):
        app = self.touch(self.local, "Programs", "Devin", "Devin.exe")
        cands = discover.candidates("devin", self.env)
        self.assertNotIn(app, cands)

    def test_a_cli_beside_the_desktop_app_is_found_and_only_if_it_documents_print(self):
        cli = self.touch(self.local, "Programs", "Devin", "bin", "devin.cmd")
        found = discover.find("devin", self.env, verify=lambda p: p == cli)
        self.assertEqual(found, cli)
        self.assertIsNone(discover.find("devin", self.env, verify=lambda p: False))            # an editor launcher fails the check

    def test_the_official_installers_folder_is_searched(self):
        cli = self.touch(self.local, "devin", "cli", "bin", "devin.EXE")
        self.assertEqual(discover.find("devin", self.env, verify=lambda p: True), cli)
        self.assertIn(os.path.join(self.local, "devin", "cli", "bin", "devin.exe"), discover.candidates("devin", self.env))

    def test_the_check_runs_help_and_needs_the_print_flag(self):
        class R:  # a fake completed process
            def __init__(self, out): self.stdout, self.stderr = out, ""
        self.assertTrue(discover.looks_like_devin_cli("x", run=lambda a: R("Usage: devin [OPTIONS]\n  -p, --print  run once")))
        self.assertFalse(discover.looks_like_devin_cli("x", run=lambda a: R("Usage: windsurf [options] [paths...]")))
        def boom(a): raise OSError("nope")
        self.assertFalse(discover.looks_like_devin_cli("x", run=boom))

    def test_factory_droid_is_found_in_its_known_folders_but_not_the_desktop_app(self):
        self.touch(self.local, "Factory", "factory-desktop.exe")
        self.assertIsNone(discover.find("droid", self.env))
        droid = self.touch(self.local, "Factory", "bin", "droid.exe")
        self.assertEqual(discover.find("droid", self.env), droid)

    def test_unset_environment_variables_never_become_relative_paths(self):
        os.makedirs("Programs/Devin/bin", exist_ok=True) if False else None
        for c in discover.candidates("devin", {"PATH": ""}):
            self.assertTrue(os.path.isabs(c), c)

    def test_a_devin_on_path_that_is_really_the_editor_launcher_is_not_used(self):
        launcher = self.touch(self.root, "pathdir", "devin")
        cli = self.touch(self.local, "Programs", "Devin", "bin", "devin.cmd")
        env = dict(self.env, PATH=os.path.dirname(launcher))
        self.assertEqual(discover.find("devin", env, verify=lambda p: p == cli), cli)
        found = discover.ensure_on_path(("devin",), env, verify=lambda p: p == cli)
        self.assertEqual(found["devin"], cli); self.assertTrue(env["PATH"].startswith(os.path.dirname(cli)))      # ours now comes first

    def test_found_tools_are_added_to_path_for_this_process_only(self):
        droid = self.touch(self.local, "Factory", "bin", "droid.exe")
        env = dict(self.env)
        found = discover.ensure_on_path(("droid",), env)
        self.assertEqual(found["droid"], droid); self.assertTrue(env["PATH"].startswith(os.path.dirname(droid)))
        self.assertEqual(discover.ensure_on_path(("droid",), {"PATH": "", "LOCALAPPDATA": os.path.join(self.root, "nothing"), "USERPROFILE": ""}), {"droid": None})


HELP = "print('Usage: devin [OPTIONS]  -p, --print  run once' if '--help' in sys.argv else 'x')"


class Wiring(FakeBin):
    def test_an_installed_devin_cli_becomes_a_brain_that_can_think_and_work(self):
        self.install("devin", HELP)
        st = make_stack()
        p = [x for x in st.providers if x.card.name.split("/")[0] == "devin"]
        self.assertEqual(len(p), 1); self.assertIsInstance(p[0], DevinCLI); self.assertTrue(p[0].can_complete and p[0].can_delegate)
        self.assertIn("devin", st.agents); self.assertNotIn("devin", st.skipped)

    def test_without_the_cli_it_says_exactly_what_to_do(self):
        st = make_stack()
        msg = st.skipped["devin"]
        self.assertIn("Install Devin CLI", msg); self.assertIn("devin auth login", msg)
        self.assertFalse([x for x in st.providers if x.card.name.startswith("devin")])

    def test_api_mode_and_the_old_fallback_still_use_the_cloud_api(self):
        st = make_stack(env={"DEVIN_API_KEY": "k", "DEVIN_ORG_ID": "o"})                   # auto: no CLI, but API credentials
        d = [x for x in st.providers if x.card.name == "devin"]
        self.assertTrue(d and isinstance(d[0], DevinProvider) and not d[0].can_complete)
        self.install("devin", HELP)
        st = make_stack(env={"DEVIN_API_KEY": "k", "DEVIN_ORG_ID": "o"}, mode="api")        # forced API even though the CLI exists
        self.assertIsInstance([x for x in st.providers if x.card.name == "devin"][0], DevinProvider)
        st = make_stack(mode="api"); self.assertIn("DEVIN_API_KEY", st.skipped["devin"])

    def test_it_can_be_switched_off(self):
        self.install("devin", HELP)
        st = make_stack(enabled=False)
        self.assertEqual(st.skipped["devin"], "disabled in config"); self.assertFalse([x for x in st.providers if x.card.name.startswith("devin")])

    def test_delegating_to_devin_always_needs_the_owners_approval(self):
        from praxis.guard import classify_call
        self.assertEqual(classify_call("agent.delegate", {"agent": "devin", "task": "x"}, tempfile.mkdtemp()), 4)


if __name__ == "__main__":
    unittest.main()
