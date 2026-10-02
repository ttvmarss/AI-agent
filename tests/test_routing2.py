import unittest
from praxis.registry import Registry
from praxis.router import ModelUnavailable, ProviderError, Router, ScriptedProvider, family


def P(name, answers, tier=None, privacy="cloud"):
    p = ScriptedProvider(answers, name=name, privacy=privacy)
    p.tier = tier
    return p


TIERS = {"planner": ["balanced", "best", "fast"], "critic": ["best", "balanced", "fast"]}


class Tiers(unittest.TestCase):
    def mk(self, **kw):
        fable, opus, sonnet = P("claude/fable", ["F"] * 5, "best"), P("claude/opus", ["O"] * 5, "balanced"), \
            P("claude/sonnet", ["S"] * 5, "fast")
        return Router([fable, opus, sonnet], {"planner": ["claude"], "critic": ["claude"]}, role_tiers=TIERS, **kw), (fable, opus, sonnet)

    def test_unmeasured_planner_uses_balanced_critic_uses_best(self):
        r, _ = self.mk()
        self.assertEqual(r.call("planner", []), "O")   # not the 67x-cost model for routine planning
        self.assertEqual(r.call("critic", []), "F")    # adversarial review is short and high-leverage

    def test_family_helper(self):
        self.assertEqual(family("claude/opus"), "claude"); self.assertEqual(family("codex"), "codex")

    def test_unavailable_model_falls_back_within_family_and_is_remembered(self):
        fable = P("claude/fable", [ModelUnavailable("unrecognized_model")], "best")
        opus = P("claude/opus", ["O", "O2"], "balanced")
        t = [0.0]
        r = Router([fable, opus], {"critic": ["claude"]}, role_tiers=TIERS, clock=lambda: t[0])
        self.assertEqual(r.call("critic", []), "O")
        self.assertEqual(r.call("critic", []), "O2")        # fable is not even tried again
        self.assertEqual(len(fable.calls), 1)
        t[0] += 7 * 3600
        fable.queue.append("F-back")                         # long cooldown eventually expires (model may be rolled out)
        self.assertEqual(r.call("critic", []), "F-back")


class CostAware(unittest.TestCase):
    def reg(self, rows):
        reg = Registry()
        for name, score, cost in rows:
            reg.record(name, "planning", score, 12, 5.0, cost_per_task=cost)
        return reg

    def test_cheapest_within_epsilon_of_the_best_wins(self):
        reg = self.reg([("claude/fable", 0.96, 0.10), ("claude/opus", 0.94, 0.016), ("claude/sonnet", 0.80, 0.0015)])
        ps = [P("claude/fable", ["F"]), P("claude/opus", ["O"]), P("claude/sonnet", ["S"])]
        self.assertEqual(Router(ps, {"planner": ["claude"]}, reg, "auto").call("planner", []), "O")

    def test_clearly_better_expensive_model_wins_when_gap_exceeds_epsilon(self):
        reg = self.reg([("claude/fable", 0.96, 0.10), ("claude/opus", 0.80, 0.016)])
        ps = [P("claude/fable", ["F"]), P("claude/opus", ["O"])]
        self.assertEqual(Router(ps, {"planner": ["claude"]}, reg, "auto").call("planner", []), "F")

    def test_free_local_model_preferred_when_as_good(self):
        reg = self.reg([("claude/opus", 0.93, 0.016), ("ollama/qwen3.6:35b-a3b", 0.92, 0.0)])
        ps = [P("claude/opus", ["O"]), P("ollama/qwen3.6:35b-a3b", ["L"], privacy="local")]
        self.assertEqual(Router(ps, {"planner": ["claude", "ollama"]}, reg, "auto").call("planner", []), "L")

    def test_partially_measured_falls_back_to_configured_order(self):
        reg = self.reg([("claude/fable", 0.99, 0.10)])  # opus unmeasured -> do not trust a lopsided comparison
        ps = [P("claude/fable", ["F"], "best"), P("claude/opus", ["O"], "balanced")]
        r = Router(ps, {"planner": ["claude"]}, reg, "auto", role_tiers=TIERS)
        self.assertEqual(r.call("planner", []), "O")


class FamilyDiversity(unittest.TestCase):
    def test_critic_exclusion_is_by_family_not_exact_name(self):
        a, b = P("claude/opus", ["A"]), P("claude/fable", ["B"])
        r = Router([a, b], {"critic": ["claude"]})
        self.assertEqual(r.eligible("critic", "project", exclude=("claude",)), [])  # same vendor family != second opinion
        c = P("codex", ["C"])
        r2 = Router([a, c], {"critic": ["claude", "codex"]})
        self.assertEqual([p.card.name for p in r2.eligible("critic", "project", exclude=("claude",))], ["codex"])


if __name__ == "__main__":
    unittest.main()
