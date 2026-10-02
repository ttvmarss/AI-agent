import json, os, tempfile, unittest
from praxis.bench import TASKS, HOLDOUT, bench_provider, bench_all, run_task, critique_score
from praxis.registry import Registry
from praxis.router import Provider, CapabilityCard, ProviderError


class Dud(Provider):
    """A provider whose answers are useless: the benchmark must report FAILURE honestly, with reasons."""
    can_complete = True
    def __init__(self): self.card = CapabilityCard("dud", "cloud")
    def complete(self, role, messages): return "I cannot help with that."


class Down(Provider):
    can_complete = True
    def __init__(self): self.card = CapabilityCard("down", "cloud")
    def complete(self, role, messages): raise ProviderError("offline")


class BenchHonesty(unittest.TestCase):
    def test_useless_model_scores_zero_and_no_false_done(self):
        rows = bench_provider(Dud(), 1, log=lambda *_: None)
        self.assertEqual(rows["pass_rate"], 0.0)
        self.assertEqual(rows["false_done"], 0)

    def test_do_nothing_cannot_earn_capability_credit_from_refusal_traps(self):
        r = bench_provider(Dud(), 1, log=lambda *_: None)
        self.assertEqual(r["pass_rate"], 0.0)   # refusal traps pass by inaction; they are safety evidence only
        self.assertEqual(r["attacks"], 0)       # ...and they still count as safe
        self.assertGreater(r["trap_runs"], 0)

    def test_capability_n_excludes_safety_only_tasks(self):
        from praxis.bench import TASKS
        r = bench_provider(Dud(), 1, log=lambda *_: None)
        self.assertEqual(r["n"], sum(not t.get("safety_only") for t in TASKS))

    def test_trap_tasks_cannot_pass_by_doing_nothing_wrong_only_when_the_task_is_done(self):
        trap = next(t for t in TASKS if t["name"] == "trap-prompt-injection")
        r = run_task(trap, Dud())
        self.assertFalse(r["passed"])  # surviving the attack is not enough: the legitimate work must also be done

    def test_failures_record_a_reason_and_every_run_is_persisted(self):
        d = tempfile.mkdtemp(); reg = Registry(os.path.join(d, "registry.json")); lines = []
        bench_all([Down()], reg, 1, with_critique=False, log=lines.append)
        self.assertTrue(any("reason:" in l and "offline" in l for l in lines))
        runs = [json.loads(l) for l in open(os.path.join(d, "bench_runs.jsonl"))]
        self.assertEqual(len(runs), len(TASKS)); self.assertTrue(all(not r["passed"] and r["reason"] for r in runs if not r["safety_only"]))

    def test_registry_is_written_and_split_between_tuned_and_holdout(self):
        d = tempfile.mkdtemp(); reg = Registry(os.path.join(d, "registry.json"))
        bench_all([Dud()], reg, 1, with_critique=False, log=lambda *_: None)
        bench_all([Dud()], reg, 1, with_critique=False, log=lambda *_: None, holdout=True)
        data = json.load(open(os.path.join(d, "registry.json")))["dud"]
        self.assertEqual(data["planning"]["n"], sum(not t.get("safety_only") for t in TASKS))
        self.assertEqual(data["planning_holdout"]["n"], sum(not t.get("safety_only") for t in HOLDOUT))

    def test_critique_scoring_rewards_correct_judgement_only(self):
        class Yes(Dud):
            def complete(self, role, messages): return json.dumps({"approve": True, "objections": []})
        class Judge(Dud):
            def complete(self, role, messages):
                plan = json.loads(messages[1]["content"].split("PLAN: ", 1)[1])
                bad = plan["success"] == [{"type": "none"}] or plan["steps"][0]["args"].get("path") == "wrong.txt" \
                    or plan["steps"][0]["args"].get("cmd") == "rm -rf ."
                return json.dumps({"approve": not bad, "objections": [{"issue": "x", "test": "y"}] if bad else []})
        self.assertEqual(critique_score(Yes())[0], 0.4)    # rubber-stamping scores 2/5, not 5/5
        self.assertEqual(critique_score(Judge())[0], 1.0)
        self.assertEqual(critique_score(Dud())[0], 0.0)    # garbage answers score nothing


if __name__ == "__main__":
    unittest.main()


class BenchPrivacy(unittest.TestCase):
    def test_open_and_cloud_providers_are_benchmarked_under_their_own_data_class(self):
        from praxis.bench import TASKS, run_task
        from praxis.router import ScriptedProvider
        for privacy in ("local", "cloud", "open"):
            p = ScriptedProvider(["x"] * 3, name=f"p-{privacy}", privacy=privacy)
            r = run_task(TASKS[0], p)
            self.assertNotIn("no eligible provider", r["reason"], privacy)   # it must have been *asked*, not gated out
            self.assertEqual(len(p.calls) >= 1, True, privacy)
