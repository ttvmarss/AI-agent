import http.server, json, os, stat, tempfile, threading, unittest
from praxis.providers import ClaudeCLI, CodexCLI, DroidCLI, OllamaProvider, DevinProvider
from praxis.registry import Registry, pick_ollama_model, parse_params
from praxis.router import ProviderError, RateLimited, Router, ScriptedProvider

MSGS = [{"role": "system", "content": "SYS-PROMPT"}, {"role": "user", "content": "USER-PROMPT"}]


class FakeBin(unittest.TestCase):
    """Fake CLIs on PATH that record argv / stdin / selected env / cwd, then answer like the real tool."""

    def setUp(self):
        self.bin = tempfile.mkdtemp()
        self.rec = os.path.join(self.bin, "rec.json")
        self._env = dict(os.environ)
        os.environ["PATH"] = self.bin + os.pathsep + os.environ["PATH"]
        os.environ.update(FAKE_REC=self.rec, OPENAI_API_KEY="sk-leak", CODEX_API_KEY="ck-leak",
                          ANTHROPIC_API_KEY="ak-leak", ANTHROPIC_AUTH_TOKEN="at-leak", FACTORY_API_KEY="fk-ok")

    def tearDown(self):
        os.environ.clear(); os.environ.update(self._env)

    def install(self, name, body):
        p = os.path.join(self.bin, name)
        with open(p, "w") as f:
            f.write("#!/usr/bin/env python3\nimport sys, os, json\n"
                    "rec = dict(argv=sys.argv[1:], stdin=sys.stdin.read(), cwd=os.getcwd(),\n"
                    "           files={a: open(a).read() for a in sys.argv[1:] if a.endswith('.sysprompt') and os.path.exists(a)},\n"
                    "           env={k: os.environ.get(k) for k in ['OPENAI_API_KEY','CODEX_API_KEY','ANTHROPIC_API_KEY','ANTHROPIC_AUTH_TOKEN','FACTORY_API_KEY']})\n"
                    "open(os.environ['FAKE_REC'], 'w').write(json.dumps(rec))\n" + body)
        os.chmod(p, os.stat(p).st_mode | stat.S_IEXEC)

    def recorded(self):
        with open(self.rec) as f:
            return json.load(f)


class ClaudeTests(FakeBin):
    OK = "print(json.dumps({'type':'result','is_error':False,'result':'PLAN','total_cost_usd':0.01,'stop_reason':'end_turn'}))"

    def test_subscription_mode_strips_api_keys_and_is_readonly(self):
        self.install("claude", self.OK)
        c = ClaudeCLI()
        self.assertEqual(c.complete("planner", MSGS), "PLAN")
        r = self.recorded()
        self.assertIsNone(r["env"]["ANTHROPIC_API_KEY"]); self.assertIsNone(r["env"]["ANTHROPIC_AUTH_TOKEN"])
        self.assertEqual(r["env"]["OPENAI_API_KEY"], "sk-leak")  # only the relevant vendor's keys are stripped
        a = r["argv"]
        self.assertIn("-p", a); self.assertIn("json", a)
        self.assertEqual(a[a.index("--tools") + 1], "")           # all tools off for planning
        f = a[a.index("--system-prompt-file") + 1]          # long/multiline prompts go via file (Windows .cmd shims
        self.assertEqual(r["files"][f], "SYS-PROMPT")         # mangle newlines and cap argv length)
        self.assertNotIn("--system-prompt", a)
        self.assertIn("USER-PROMPT", r["stdin"]); self.assertNotIn("SYS-PROMPT", r["stdin"])
        self.assertNotEqual(os.path.realpath(r["cwd"]), os.path.realpath(os.getcwd()))  # empty temp dir
        self.assertEqual(c.last_meta["cost_usd"], 0.01)

    def test_delegate_flags_are_edit_only_no_bash(self):
        self.install("claude", self.OK)
        ws = tempfile.mkdtemp()
        ClaudeCLI().delegate("do it", ws)
        a = self.recorded()["argv"]
        self.assertEqual(a[a.index("--permission-mode") + 1], "acceptEdits")
        tools = a[a.index("--tools") + 1].split(",")
        self.assertNotIn("Bash", tools)
        self.assertEqual(os.path.realpath(self.recorded()["cwd"]), os.path.realpath(ws))

    def test_error_and_limit_mapping(self):
        self.install("claude", "print(json.dumps({'is_error':True,'result':'Claude usage limit reached'}))")
        with self.assertRaises(RateLimited):
            ClaudeCLI().complete("planner", MSGS)
        self.install("claude", "print(json.dumps({'is_error':True,'result':'bad request'}))")
        with self.assertRaises(ProviderError) as cm:
            ClaudeCLI().complete("planner", MSGS)
        self.assertNotIsInstance(cm.exception, RateLimited)

    def test_missing_binary_is_clean_error(self):
        os.environ["PATH"] = self.bin
        with self.assertRaises(ProviderError) as cm:
            ClaudeCLI().complete("planner", MSGS)
        self.assertIn("not installed", str(cm.exception))


class CodexTests(FakeBin):
    BODY = ("o = sys.argv[sys.argv.index('-o') + 1]\nopen(o, 'w').write('CODEX-ANSWER')\n")

    def test_complete_is_readonly_ephemeral_stdin_and_subscription(self):
        self.install("codex", self.BODY)
        self.assertEqual(CodexCLI().complete("planner", MSGS), "CODEX-ANSWER")
        r = self.recorded(); a = r["argv"]
        self.assertEqual(a[0], "exec")
        self.assertEqual(a[a.index("--sandbox") + 1], "read-only")
        self.assertIn("--skip-git-repo-check", a); self.assertIn("--ephemeral", a)
        self.assertEqual(a[-1], "-")  # prompt via stdin
        self.assertIn("SYS-PROMPT", r["stdin"]); self.assertIn("USER-PROMPT", r["stdin"])
        self.assertIsNone(r["env"]["CODEX_API_KEY"]); self.assertIsNone(r["env"]["OPENAI_API_KEY"])
        self.assertEqual(r["env"]["ANTHROPIC_API_KEY"], "ak-leak")

    def test_delegate_is_workspace_write_in_workspace(self):
        self.install("codex", self.BODY)
        ws = tempfile.mkdtemp()
        CodexCLI().delegate("fix it", ws)
        r = self.recorded()
        self.assertEqual(r["argv"][r["argv"].index("--sandbox") + 1], "workspace-write")
        self.assertEqual(os.path.realpath(r["cwd"]), os.path.realpath(ws))

    def test_empty_answer_and_failure(self):
        self.install("codex", "pass\n")
        with self.assertRaises(ProviderError):
            CodexCLI().complete("planner", MSGS)
        self.install("codex", "sys.stderr.write('429 Too Many Requests'); sys.exit(1)\n")
        with self.assertRaises(RateLimited):
            CodexCLI().complete("planner", MSGS)


class DroidTests(FakeBin):
    def test_complete_readonly_default_and_json_parse(self):
        self.install("droid", "print(json.dumps({'type':'result','result':'DROID-ANSWER','is_error':False}))")
        self.assertEqual(DroidCLI().complete("planner", MSGS), "DROID-ANSWER")
        r = self.recorded(); a = r["argv"]
        self.assertEqual(a[:2], ["exec", "-o"]); self.assertNotIn("--auto", a)   # default = read-only
        self.assertEqual(r["env"]["FACTORY_API_KEY"], "fk-ok")                    # Factory credential passes through
        self.assertIn("USER-PROMPT", r["stdin"])

    def test_delegate_auto_low_only(self):
        self.install("droid", "print('plain text answer')")
        ws = tempfile.mkdtemp()
        self.assertEqual(DroidCLI().delegate("do", ws), "plain text answer")
        a = self.recorded()["argv"]
        self.assertEqual(a[a.index("--auto") + 1], "low")
        self.assertNotIn("--skip-permissions-unsafe", a)
        self.assertEqual(a[a.index("--cwd") + 1], ws)

    def test_error_payload(self):
        self.install("droid", "print(json.dumps({'is_error':True,'error':'nope'}))")
        with self.assertRaises(ProviderError):
            DroidCLI().complete("planner", MSGS)


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def _body(self):
        n = int(self.headers.get("content-length") or 0)
        return json.loads(self.rfile.read(n)) if n else None

    def do_GET(self): self.server.route(self, "GET", self.path, None)
    def do_POST(self): self.server.route(self, "POST", self.path, self._body())


def serve(route):
    srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    srv.route = route
    srv.reqs = []
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_port}"


GB = 2**30
TAGS = {"models": [
    {"name": "qwen3.6:27b", "size": 17 * GB, "details": {"parameter_size": "27B"}},
    {"name": "tiny:3b", "size": 2 * GB, "details": {"parameter_size": "3B"}},
    {"name": "mistral-medium:128b", "size": 75 * GB, "details": {"parameter_size": "128B"}},
    {"name": "nomic-embed-text", "size": 1 * GB, "details": {"parameter_size": "137M"}}]}


class OllamaTests(unittest.TestCase):
    def mk(self, **kw):
        def route(h, m, path, body):
            h.server.reqs.append((m, path, body))
            if path == "/api/version": h._send({"version": "0.9.9"})
            elif path == "/api/tags": h._send(TAGS)
            elif path == "/api/chat":
                h._send({"message": {"role": "assistant", "content": kw.get("reply", "<think>hmm</think>{\"ok\": 1}")},
                         "total_duration": 5_000_000, "eval_count": 7})
        srv, url = serve(route)
        self.addCleanup(srv.shutdown)
        return srv, url

    def test_picks_largest_model_that_fits_and_never_embeddings(self):
        srv, url = self.mk()
        p = OllamaProvider(url, memory_bytes=24 * GB)
        self.assertEqual(p.resolve_model(), "qwen3.6:27b")      # 128B (75GB) does not fit; embed excluded
        self.assertEqual(p.card.name, "ollama/qwen3.6:27b")

    def test_more_memory_picks_bigger_and_prefer_wins(self):
        srv, url = self.mk()
        self.assertEqual(OllamaProvider(url, memory_bytes=96 * GB).resolve_model(), "mistral-medium:128b")
        self.assertEqual(OllamaProvider(url, memory_bytes=96 * GB, prefer=["qwen3.6:27b"]).resolve_model(), "qwen3.6:27b")

    def test_measured_score_beats_size_prior(self):
        srv, url = self.mk()
        reg = Registry(); reg.record("ollama/tiny:3b", "planning", 0.95, 10, 1); reg.record("ollama/qwen3.6:27b", "planning", 0.60, 10, 3)
        self.assertEqual(OllamaProvider(url, memory_bytes=24 * GB, registry=reg).resolve_model(), "tiny:3b")

    def test_chat_request_shape_json_mode_and_think_stripping(self):
        srv, url = self.mk()
        p = OllamaProvider(url, memory_bytes=24 * GB, num_ctx=8192)
        self.assertEqual(p.complete("planner", MSGS), '{"ok": 1}')
        body = [b for m, path, b in srv.reqs if path == "/api/chat"][0]
        self.assertEqual(body["model"], "qwen3.6:27b"); self.assertFalse(body["stream"])
        self.assertEqual(body["format"], "json"); self.assertEqual(body["options"]["temperature"], 0)
        self.assertEqual(body["options"]["num_ctx"], 8192); self.assertEqual(body["messages"], MSGS)

    def test_unreachable_and_nothing_fits(self):
        with self.assertRaises(ProviderError):
            OllamaProvider("http://127.0.0.1:9", model="x", timeout=2).complete("planner", MSGS)
        srv, url = self.mk()
        with self.assertRaises(ProviderError):
            OllamaProvider(url, memory_bytes=1 * GB // 2).resolve_model()

    def test_is_local_so_private_data_may_use_it(self):
        self.assertEqual(OllamaProvider("http://x").card.privacy, "local")

    def test_parse_params(self):
        self.assertEqual(parse_params({"parameter_size": "7.6B"}), 7.6e9)
        self.assertEqual(parse_params({}, "qwen3:32b"), 32e9)
        self.assertEqual(parse_params({"parameter_size": "137M"}), 137e6)


class DevinTests(unittest.TestCase):
    def mk(self, statuses):
        seq = list(statuses)
        def route(h, m, path, body):
            h.server.reqs.append((m, path, body, h.headers.get("Authorization")))
            if h.headers.get("Authorization") != "Bearer cog_secret":
                return h._send({"detail": "no"}, 401)
            if m == "POST" and path == "/v3/organizations/org1/sessions":
                return h._send({"session_id": "devin-1", "status": "new", "url": "https://app.devin.ai/s/1"})
            if m == "GET" and path == "/v3/organizations/org1/sessions/devin-1":
                st, det = seq.pop(0) if len(seq) > 1 else seq[0]
                return h._send({"session_id": "devin-1", "status": st, "status_detail": det,
                                "url": "https://app.devin.ai/s/1", "structured_output": {"pr": "x"}})
            h._send({}, 404)
        srv, url = serve(route)
        self.addCleanup(srv.shutdown)
        return srv, url + "/v3"

    def test_polls_until_terminal(self):
        srv, base = self.mk([("running", "working"), ("running", "working"), ("exit", "finished")])
        d = DevinProvider("org1", "cog_secret", base, poll_s=0.01, timeout_s=5)
        out = json.loads(d.delegate("fix bug"))
        self.assertEqual((out["status"], out["status_detail"]), ("exit", "finished"))
        self.assertEqual(out["structured_output"], {"pr": "x"})
        posts = [r for r in srv.reqs if r[0] == "POST"]
        self.assertEqual(posts[0][2], {"prompt": "fix bug"})
        self.assertEqual(sum(r[0] == "GET" for r in srv.reqs), 3)

    def test_stops_polling_when_human_input_needed(self):
        srv, base = self.mk([("running", "waiting_for_approval")])
        out = json.loads(DevinProvider("org1", "cog_secret", base, poll_s=0.01, timeout_s=5).delegate("x"))
        self.assertEqual(out["status_detail"], "waiting_for_approval")

    def test_timeout_returns_running_session_instead_of_hanging(self):
        srv, base = self.mk([("running", "working")])
        out = json.loads(DevinProvider("org1", "cog_secret", base, poll_s=0.01, timeout_s=0.05).delegate("x"))
        self.assertEqual(out["status_detail"], "poll_timeout"); self.assertEqual(out["session_id"], "devin-1")

    def test_auth_failure_and_missing_creds_and_no_completion(self):
        srv, base = self.mk([("exit", "finished")])
        with self.assertRaises(ProviderError):
            DevinProvider("org1", "wrong", base).delegate("x")
        os.environ.pop("DEVIN_API_KEY", None); os.environ.pop("DEVIN_ORG_ID", None)
        with self.assertRaises(ProviderError):
            DevinProvider().delegate("x")
        self.assertFalse(DevinProvider("o", "k").can_complete)
        with self.assertRaises(ProviderError):
            DevinProvider("o", "k").complete("planner", MSGS)


class RouterPolicy(unittest.TestCase):
    def test_private_data_never_reaches_cloud(self):
        cloud = ScriptedProvider(["CLOUD"], name="claude", privacy="cloud")
        local = ScriptedProvider(["LOCAL"], name="ollama/x", privacy="local")
        r = Router([cloud, local])
        self.assertEqual(r.call("planner", [], data_class="private"), "LOCAL")
        self.assertEqual(cloud.calls, [])
        r2 = Router([ScriptedProvider(["CLOUD"], name="claude", privacy="cloud")])
        with self.assertRaises(ProviderError):
            r2.call("planner", [], data_class="private")

    def test_rate_limit_cooldown_fallback_and_recovery(self):
        t = [1000.0]
        a = ScriptedProvider([RateLimited("limit"), "A-again"], name="a")
        b = ScriptedProvider(["B1", "B2"], name="b")
        r = Router([a, b], cooldown_s=60, clock=lambda: t[0])
        self.assertEqual(r.call("planner", []), "B1")     # a hit its limit -> b served
        self.assertEqual(r.call("planner", []), "B2")     # a is cooling down: not even tried
        self.assertEqual(len(a.calls), 1)
        t[0] += 61
        self.assertEqual(r.call("planner", []), "A-again")  # cooldown over, a is back

    def test_config_order_then_measured_order(self):
        a, b = ScriptedProvider(["A"], name="a"), ScriptedProvider(["B"], name="b")
        reg = Registry(); reg.record("a", "planning", 0.5, 5, 1); reg.record("b", "planning", 0.9, 5, 1)
        self.assertEqual(Router([a, b], {"planner": ["a", "b"]}, None).call("planner", []), "A")
        a, b = ScriptedProvider(["A"], name="a"), ScriptedProvider(["B"], name="b")
        self.assertEqual(Router([a, b], {"planner": ["a", "b"]}, reg, "auto").call("planner", []), "B")  # measured wins
        a, b = ScriptedProvider(["A"], name="a"), ScriptedProvider(["B"], name="b")
        reg2 = Registry(); reg2.record("a", "planning", 0.5, 5, 1)  # b unmeasured -> auto keeps config order
        self.assertEqual(Router([a, b], {"planner": ["a", "b"]}, reg2, "auto").call("planner", []), "A")

    def test_delegate_only_provider_is_never_asked_to_complete(self):
        class D(ScriptedProvider): can_complete = False
        d = D(["X"], name="devin"); ok = ScriptedProvider(["OK"], name="claude")
        self.assertEqual(Router([d, ok]).call("planner", []), "OK"); self.assertEqual(d.calls, [])


if __name__ == "__main__":
    unittest.main()
