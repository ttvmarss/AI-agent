import json
import os
import shutil
import tempfile
import unittest

import torch
from safetensors.torch import load_file

from tests.helpers import prepared, tiny_config
from trail.config import load_config
from trail.training import checkpoint as ck
from trail.training.schedule import lr_at
from trail.training.trainer import Trainer


class Schedule(unittest.TestCase):
    def test_warmup_cosine_floor(self):
        f = lambda s: lr_at(s, 100, 1.0, 10, 0.1, "cosine")
        self.assertAlmostEqual(f(0), 0.1); self.assertAlmostEqual(f(9), 1.0)
        self.assertAlmostEqual(f(10), 1.0, places=6); self.assertAlmostEqual(f(100), 0.1, places=6)
        self.assertTrue(all(f(s) >= f(s + 1) for s in range(10, 99)))
        self.assertEqual(lr_at(50, 100, 2.0, 0, 0.1, "constant"), 2.0)
        self.assertAlmostEqual(lr_at(100, 100, 1.0, 0, 0.5, "linear"), 0.5)
        with self.assertRaises(ValueError): lr_at(50, 100, 1.0, 0, 0.1, "bogus")


class Training(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.path, cls.cfg = prepared(cls.tmp, steps=40)
        cls.rundir = cls.cfg.training["run_dir"]
        Trainer(cls.cfg, resume=False).run()

    def test_loss_decreases_and_validation_runs(self):
        rows = [json.loads(l) for l in open(os.path.join(self.rundir, "metrics.jsonl"))]
        first, last = rows[0]["loss"], rows[-1]["loss"]
        self.assertLess(last, first - 0.5, (first, last))
        self.assertTrue(any("val_loss" in r for r in rows))
        r = rows[-1]
        for k in ("step", "tokens", "loss", "lr", "grad_norm", "tok_s", "mem_mb"):
            self.assertIn(k, r)

    def test_checkpoint_describes_exactly_what_made_it(self):
        c = ck.latest(self.rundir)
        for f in ("model.safetensors", "optimizer.pt", "scheduler.pt", "trainer_state.json", "architecture.json", "metrics.json", "dataset_manifest.json", "tokenizer/tokenizer.json", "COMPLETE"):
            self.assertTrue(os.path.exists(os.path.join(c, f)), f)
        arch = json.load(open(os.path.join(c, "architecture.json")))
        self.assertEqual(arch["architecture"], "TCE-G1"); self.assertEqual(arch["trail"]["generation"], 1)
        st = json.load(open(os.path.join(c, "trainer_state.json")))
        self.assertEqual(st["step"], 40); self.assertEqual(st["config_digest"], self.cfg.digest())

    def test_reload_gives_identical_weights_and_refuses_overwrite_and_incomplete(self):
        c = ck.latest(self.rundir)
        model, _ = ck.load_model(c)
        saved = load_file(os.path.join(c, "model.safetensors"))
        self.assertTrue(all(torch.equal(saved[k], v) for k, v in model.state_dict().items()))
        with self.assertRaises(FileExistsError):
            ck.save(self.rundir, 40, model, None, {"step": 40}, model.cfg, None, None, {})
        os.makedirs(os.path.join(self.rundir, "checkpoint_999999"))                  # no COMPLETE marker: a crashed write
        self.assertNotIn("999999", ck.latest(self.rundir)); shutil.rmtree(os.path.join(self.rundir, "checkpoint_999999"))

    def test_checkpoint_rotation_keeps_only_the_newest(self):
        d = tempfile.mkdtemp()
        model, mc = ck.load_model(ck.latest(self.rundir))
        for s in (1, 2, 3, 4):
            ck.save(d, s, model, None, {"step": s}, mc, None, None, {}, keep=2)
        self.assertEqual([os.path.basename(x) for x in ck.checkpoint_dirs(d)], ["checkpoint_000003", "checkpoint_000004"])

    def test_interrupted_run_resumes_bit_for_bit(self):
        full = self.cfg
        d1 = tempfile.mkdtemp(); d2 = tempfile.mkdtemp()
        shutil.copytree(os.path.join(self.tmp, "processed"), os.path.join(d1, "processed")); shutil.copytree(os.path.join(self.tmp, "processed"), os.path.join(d2, "processed"))
        ov = lambda d: {"data": {"output": os.path.join(d, "processed")}, "training": {"run_dir": os.path.join(d, "run")}}
        c1 = load_config(self.path, ov(d1)); c2 = load_config(self.path, ov(d2))
        Trainer(c1, resume=False).run()                                               # straight to 40
        Trainer(c2, resume=False, max_steps=20).run()                                 # interrupted at 20 ...
        self.assertEqual(os.path.basename(ck.latest(c2.training["run_dir"])), "checkpoint_000020")
        Trainer(c2).run()                                                             # ... and resumed
        a = load_file(os.path.join(ck.latest(c1.training["run_dir"]), "model.safetensors"))
        b = load_file(os.path.join(ck.latest(c2.training["run_dir"]), "model.safetensors"))
        self.assertEqual(max((a[k] - b[k]).abs().max().item() for k in a), 0.0)

    def test_resuming_with_a_different_architecture_is_refused(self):
        other = load_config(self.path, {"model": {"d_model": 64}})
        with self.assertRaises(ValueError):
            Trainer(other).run()

    def test_training_without_prepared_data_says_what_to_do(self):
        d = tempfile.mkdtemp()
        cfg = load_config(self.path, {"data": {"output": os.path.join(d, "nothing")}, "training": {"run_dir": os.path.join(d, "r")}})
        with self.assertRaises(FileNotFoundError):
            Trainer(cfg).run()


if __name__ == "__main__":
    unittest.main()
