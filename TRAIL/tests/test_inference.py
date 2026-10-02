import hashlib
import io
import os
import shutil
import tempfile
import unittest

import torch
from safetensors.torch import load_file, save_file

from tests.helpers import prepared
from trail.config import load_config
from trail.evaluation.suite import run_suite
from trail.inference.chat import chat_loop
from trail.inference.engine import Engine
from trail.inference.sampling import sample_next
from trail.tokenizer.bpe import EOS
from trail.tokenizer.template import encode_training_example
from trail.training import checkpoint as ck
from trail.training.instruct import run_instruct
from trail.training.instruct_data import EVAL_IDENTITY, IDENTITY, make_examples
from trail.training.trainer import Trainer


class Sampling(unittest.TestCase):
    def setUp(self):
        self.logits = torch.tensor([1.0, 3.0, 2.0, 0.5, -1.0])

    def test_greedy_and_topk1_agree(self):
        self.assertEqual(sample_next(self.logits, [], temperature=0), 1)
        self.assertEqual(sample_next(self.logits, [], temperature=1.0, top_k=1), 1)

    def test_seed_makes_sampling_reproducible(self):
        a = [sample_next(self.logits, [], 1.0, 0, 1.0, generator=torch.Generator().manual_seed(s)) for s in range(30)]
        b = [sample_next(self.logits, [], 1.0, 0, 1.0, generator=torch.Generator().manual_seed(s)) for s in range(30)]
        self.assertEqual(a, b); self.assertGreater(len(set(a)), 1)

    def test_top_p_and_top_k_restrict_the_choices(self):
        g = torch.Generator().manual_seed(0)
        seen = {sample_next(self.logits, [], 1.0, 2, 1.0, generator=g) for _ in range(200)}
        self.assertLessEqual(seen, {1, 2})
        seen = {sample_next(self.logits, [], 1.0, 0, 0.5, generator=g) for _ in range(200)}
        self.assertEqual(seen, {1})

    def test_repetition_penalty_discourages_seen_tokens(self):
        self.assertEqual(sample_next(self.logits, [], temperature=0), 1)
        self.assertNotEqual(sample_next(self.logits, [1], temperature=0, repetition_penalty=5.0), 1)


class Runtime(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.path, cls.cfg = prepared(cls.tmp, steps=30)
        Trainer(cls.cfg, resume=False).run()
        cls.base = ck.latest(cls.cfg.training["run_dir"])
        cls.eng = Engine.load(cls.base, "cpu")

    def test_generation_comes_from_the_checkpoint_weights(self):
        a = self.eng.generate("the quick", max_new_tokens=25, temperature=0)
        self.assertEqual(a, self.eng.generate("the quick", max_new_tokens=25, temperature=0))              # deterministic
        d = tempfile.mkdtemp(); c2 = os.path.join(d, "checkpoint_000001")
        shutil.copytree(self.base, c2)
        w = load_file(os.path.join(c2, "model.safetensors"))
        w["embed.weight"] = w["embed.weight"] + torch.randn_like(w["embed.weight"]) * 0.5               # damage the weights
        save_file(w, os.path.join(c2, "model.safetensors"))
        e2 = Engine.load(c2, "cpu")
        self.assertNotEqual(e2.fingerprint(), self.eng.fingerprint())
        self.assertNotEqual(e2.generate("the quick", max_new_tokens=25, temperature=0), a)                # different weights, different words

    def test_fingerprint_is_the_hash_of_the_weights_file(self):
        h = hashlib.sha256(open(os.path.join(self.base, "model.safetensors"), "rb").read()).hexdigest()
        self.assertEqual(self.eng.fingerprint(), h)

    def test_streaming_matches_blocking_and_is_seeded(self):
        s = "".join(self.eng.stream("def f(x):", max_new_tokens=30, temperature=0.9, seed=4))
        self.assertEqual(s, self.eng.generate("def f(x):", max_new_tokens=30, temperature=0.9, seed=4))
        self.assertNotEqual(s, self.eng.generate("def f(x):", max_new_tokens=30, temperature=0.9, seed=5))

    def test_cached_decoding_equals_recomputing_everything(self):
        ids = self.eng.tok.encode("the quick brown", bos=True)
        got = list(self.eng.stream_ids(ids, max_new_tokens=12, temperature=0, stop_ids=()))
        cur = list(ids)
        for _ in range(12):
            with torch.no_grad():
                nxt = int(self.eng.model(torch.tensor([cur]))["logits"][0, -1].argmax())
            cur.append(nxt)
        self.assertEqual(got, cur[len(ids):])

    def test_context_limit_stops_instead_of_crashing(self):
        out = list(self.eng.stream_ids([1] + [10] * 60, max_new_tokens=500, temperature=0, stop_ids=()))
        self.assertLessEqual(len(out) + 61, self.eng.cfg.max_seq_len + 1)
        list(self.eng.stream_ids([1] + [10] * 500, max_new_tokens=3, temperature=0))                      # over-long prompt is truncated

    def test_evaluation_suite_reports_every_measurement(self):
        r = run_suite(self.base, self.path, record=False, n_val=8, gen_tokens=20)
        for k in ("weights_sha256", "language_modeling", "token_efficiency", "generation", "latency", "reasoning", "coding", "peak_rss_mb"):
            self.assertIn(k, r)
        self.assertGreater(r["language_modeling"]["perplexity"], 1)
        self.assertEqual(r["reasoning"]["items"], 12)

    def test_base_chat_says_it_is_a_base_model(self):
        out = io.StringIO()
        chat_loop(self.base, inp=io.StringIO("the quick\n\n"), out=out, max_tokens=10, seed=1)
        self.assertIn("BASE checkpoint", out.getvalue()); self.assertIn("sha256", out.getvalue())


class Instruct(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.path, cls.cfg = prepared(cls.tmp, steps=20)
        Trainer(cls.cfg, resume=False).run()
        cls.base = ck.latest(cls.cfg.training["run_dir"])
        cls.out = os.path.join(cls.tmp, "instruct_run")
        cls.before = hashlib.sha256(open(os.path.join(cls.base, "model.safetensors"), "rb").read()).hexdigest()
        run_instruct(cls.base, cls.out, cls.path)

    def test_base_checkpoint_is_untouched_and_instruct_is_a_separate_lineage_entry(self):
        self.assertEqual(self.before, hashlib.sha256(open(os.path.join(self.base, "model.safetensors"), "rb").read()).hexdigest())
        e = Engine.load(self.out, "cpu")
        self.assertEqual(e.stage, "instruct")
        self.assertNotEqual(e.fingerprint(), self.before)
        self.assertIn("base_checkpoint_sha256", e.arch_meta); self.assertEqual(e.arch_meta["base_checkpoint_sha256"], self.before)

    def test_refuses_to_write_into_the_base_run(self):
        with self.assertRaises(ValueError):
            run_instruct(self.base, os.path.dirname(self.base), self.path)

    def test_loss_mask_covers_only_the_answer(self):
        e = Engine.load(self.base, "cpu")
        ids, mask = encode_training_example(e.tok, "sys", "hi there", "hello")
        self.assertEqual(ids[-1], EOS); self.assertEqual(sum(mask), len(e.tok.encode("hello")) + 1)
        self.assertTrue(all(m == 0 for m in mask[:len(ids) - sum(mask)]))

    def test_identity_data_is_honest_and_eval_prompts_are_held_out(self):
        ex = make_examples()
        text = " ".join(a for _, a in ex).lower()
        self.assertIn("trail project", text); self.assertIn("from scratch", text)
        for banned in ("i am chatgpt", "i am claude", "built by openai", "built by anthropic", "i am llama"):
            self.assertNotIn(banned, text)
        trained = {q for qs, _ in IDENTITY for q in qs}
        self.assertTrue(set(EVAL_IDENTITY).isdisjoint(trained))


if __name__ == "__main__":
    unittest.main()
