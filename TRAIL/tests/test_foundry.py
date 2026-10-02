import json
import os
import tempfile
import unittest

import numpy as np

from trail.data_foundry import curriculum, dedup, normalize, pipeline, quality, safety, tagging
from trail.data_foundry.mixer import TokenStreams
from trail.tokenizer.bpe import Tokenizer, EOS
from tests.helpers import prepared

LONG = "This is a perfectly ordinary paragraph of english text about rivers and bridges. " * 8


class Stages(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(normalize.normalize("a\r\nb\rc\x00d  \n\n\n\n\n\ne"), "a\nb\ncd\n\n\n\ne\n".replace("\n\n\n\ne", "\n\n\ne"))
        self.assertEqual(normalize.normalize("é"), "é\n")

    def test_quality_rules(self):
        self.assertEqual(quality.check("x" * 10, "language", 200, 10**6), "too_short")
        self.assertEqual(quality.check("a" * 300, "language", 200, 100), "too_long")
        self.assertEqual(quality.check("".join(f"{i}2345 !!! ###\n" for i in range(40)), "language", 200, 10**6), "low_alpha_ratio")
        self.assertEqual(quality.check("same line here\n" * 60, "code", 200, 10**6), "repetitive_lines")
        self.assertEqual(quality.check("a" * 30000 + "\nb" * 100, "code", 200, 10**6), "minified_or_binary_like")
        self.assertIsNone(quality.check(LONG, "language", 200, 10**6))
        self.assertEqual(quality.check(LONG, "language", 200, 10**6, bad_decode=len(LONG)), "corrupt_encoding")

    def test_dedup_exact_and_near(self):
        d = dedup.Deduper()
        base = " ".join(f"word{i % 50} token{i}" for i in range(400))
        self.assertIsNone(d.check("a", base))
        self.assertEqual(d.check("b", base), "a")
        near = base + " one more small tail sentence added here"
        self.assertEqual(d.check("c", near), "a")
        other = " ".join(f"different{i} text{i * 3}" for i in range(400))
        self.assertIsNone(d.check("d", other))

    def test_secrets_dropped_and_emails_redacted(self):
        why, _, _ = safety.scan("config\n-----BEGIN RSA PRIVATE KEY-----\nabc")
        self.assertEqual(why, "secret:private_key")
        self.assertEqual(safety.scan("key AKIAABCDEFGHIJKLMNOP")[0], "secret:aws_key")
        self.assertEqual(safety.scan('api_key = "abcdefghijklmnopqrstuvwxyz123456"')[0], "secret:api_key_assignment")
        why, out, n = safety.scan("mail me at jane.doe@example.com please")
        self.assertIsNone(why); self.assertEqual(n, 1); self.assertNotIn("jane", out)

    def test_tagging(self):
        self.assertEqual(tagging.category_of("a/b.py", ""), "code")
        self.assertEqual(tagging.category_of("x.json", ""), "structured_data")
        self.assertEqual(tagging.category_of("x.py", "science"), "science")
        self.assertEqual(tagging.script_of("日本語のテキスト"), "cjk")
        self.assertEqual(tagging.script_of("hello world"), "latin")

    def test_curriculum_is_configuration_not_code(self):
        base = {"a": 1, "b": 1}
        ph = [{"until": 0.5, "mixture": {"a": 3, "b": 1}}, {"until": 1.0, "mixture": {"a": 1, "b": 3}}]
        self.assertAlmostEqual(curriculum.mixture_at(0, 100, base, ph)["a"], 0.75)
        self.assertAlmostEqual(curriculum.mixture_at(60, 100, base, ph)["a"], 0.25)
        self.assertAlmostEqual(curriculum.mixture_at(999, 100, base, ph)["a"], 0.25)
        self.assertAlmostEqual(curriculum.mixture_at(5, 100, base, [])["a"], 0.5)
        with self.assertRaises(ValueError):
            curriculum.validate([{"until": 0.5}, {"until": 0.4}])


class Pipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.path, cls.cfg = prepared(cls.tmp)
        cls.out = cls.cfg.data["output"]

    def test_manifest_has_provenance_counts_and_hashes(self):
        m = json.load(open(os.path.join(self.out, "shards", "manifest.json")))
        self.assertEqual(m["foundry"], "foundry-v1")
        self.assertEqual(m["config_digest"], self.cfg.digest())
        self.assertGreater(m["totals"]["train"], 1000)
        self.assertTrue(m["documents"] and all("rel" in d and "tokens" in d for d in m["documents"]))
        for cat in m["categories"].values():
            for s in cat["train"]["shards"]:
                import hashlib
                a = np.fromfile(os.path.join(self.out, "shards", s["file"]), dtype=np.uint16)
                self.assertEqual(hashlib.sha256(a.tobytes()).hexdigest(), s["sha256"])
                self.assertEqual(len(a), s["tokens"])

    def test_train_and_val_never_share_a_document(self):
        m = json.load(open(os.path.join(self.out, "shards", "manifest.json")))
        splits = {}
        for d in m["documents"]:
            splits.setdefault(d["id"], set()).add(d["split"])
        self.assertTrue(all(len(s) == 1 for s in splits.values()))
        self.assertTrue(any("val" in s for s in splits.values()))

    def test_shards_decode_back_to_the_documents(self):
        tok = Tokenizer.load(os.path.join(self.out, "tokenizer"))
        a = np.fromfile(os.path.join(self.out, "shards", "language", "train_00000.bin"), dtype=np.uint16).tolist()
        self.assertEqual(a[a.index(EOS) - 1] != EOS, True)
        text = tok.decode(a[:a.index(EOS)])
        self.assertIn("the", text)

    def test_mixer_is_deterministic_per_step_and_respects_weights(self):
        s = TokenStreams(os.path.join(self.out, "shards"), "train")
        x1, y1 = s.batch(5, 7, 4, 16, {"language": 1.0})
        x2, y2 = s.batch(5, 7, 4, 16, {"language": 1.0})
        x3, _ = s.batch(5, 8, 4, 16, {"language": 1.0})
        self.assertTrue((x1 == x2).all()); self.assertFalse((x1 == x3).all())
        self.assertTrue((x1[:, 1:] == y1[:, :-1]).all())                          # targets are inputs shifted by one
        with self.assertRaises(ValueError):
            s.batch(5, 1, 2, 8, {"nonexistent": 1.0})
        fx, _ = s.fixed_windows(1, 6, 16); fy, _ = s.fixed_windows(1, 6, 16)
        self.assertTrue((fx == fy).all())

    def test_clean_report_counts_every_drop(self):
        d = tempfile.mkdtemp(); os.makedirs(os.path.join(d, "language"))
        open(os.path.join(d, "language", "a.txt"), "w").write(LONG)
        open(os.path.join(d, "language", "dup.txt"), "w").write(LONG)
        open(os.path.join(d, "language", "short.txt"), "w").write("tiny")
        open(os.path.join(d, "language", "key.txt"), "w").write(LONG + "\n-----BEGIN PRIVATE KEY-----\n")
        open(os.path.join(d, "language", "bin.txt"), "wb").write(b"\x00\x01\x02" * 100)
        open(os.path.join(d, "language", "other.exe"), "wb").write(b"MZ")
        r = pipeline.clean([d], tempfile.mkdtemp(), min_chars=100)
        self.assertEqual(r["kept_docs"], {"language": 1})
        self.assertEqual(r["dropped"], {"duplicate": 1, "too_short": 1, "secret:private_key": 1, "not_text": 2})

    def test_missing_source_is_an_error_not_an_empty_dataset(self):
        with self.assertRaises(FileNotFoundError):
            pipeline.clean(["/nonexistent/dir"], tempfile.mkdtemp())


if __name__ == "__main__":
    unittest.main()
