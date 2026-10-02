"""Whole-run configuration loaded from configs/*.yaml. One file describes model scale, tokenizer, data mixture, curriculum and training."""
import copy
import hashlib
import json
import os
from dataclasses import dataclass, field

import yaml

from .model.config import ModelConfig

DEFAULTS = {
    "name": "trail-micro",
    "generation": 1,
    "seed": 1337,
    "model": {},
    "tokenizer": {"vocab_size": 2048, "min_frequency": 2, "sample_bytes": 20_000_000},
    "data": {
        "sources": ["datasets/raw"],
        "output": "datasets/processed",
        "val_fraction": 0.02,
        "min_chars": 200, "max_chars": 2_000_000,
        "mixture": {"language": 0.3, "code": 0.4, "technical": 0.2, "structured_data": 0.1},
        "allow_unknown_categories": False,
    },
    "curriculum": [],          # [{until: 0.3, mixture: {...}}, ...]  `until` is a fraction of total steps
    "training": {
        "run_dir": "checkpoints/run",
        "seq_len": 256, "batch_size": 16, "grad_accum": 1,
        "max_steps": 2000, "warmup_steps": 100, "lr": 3e-3, "min_lr_ratio": 0.1, "schedule": "cosine",
        "weight_decay": 0.1, "betas": [0.9, 0.95], "grad_clip": 1.0,
        "precision": "auto", "eval_interval": 250, "eval_batches": 20, "checkpoint_interval": 500, "keep_checkpoints": 3,
        "log_interval": 10, "compile": False, "num_threads": 0,
    },
    "instruct": {"steps": 300, "lr": 5e-4, "batch_size": 8, "epochs": 0},
}


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


@dataclass
class TrailConfig:
    raw: dict
    model: ModelConfig = field(default=None)

    @property
    def name(self): return self.raw["name"]
    @property
    def seed(self): return int(self.raw["seed"])
    @property
    def tokenizer(self): return self.raw["tokenizer"]
    @property
    def data(self): return self.raw["data"]
    @property
    def training(self): return self.raw["training"]
    @property
    def curriculum(self): return self.raw["curriculum"]
    @property
    def instruct(self): return self.raw["instruct"]

    def digest(self):
        return hashlib.sha256(json.dumps(self.raw, sort_keys=True).encode()).hexdigest()[:16]


def load_config(path, overrides=None):
    with open(path, "r", encoding="utf-8") as f:
        user = yaml.safe_load(f) or {}
    raw = _merge(DEFAULTS, _merge(user, overrides or {}))
    unknown = set(raw) - set(DEFAULTS)
    if unknown:
        raise ValueError(f"unknown top-level config keys in {path}: {sorted(unknown)}")
    mc = dict(raw["model"])
    mc.setdefault("vocab_size", raw["tokenizer"]["vocab_size"])
    if mc["vocab_size"] != raw["tokenizer"]["vocab_size"]:
        raise ValueError("model.vocab_size must equal tokenizer.vocab_size")
    model = ModelConfig.from_dict(mc)
    if raw["training"]["seq_len"] > model.max_seq_len:
        raise ValueError("training.seq_len exceeds model.max_seq_len")
    mix = raw["data"]["mixture"]
    if not mix or any(w < 0 for w in mix.values()) or sum(mix.values()) <= 0:
        raise ValueError("data.mixture needs non-negative weights with a positive sum")
    raw["model"] = model.to_dict()
    return TrailConfig(raw=raw, model=model)


def resolve(path, base=None):
    """Relative paths in a config are relative to the project root (the directory holding configs/)."""
    if os.path.isabs(path):
        return path
    return os.path.join(base or project_root(), path)


def project_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
