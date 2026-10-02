import os
import random
import tempfile

import torch
import yaml

torch.set_num_threads(1)

WORDS = "the quick brown fox jumps over lazy dog and runs through green forest while river water flows under old stone bridge near small village".split()


def make_corpus(root, n_docs=40, seed=0):
    rnd = random.Random(seed)
    for cat in ("language", "code", "technical"):
        os.makedirs(os.path.join(root, cat), exist_ok=True)
    for i in range(n_docs):
        text = " ".join(rnd.choice(WORDS) for _ in range(400)) + f" unique{i}\n"
        open(os.path.join(root, "language", f"d{i}.txt"), "w").write(text)
        code = "\n".join(f"def f{i}_{j}(x):\n    return x + {j} * {rnd.randint(1, 9)}" for j in range(30))
        open(os.path.join(root, "code", f"c{i}.py"), "w").write(code)
        open(os.path.join(root, "technical", f"t{i}.md"), "w").write("# Title %d\n" % i + " ".join(rnd.choice(WORDS) for _ in range(300)) + "\n")


def tiny_config(tmp, steps=20, vocab=300, extra=None):
    cfg = {"name": "trail-test", "seed": 5,
           "model": {"n_layers": 2, "d_model": 32, "n_heads": 4, "n_kv_heads": 2, "max_seq_len": 64},
           "tokenizer": {"vocab_size": vocab},
           "data": {"sources": [os.path.join(tmp, "raw")], "output": os.path.join(tmp, "processed"),
                    "mixture": {"language": 0.5, "code": 0.3, "technical": 0.2}, "min_chars": 50, "val_fraction": 0.1},
           "training": {"run_dir": os.path.join(tmp, "run"), "seq_len": 32, "batch_size": 4, "max_steps": steps, "warmup_steps": 2, "lr": 3e-3,
                        "eval_interval": 10, "eval_batches": 2, "checkpoint_interval": 10, "log_interval": 5, "keep_checkpoints": 5},
           "instruct": {"steps": 6, "batch_size": 2, "lr": 1e-3}}
    if extra:
        for k, v in extra.items():
            cfg[k].update(v)
    p = os.path.join(tmp, "cfg.yaml")
    yaml.safe_dump(cfg, open(p, "w"))
    return p


def prepared(tmp, steps=20):
    """A tiny corpus, tokenizer and shards ready for training."""
    from trail.config import load_config
    from trail.data_foundry import pipeline
    from trail.tokenizer import train as tt
    from trail.tokenizer.bpe import Tokenizer
    make_corpus(os.path.join(tmp, "raw"))
    path = tiny_config(tmp, steps)
    cfg = load_config(path)
    out = cfg.data["output"]
    pipeline.clean(cfg.data["sources"], os.path.join(out, "clean"), min_chars=50, allowed_categories=set(cfg.data["mixture"]))
    tt.train_from_clean(os.path.join(out, "clean"), os.path.join(out, "tokenizer"), cfg.tokenizer["vocab_size"])
    pipeline.shard(os.path.join(out, "clean"), Tokenizer.load(os.path.join(out, "tokenizer")), os.path.join(out, "shards"), 0.1, cfg.digest())
    return path, cfg
