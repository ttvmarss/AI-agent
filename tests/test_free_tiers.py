import json, os, stat, tempfile, threading, time, unittest
from praxis import proc, secrets
from praxis.openai_compat import OpenAICompatProvider
from praxis.redact import find_secrets, redact
from praxis.router import ModelUnavailable, ProviderError, RateLimited, Router, ScriptedProvider
from tests.test_providers import serve

MSGS = [{"role": "system", "content": "SYS"}, {"role": "user", "content": "hello"}]


def chat_server(handler=None, status=200, headers=None, body=None):
    def route(h, m, path, req):
        h.server.reqs.append((m, path, req, dict(h.headers)))
        if handler:
            return handler(h, m, path, req)
        if path.endswith("/models"):
            return h._send({"data": [{"id": "free-a", "pricing": {"prompt": "0", "completion": "0"}},
                                     {"id": "paid-b", "pricing": {"prompt": "0.001", "completion": "0.002"}}]})
        payload = body or {"choices": [{"message": {"content": "<think>x</think>ANSWER"}}],
                           "usage": {"prompt_tokens": 12, "completion_tokens": 5}}
        data = json.dumps(payload).encode()
        h.send_response(status)
        for k, v in (headers or {}).items():
            h.send_header(k, v)
        h.send_header("content-length", str(len(data))); h.end_headers(); h.wfile.write(data)
    return serve(route)


class Adapter(unittest.TestCase):
    def mk(self, url, **kw):
        kw.setdefault("name", "groq"); kw.setdefault("model", "m1"); kw.setdefault("api_key", "sk-test-KEY")
        return OpenAICompatProvider(base_url=url + "/v1", **kw)

    def test_request_shape_auth_and_parsing(self):
        srv, url = chat_server(); self.addCleanup(srv.shutdown)
        p = self.mk(url, privacy="cloud")
        out = p.complete("planner", MSGS)
        self.assertEqual(out, "ANSWER")                                  # <think> blocks stripped
        m, path, req, hdrs = srv.reqs[0]
        self.assertEqual(path, "/v1/chat/completions")
        self.assertEqual(req["model"], "m1"); self.assertEqual(req["messages"], MSGS)
        self.assertEqual(req["temperature"], 0); self.assertFalse(req.get("stream"))
        self.assertEqual(hdrs.get("Authorization"), "Bearer sk-test-KEY")
        self.assertEqual(p.last_meta["prompt_tokens"], 12); self.assertEqual(p.last_meta["cost_usd"], 0.0)
        self.assertEqual(p.card.name, "groq/m1"); self.assertEqual(p.card.privacy, "cloud")

    def test_rate_limit_carries_retry_after(self):
        srv, url = chat_server(status=429, headers={"Retry-After": "37"}, body={"error": {"message": "rate limit"}})
        self.addCleanup(srv.shutdown)
        with self.assertRaises(RateLimited) as cm:
            self.mk(url).complete("planner", MSGS)
        self.assertEqual(cm.exception.retry_after, 37)

    def test_daily_quota_message_gets_a_long_cooldown(self):
        srv, url = chat_server(status=429, body={"error": {"message": "You exceeded your daily quota (RPD)"}})
        self.addCleanup(srv.shutdown)
        with self.assertRaises(RateLimited) as cm:
            self.mk(url).complete("planner", MSGS)
        self.assertGreaterEqual(cm.exception.retry_after, 3600)

    def test_auth_model_and_server_errors_are_distinguished(self):
        for status, body, exc in ((401, {"error": {"message": "bad key"}}, ProviderError),
                                  (404, {"error": {"message": "model not found"}}, ModelUnavailable),
                                  (400, {"error": {"message": "context length exceeded"}}, ProviderError),
                                  (503, {"error": {"message": "overloaded"}}, ProviderError)):
            srv, url = chat_server(status=status, body=body)
            try:
                with self.assertRaises(exc) as cm:
                    self.mk(url).complete("planner", MSGS)
                if status == 401:
                    self.assertNotIsInstance(cm.exception, (RateLimited, ModelUnavailable))
                    self.assertNotIn("sk-test-KEY", str(cm.exception))   # a key must never be echoed into an error
            finally:
                srv.shutdown()

    def test_missing_key_is_a_clear_error_and_nothing_is_sent(self):
        srv, url = chat_server(); self.addCleanup(srv.shutdown)
        os.environ.pop("NOPE_API_KEY", None)
        p = OpenAICompatProvider("nope", "m", url + "/v1", key_env="NOPE_API_KEY", privacy="cloud")
        with self.assertRaises(ProviderError) as cm:
            p.complete("planner", MSGS)
        self.assertIn("NOPE_API_KEY", str(cm.exception)); self.assertEqual(srv.reqs, [])

    def test_oversized_prompt_is_refused_before_spending_a_request(self):
        srv, url = chat_server(); self.addCleanup(srv.shutdown)
        p = self.mk(url, max_prompt_tokens=100)
        with self.assertRaises(ProviderError) as cm:
            p.complete("planner", [{"role": "user", "content": "x" * 4000}])
        self.assertIn("tokens", str(cm.exception)); self.assertEqual(srv.reqs, [])

    def test_local_rate_limiter_spaces_requests_to_the_tier_rpm(self):
        srv, url = chat_server(); self.addCleanup(srv.shutdown)
        t = [100.0]; slept = []
        def sleep(s): slept.append(s); t[0] += s
        p = self.mk(url, rpm=5, clock=lambda: t[0], sleep=sleep)       # 5/min -> one request per 12 s
        p.complete("planner", MSGS); p.complete("planner", MSGS)
        self.assertEqual(len(srv.reqs), 2)
        self.assertAlmostEqual(sum(slept), 12.0, places=0)

    def test_cancel_interrupts_the_throttle_wait(self):
        srv, url = chat_server(); self.addCleanup(srv.shutdown)
        p = self.mk(url, rpm=1)           # second call would wait ~60 s
        p.complete("planner", MSGS)
        ev = threading.Event(); proc.set_cancel(ev); threading.Timer(0.3, ev.set).start()
        t0 = time.time()
        try:
            with self.assertRaises(ProviderError):
                p.complete("planner", MSGS)
        finally:
            proc.set_cancel(None)
        self.assertLess(time.time() - t0, 5)

    def test_discover_lists_models_and_filters_free_ones(self):
        srv, url = chat_server(); self.addCleanup(srv.shutdown)
        p = self.mk(url)
        self.assertEqual(p.discover(), ["free-a", "paid-b"])
        self.assertEqual(p.discover(free_only=True), ["free-a"])


class KeyStore(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(); os.environ["PRAXIS_HOME"] = self.home
        self.addCleanup(lambda: os.environ.pop("PRAXIS_HOME", None))
        os.environ.pop("GROQ_API_KEY", None)

    def test_env_wins_over_file_and_file_is_private(self):
        secrets.set("groq", "file-key-123456")
        self.assertEqual(secrets.get("groq", "GROQ_API_KEY"), "file-key-123456")
        os.environ["GROQ_API_KEY"] = "env-key-654321"
        self.addCleanup(lambda: os.environ.pop("GROQ_API_KEY", None))
        self.assertEqual(secrets.get("groq", "GROQ_API_KEY"), "env-key-654321")
        if os.name == "posix":
            mode = stat.S_IMODE(os.stat(os.path.join(self.home, "secrets.json")).st_mode)
            self.assertEqual(mode, 0o600)

    def test_names_mask_and_remove(self):
        secrets.set("groq", "abcdefghijklmnop"); secrets.set("cerebras", "zzzzzzzzzzzzzzzz")
        self.assertEqual(secrets.names(), ["cerebras", "groq"])
        self.assertEqual(secrets.mask("abcdefghijklmnop"), "abcd...mnop")
        self.assertNotIn("efghijkl", secrets.mask("abcdefghijklmnop"))
        secrets.remove("groq"); self.assertIsNone(secrets.get("groq", "GROQ_API_KEY"))

    def test_corrupt_file_does_not_crash(self):
        open(os.path.join(self.home, "secrets.json"), "w").write("{broken")
        self.assertIsNone(secrets.get("groq", "GROQ_API_KEY")); secrets.set("groq", "k" * 12)
        self.assertEqual(secrets.get("groq", "GROQ_API_KEY"), "k" * 12)


class SecretScanner(unittest.TestCase):
    def test_detects_common_credentials(self):
        cases = {"private key": "-----BEGIN RSA PRIVATE KEY-----\nabc", "aws access key": "id AKIAABCDEFGHIJKLMNOP x",
                 "github token": "ghp_" + "a" * 36, "api key": "sk-" + "A1b2C3d4" * 4,
                 "google api key": "AIza" + "x" * 35, "jwt": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV",
                 "password assignment": 'DB_PASSWORD = "hunter2hunter2"'}
        for kind, text in cases.items():
            self.assertIn(kind, find_secrets(f"some context\n{text}\nmore"), kind)

    def test_ordinary_text_and_code_are_not_flagged(self):
        for text in ("def add(a, b): return a + b", "The password policy requires rotation.", "x = 1\nprint('hello world')",
                     "token_count = len(tokens)", "sk = 3"):
            self.assertEqual(find_secrets(text), [], text)

    def test_redact_masks_the_value(self):
        out = redact("key=AKIAABCDEFGHIJKLMNOP end")
        self.assertNotIn("AKIAABCDEFGHIJKLMNOP", out); self.assertIn("[REDACTED", out)


class PrivacyClasses(unittest.TestCase):
    def P(self, name, privacy):
        p = ScriptedProvider(["R-" + name] * 3, name=name, privacy=privacy); p.tier = None; return p

    def setUp(self):
        self.local, self.cloud, self.open_ = self.P("l", "local"), self.P("c", "cloud"), self.P("o", "open")
        self.router = Router([self.open_, self.cloud, self.local], {"planner": ["o", "c", "l"]})

    def test_private_allows_only_local(self):
        self.assertEqual([p.card.name for p in self.router.eligible("planner", "private")], ["l"])

    def test_project_allows_local_and_trusted_cloud_never_open(self):
        self.assertEqual(sorted(p.card.name for p in self.router.eligible("planner", "project")), ["c", "l"])

    def test_open_allows_everything(self):
        self.assertEqual(len(self.router.eligible("planner", "open")), 3)

    def test_unknown_privacy_label_is_treated_as_open_not_trusted(self):
        weird = self.P("w", "mystery")
        self.assertEqual(Router([weird]).eligible("planner", "project"), [])

    def test_open_provider_never_sees_a_detected_secret(self):
        msgs = [{"role": "user", "content": "config:\nAWS_KEY=AKIAABCDEFGHIJKLMNOP"}]
        self.assertEqual(self.router.call("planner", msgs, data_class="open"), "R-c")   # skipped o, used trusted cloud
        self.assertEqual(self.open_.calls, [])

    def test_secret_blocks_open_but_the_event_says_why(self):
        ev = []
        msgs = [{"role": "user", "content": "token ghp_" + "a" * 36}]
        self.router.call("planner", msgs, data_class="open", on_event=lambda t, p: ev.append((t, p)))
        self.assertTrue(any(t == "model.skipped" and "secret" in p["reason"] for t, p in ev))

    def test_only_open_provider_and_secret_present_means_no_call(self):
        r = Router([self.P("o", "open")])
        with self.assertRaises(ProviderError):
            r.call("planner", [{"role": "user", "content": "AKIAABCDEFGHIJKLMNOP"}], data_class="open")

    def test_retry_after_sets_the_cooldown(self):
        t = [0.0]
        class Lim(ScriptedProvider):
            pass
        a = Lim([RateLimited("rpm")], name="a"); a.queue[0].retry_after = 30
        b = ScriptedProvider(["B", "B"], name="b")
        r = Router([a, b], {"planner": ["a", "b"]}, cooldown_s=900, clock=lambda: t[0])
        r.call("planner", [])
        self.assertAlmostEqual(r.cooling["a"], 30.0)           # not the 900 s default
        t[0] = 31; a.queue.append("A-back")
        self.assertEqual(r.call("planner", []), "A-back")


if __name__ == "__main__":
    unittest.main()
