import unittest

import torch

from trail.model import TCEG1, ModelConfig
from trail.model import registry


def small(**kw):
    d = dict(vocab_size=128, n_layers=2, d_model=32, n_heads=4, n_kv_heads=2, max_seq_len=48)
    d.update(kw)
    return ModelConfig(**d).validate()


class Model(unittest.TestCase):
    def setUp(self):
        torch.manual_seed(0)
        self.m = TCEG1(small()).eval()

    def test_shapes_and_loss_near_log_vocab_at_init(self):
        ids = torch.randint(0, 128, (3, 20))
        out = self.m(ids[:, :-1], ids[:, 1:])
        self.assertEqual(out["logits"].shape, (3, 19, 128))
        self.assertAlmostEqual(out["loss"].item(), torch.log(torch.tensor(128.0)).item(), delta=0.5)

    def test_causality(self):
        a = torch.randint(0, 128, (2, 30)); b = a.clone(); b[:, 20:] = (b[:, 20:] + 1) % 128
        with torch.no_grad():
            self.assertEqual((self.m(a)["logits"][:, :20] - self.m(b)["logits"][:, :20]).abs().max().item(), 0.0)

    def test_kv_cache_matches_full_forward_for_prefill_chunk_and_decode(self):
        ids = torch.randint(0, 128, (2, 36))
        with torch.no_grad():
            full = self.m(ids)["logits"]
            c = self.m.new_caches(2)
            parts = [self.m(ids[:, :20], caches=c, start=0)["logits"], self.m(ids[:, 20:26], caches=c, start=20)["logits"]]
            parts += [self.m(ids[:, t:t + 1], caches=c, start=t)["logits"] for t in range(26, 36)]
        self.assertLess((torch.cat(parts, 1) - full).abs().max().item(), 1e-4)

    def test_cache_overflow_is_an_error_not_corruption(self):
        c = self.m.new_caches(1)
        with self.assertRaises(ValueError):
            self.m(torch.zeros(1, 49, dtype=torch.long), caches=c)

    def test_gqa_mha_mqa_all_work_and_gqa_shrinks_the_cache(self):
        for kv in (4, 2, 1):
            m = TCEG1(small(n_kv_heads=kv)).eval()
            self.assertEqual(m(torch.zeros(1, 5, dtype=torch.long))["logits"].shape, (1, 5, 128))
        self.assertLess(TCEG1(small(n_kv_heads=1)).num_parameters(), TCEG1(small(n_kv_heads=4)).num_parameters())

    def test_parameter_count_matches_the_formula(self):
        c = small()
        h = c.ffn_hidden
        per_layer = 2 * c.d_model + c.d_model * (c.n_heads + 2 * c.n_kv_heads) * c.head_dim + c.n_heads * c.head_dim * c.d_model + 3 * c.d_model * h
        expect = c.vocab_size * c.d_model + c.n_layers * per_layer + c.d_model
        self.assertEqual(TCEG1(c).num_parameters(), expect)

    def test_untied_head_adds_parameters(self):
        self.assertEqual(TCEG1(small(tie_embeddings=False)).num_parameters() - TCEG1(small()).num_parameters(), 128 * 32)

    def test_ignore_index_masks_the_loss(self):
        ids = torch.randint(0, 128, (2, 10)); t = ids.clone(); t[:, :5] = -100
        a = self.m(ids, t)["loss"].item()
        t2 = ids.clone()
        self.assertNotAlmostEqual(a, self.m(ids, t2)["loss"].item(), places=4)

    def test_gradient_checkpointing_gives_the_same_gradients(self):
        ids = torch.randint(0, 128, (2, 12))
        grads = []
        for gc in (False, True):
            torch.manual_seed(3)
            m = TCEG1(small(gradient_checkpointing=gc)).train()
            m(ids, ids)["loss"].backward()
            grads.append(m.blocks[0].attn.q_proj.weight.grad.clone())
        self.assertLess((grads[0] - grads[1]).abs().max().item(), 1e-6)

    def test_config_validation_and_unknown_keys(self):
        with self.assertRaises(ValueError): ModelConfig(d_model=30, n_heads=4).validate()
        with self.assertRaises(ValueError): ModelConfig(n_heads=6, n_kv_heads=4).validate()
        with self.assertRaises(ValueError): ModelConfig.from_dict({"bogus": 1})
        with self.assertRaises(ValueError): ModelConfig.from_dict({"architecture": "other"})

    def test_components_are_swappable_and_unbuilt_futures_refuse_honestly(self):
        self.assertIn("swiglu", registry.available()["ffn"])
        with self.assertRaises(NotImplementedError):
            TCEG1(small(components={"norm": "rmsnorm", "position": "rope", "attention": "gqa", "ffn": "moe", "memory": "none", "router": "none"}))
        with self.assertRaises(NotImplementedError):
            TCEG1(small(components={"norm": "rmsnorm", "position": "rope", "attention": "gqa", "ffn": "swiglu", "memory": "fabric", "router": "none"}))
        with self.assertRaises(ValueError):
            TCEG1(small(components={"norm": "nope", "position": "rope", "attention": "gqa", "ffn": "swiglu", "memory": "none", "router": "none"}))

    def test_initialisation_is_random_and_seeded(self):
        torch.manual_seed(1); a = TCEG1(small()).embed.weight.clone()
        torch.manual_seed(2); b = TCEG1(small()).embed.weight.clone()
        torch.manual_seed(1); c = TCEG1(small()).embed.weight.clone()
        self.assertFalse(torch.equal(a, b)); self.assertTrue(torch.equal(a, c))
        self.assertAlmostEqual(a.std().item(), 0.02, delta=0.005)


if __name__ == "__main__":
    unittest.main()
