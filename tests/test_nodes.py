import time, types, unittest
from praxis.desktop.nodes import failover_chain, provider_nodes
from praxis.registry import Registry
from praxis.router import Router, ScriptedProvider
from praxis.usage import UsageTracker


def P(name, privacy="cloud", tier=None, can_complete=True):
    p = ScriptedProvider(["x"] * 3, name=name, privacy=privacy); p.tier = tier; p.can_complete = can_complete; return p


def mkstack(providers, usage=None, registry=None, strategy="frugal"):
    reg = registry or Registry()
    return types.SimpleNamespace(providers=providers, usage=usage or UsageTracker(), registry=reg,
                                 router=Router(providers, {"planner": ["claude", "groq", "ollama"]}, reg, strategy),
                                 skipped={"codex": "not installed"})


class Nodes(unittest.TestCase):
    def setUp(self):
        self.ps = [P("claude/opus", tier="balanced"), P("claude/fable", tier="best"), P("groq/gpt-oss", tier="free"),
                   P("ollama/qwen", privacy="local", tier="local"), P("gemini/flash", privacy="open", tier="free")]

    def test_one_node_per_family_ordered_by_the_frugal_ladder(self):
        nodes = provider_nodes(mkstack(self.ps), "project")
        self.assertEqual([n["family"] for n in nodes], ["ollama", "groq", "gemini", "claude"])   # local, free, free(open), subscription
        self.assertEqual([m["name"] for m in nodes[-1]["models"]], ["claude/opus", "claude/fable"])
        self.assertEqual(nodes[0]["cost_class"], 0); self.assertEqual(nodes[-1]["cost_class"], 2)

    def test_data_class_blocks_what_it_must(self):
        st = mkstack(self.ps)
        blocked = lambda dc: {n["family"] for n in provider_nodes(st, dc) if n["blocked"]}
        self.assertEqual(blocked("private"), {"groq", "gemini", "claude"})
        self.assertEqual(blocked("project"), {"gemini"})
        self.assertEqual(blocked("open"), set())

    def test_pressure_is_the_worst_across_the_family_and_cooldown_is_all_or_nothing(self):
        u = UsageTracker({"claude": {"calls_24h": 4}}); u.record("claude/opus", time.time()); u.record("claude/opus", time.time())
        st = mkstack(self.ps, usage=u)
        claude = next(n for n in provider_nodes(st, "project") if n["family"] == "claude")
        self.assertAlmostEqual(claude["pressure"], 0.5)
        st.router.cooling["claude/opus"] = time.time() + 600
        self.assertEqual(next(n for n in provider_nodes(st, "project") if n["family"] == "claude")["cooling_s"], 0)  # fable still up
        st.router.cooling["claude/fable"] = time.time() + 300
        c = next(n for n in provider_nodes(st, "project") if n["family"] == "claude")
        self.assertTrue(250 <= c["cooling_s"] <= 305)                                          # resting until the earliest return

    def test_one_models_own_budget_makes_the_whole_family_node_show_the_pressure(self):
        u = UsageTracker({"claude/fable": {"calls_24h": 2}})              # an EXACT-model budget: opus has none
        for _ in range(2):
            u.record("claude/fable", time.time())
        claude = next(n for n in provider_nodes(mkstack(self.ps, usage=u), "project") if n["family"] == "claude")
        self.assertGreaterEqual(claude["pressure"], 1.0)                  # the node warns about its most-spent model, not the average

    def test_a_family_with_no_resting_member_never_shows_a_clock(self):
        st = mkstack(self.ps)
        self.assertEqual(next(n for n in provider_nodes(st, "project") if n["family"] == "claude")["cooling_s"], 0)
        for name, secs in (("claude/opus", 900), ("claude/fable", 300)):
            st.router.cooling[name] = time.time() + secs
        c = next(n for n in provider_nodes(st, "project") if n["family"] == "claude")
        self.assertTrue(250 <= c["cooling_s"] <= 305)

    def test_measured_scores_and_costs_surface(self):
        reg = Registry(); reg.record("groq/gpt-oss", "planning", 0.88, 20, 3, cost_per_task=0.0, tokens_per_s=300)
        n = next(n for n in provider_nodes(mkstack(self.ps, registry=reg), "project") if n["family"] == "groq")
        self.assertEqual(n["models"][0]["score"], 0.88); self.assertEqual(n["models"][0]["tps"], 300)

    def test_delegate_only_providers_are_marked(self):
        st = mkstack(self.ps + [P("devin", tier="best", can_complete=False)])
        d = next(n for n in provider_nodes(st, "project") if n["family"] == "devin")
        self.assertTrue(d["delegate_only"])

    def test_failover_chain_is_what_the_router_would_try_next(self):
        st = mkstack(self.ps)
        self.assertEqual(failover_chain(st, "project"), ["ollama/qwen", "groq/gpt-oss", "claude/opus", "claude/fable"])
        self.assertEqual(failover_chain(st, "private"), ["ollama/qwen"])
        self.assertEqual(failover_chain(st, "open")[:3], ["ollama/qwen", "groq/gpt-oss", "gemini/flash"])


if __name__ == "__main__":
    unittest.main()
