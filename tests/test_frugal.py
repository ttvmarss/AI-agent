import json, os, tempfile, time, unittest
from praxis.events import EventLog
from praxis.executive import Executive, VERIFIED, FAILED
from praxis.registry import Registry
from praxis.router import ProviderError, RateLimited, Router, ScriptedProvider, cost_class, parse_reset_seconds
from praxis.usage import UsageTracker
from tests.test_executive import plan, W


def P(name, answers=("ok",) * 5, privacy="cloud", tier=None):
    p = ScriptedProvider(list(answers), name=name, privacy=privacy); p.tier = tier; return p


class Usage(unittest.TestCase):
    def test_windows_costs_and_pressure(self):
        t = [10_000_000.0]
        u = UsageTracker({"claude": {"cost_usd_5h": 2.0, "calls_24h": 100}}, clock=lambda: t[0])
        u.record("claude/opus", t[0] - 3600, cost=0.5, tokens=100)
        u.record("claude/opus", t[0] - 6 * 3600, cost=9.0)         # outside the 5 h window
        self.assertEqual(u.used("claude/opus", "5h")["calls"], 1)
        self.assertAlmostEqual(u.used("claude/opus", "5h")["cost"], 0.5)
        self.assertAlmostEqual(u.pressure("claude/opus"), 0.25)     # 0.5 / 2.0 (family-level budget applies to the model)
        self.assertEqual(u.pressure("codex"), 0.0)                  # no budget -> never pressured

    def test_budget_exact_name_beats_family(self):
        u = UsageTracker({"claude": {"calls_24h": 1000}, "claude/fable": {"calls_24h": 2}})
        for _ in range(2):
            u.record("claude/fable", time.time())
        self.assertGreaterEqual(u.pressure("claude/fable"), 1.0)
        self.assertLess(u.pressure("claude/opus"), 1.0)

    def test_persists_across_restarts_and_ignores_old_rows(self):
        path = os.path.join(tempfile.mkdtemp(), "usage.jsonl")
        UsageTracker(path=path).record("groq/x", time.time(), tokens=500)
        old = json.dumps({"p": "groq/x", "ts": time.time() - 30 * 86400, "cost": 0, "tok": 999})
        open(path, "a").write(old + "\n{garbage\n")
        u = UsageTracker(path=path)
        self.assertEqual(u.used("groq/x", "24h")["tokens"], 500)
        self.assertEqual(len(u.rows), 1)                                # the 30-day-old row was not kept in memory at all

    def test_a_row_inside_the_keep_window_is_loaded_and_one_outside_is_not(self):
        path = os.path.join(tempfile.mkdtemp(), "usage.jsonl")
        now = time.time()
        with open(path, "w") as f:
            for days in (1, 7.5, 8.5, 20):
                f.write(json.dumps({"p": "groq/x", "ts": now - days * 86400, "cost": 0, "tok": 1}) + "\n")
        self.assertEqual(sorted(round((now - r[0]) / 86400, 1) for r in UsageTracker(path=path, clock=lambda: now).rows), [1.0, 7.5])

    def test_a_nonsense_budget_key_is_ignored_not_a_crash(self):
        u = UsageTracker({"claude": {"calls_2h": 1, "calls_foo": 1, "bogus": 3, "calls_24h": 0}})
        u.record("claude/opus", time.time())
        self.assertEqual(u.pressure("claude/opus"), 0.0)                # unknown windows and a zero limit mean "no budget"
        u2 = UsageTracker({"claude": {"calls_24h": 4, "calls_2h": 1}})
        u2.record("claude/opus", time.time())
        self.assertAlmostEqual(u2.pressure("claude/opus"), 0.25)        # the valid key still counts

    def test_router_records_every_successful_call(self):
        u = UsageTracker()
        a = P("a"); a.last_meta = {"cost_usd": 0.02, "prompt_tokens": 40, "completion_tokens": 10}
        Router([a], usage=u).call("planner", [])
        self.assertEqual(u.used("a", "24h")["calls"], 1); self.assertAlmostEqual(u.used("a", "24h")["cost"], 0.02)
        self.assertEqual(u.used("a", "24h")["tokens"], 50)


class ResetParsing(unittest.TestCase):
    def test_common_limit_messages(self):
        now = time.mktime((2026, 10, 2, 14, 0, 0, 0, 0, -1))
        self.assertEqual(parse_reset_seconds("Please try again in 90 seconds", now), 90)
        self.assertEqual(parse_reset_seconds("rate limited, retry in 2 hours", now), 7200)
        self.assertEqual(parse_reset_seconds("try again in 1.5s", now), 1.5)
        self.assertEqual(parse_reset_seconds("Claude usage limit reached. Your limit will reset at 3pm", now), 3600)
        self.assertEqual(parse_reset_seconds("resets at 9:30 am", now), 19.5 * 3600)   # tomorrow morning
        self.assertIsNone(parse_reset_seconds("something unrelated", now))

    def test_cli_limit_error_sets_cooldown_from_the_message(self):
        t = [1000.0]
        a = P("claude", [RateLimited("usage limit reached, try again in 2 hours")]); b = P("groq")
        r = Router([a, b], {"planner": ["claude", "groq"]}, cooldown_s=900, clock=lambda: t[0])
        r.call("planner", [])
        self.assertAlmostEqual(r.cooling["claude"] - 1000.0, 7200.0)


class Frugal(unittest.TestCase):
    def providers(self):
        return {"local": P("ollama/qwen", privacy="local", tier="local"), "free": P("groq/gpt-oss", tier="free"),
                "fast": P("claude/sonnet", tier="fast"), "bal": P("claude/opus", tier="balanced"),
                "best": P("claude/fable", tier="best")}

    def router(self, ps, reg=None, **kw):
        return Router(list(ps.values()), {"planner": ["claude", "groq", "ollama"]}, reg, "frugal", **kw)

    def names(self, r, role="planner"):
        return [p.card.name for p in r.eligible(role, "project")]

    def test_cost_class_ladder(self):
        ps = self.providers()
        self.assertEqual([cost_class(ps[k]) for k in ("local", "free", "fast", "bal", "best")], [0, 1, 2, 2, 2])

    def test_unmeasured_frugal_goes_local_then_free_then_cheapest_claude(self):
        self.assertEqual(self.names(self.router(self.providers())),
                         ["ollama/qwen", "groq/gpt-oss", "claude/sonnet", "claude/opus", "claude/fable"])

    def test_measured_weak_model_is_skipped_below_min_quality_and_far_below_the_best(self):
        ps = self.providers(); reg = Registry()
        for n, s in (("ollama/qwen", 0.40), ("groq/gpt-oss", 0.88), ("claude/sonnet", 0.90), ("claude/opus", 0.95), ("claude/fable", 0.97)):
            reg.record(n, "planning", s, 20, 5, cost_per_task=0.0)
        order = self.names(self.router(ps, reg, min_quality=0.6, slack=0.25))
        self.assertEqual(order[0], "groq/gpt-oss")            # cheapest model that is good enough
        self.assertNotIn("ollama/qwen", order[:3])             # 0.40 < min_quality: demoted to last resort
        self.assertEqual(order[-1], "ollama/qwen")

    def test_slack_demotes_models_far_below_the_best_even_if_cheap(self):
        ps = self.providers(); reg = Registry()
        for n, s in (("ollama/qwen", 0.65), ("groq/gpt-oss", 0.70), ("claude/sonnet", 0.90), ("claude/opus", 0.95), ("claude/fable", 0.97)):
            reg.record(n, "planning", s, 20, 5)
        order = self.names(self.router(ps, reg, min_quality=0.6, slack=0.20))   # 0.97-0.20 = 0.77 floor
        self.assertEqual(order[0], "claude/sonnet")            # local/free are cheap but too far behind the best

    def test_exhausted_provider_moves_to_the_back(self):
        ps = self.providers(); u = UsageTracker({"groq": {"calls_24h": 1}})
        u.record("groq/gpt-oss", time.time())
        order = self.names(self.router(ps, usage=u))
        self.assertEqual(order[-1], "groq/gpt-oss"); self.assertEqual(order[0], "ollama/qwen")

    def test_critic_is_not_frugal_it_prefers_the_strongest(self):
        ps = self.providers(); r = Router(list(ps.values()), {"critic": ["claude"]}, None, "frugal",
                                           role_tiers={"critic": ["best", "balanced", "fast"]})
        self.assertEqual(self.names(r, "critic")[0], "claude/fable")

    def test_private_goal_keeps_only_local_even_when_frugal(self):
        r = self.router(self.providers())
        self.assertEqual([p.card.name for p in r.eligible("planner", "private")], ["ollama/qwen"])

    def test_open_goal_adds_free_open_tiers_in_the_cheap_class(self):
        ps = self.providers(); ps["gem"] = P("gemini/flash", privacy="open", tier="free")
        r = self.router(ps)
        self.assertNotIn("gemini/flash", self.names(r)); self.assertIn("gemini/flash", [p.card.name for p in r.eligible("planner", "open")])


BAD = plan([W("s1", "a.txt", "wrong")], [{"type": "file_contains", "path": "a.txt", "text": "RIGHT"}])
GOOD = plan([W("s1", "a.txt", "RIGHT")], [{"type": "file_contains", "path": "a.txt", "text": "RIGHT"}])


class Escalation(unittest.TestCase):
    def mk(self, cheap, strong, **kw):
        ws, log = tempfile.mkdtemp(), EventLog()
        a, b = P("cheap", cheap, tier="free"), P("strong", strong, tier="best")
        r = Router([a, b], {"planner": ["cheap", "strong"]}, None, "config")
        kw.setdefault("critic", False)
        return Executive(ws, log, r, **kw), ws, log, a, b

    def test_failed_verification_escalates_to_a_stronger_model_automatically(self):
        ex, ws, log, a, b = self.mk([BAD], [GOOD])
        r = ex.run("write RIGHT into a.txt")
        self.assertEqual(r.status, VERIFIED)
        self.assertEqual((len(a.calls), len(b.calls)), (1, 1))
        esc = log.all(type_="escalation")
        self.assertEqual(len(esc), 1); self.assertEqual(esc[0].payload["from"], "cheap")
        self.assertEqual(open(os.path.join(ws, "a.txt")).read(), "RIGHT")      # rolled back, then redone correctly
        self.assertEqual(log.verify_chain(), (True, None))

    def test_the_stronger_model_is_told_why_the_cheap_one_failed(self):
        ex, ws, log, a, b = self.mk([BAD], [GOOD]); ex.run("x")
        self.assertIn("RIGHT", json.dumps(b.calls[0][1]))                       # failure reason (our own words) reaches it
        self.assertIn("failed", json.dumps(b.calls[0][1]).lower())

    def test_guard_denial_never_escalates(self):
        evil = plan([{"id": "s1", "tool": "shell.run", "args": {"cmd": "rm -rf ."}, "verify": {"type": "none"}, "deps": []}], [{"type": "none"}])
        ex, ws, log, a, b = self.mk([evil], [GOOD])
        self.assertEqual(ex.run("x").status, FAILED)
        self.assertEqual(len(b.calls), 0)                                       # a denied action is not a reason to ask a smarter model to try harder

    def test_escalation_can_be_turned_off(self):
        ex, ws, log, a, b = self.mk([BAD], [GOOD], escalate=False)
        self.assertEqual(ex.run("x").status, FAILED); self.assertEqual(len(b.calls), 0)

    def test_escalation_is_bounded_and_does_not_reuse_a_tried_model(self):
        c = P("third", [BAD], tier="best")
        ws, log = tempfile.mkdtemp(), EventLog()
        a, b = P("cheap", [BAD]), P("strong", [BAD])
        r = Router([a, b, c], {"planner": ["cheap", "strong", "third"]}, None, "config")
        res = Executive(ws, log, r, max_escalations=1, critic=False).run("x")
        self.assertEqual(res.status, FAILED)
        self.assertEqual((len(a.calls), len(b.calls), len(c.calls)), (1, 1, 0))

    def test_invalid_plan_retry_goes_to_a_different_model(self):
        ex, ws, log, a, b = self.mk(["not json"], [GOOD])
        self.assertEqual(ex.run("x").status, VERIFIED)
        self.assertEqual((len(a.calls), len(b.calls)), (1, 1))                  # second attempt used the other model

    def test_single_provider_behaves_as_before(self):
        ws, log = tempfile.mkdtemp(), EventLog()
        a = P("only", [BAD])
        self.assertEqual(Executive(ws, log, Router([a])).run("x").status, FAILED)
        self.assertEqual(len(a.calls), 1)

    def test_free_tier_limit_mid_goal_falls_over_to_the_next_provider(self):
        ws, log = tempfile.mkdtemp(), EventLog()
        a = P("groq/x", [RateLimited("daily quota", retry_after=3600)], tier="free"); b = P("claude/y", [GOOD], tier="balanced")
        r = Router([a, b], {"planner": ["groq", "claude"]}, None, "config")
        self.assertEqual(Executive(ws, log, r, critic=False).run("x").status, VERIFIED)
        self.assertGreater(r.cooling["groq/x"], time.time() + 3000)


if __name__ == "__main__":
    unittest.main()
