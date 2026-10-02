"""Checkpoints that describe exactly what created them, written atomically (temp directory then rename), rotated, never overwritten by accident."""
import json
import os
import re
import shutil
import time

import torch
from safetensors.torch import load_file, save_file

from .. import ARCHITECTURE, GENERATION, __version__
from ..model.config import ModelConfig
from ..utilities.files import read_json, write_json_atomic

_NAME = re.compile(r"^checkpoint_(\d{6})$")


def checkpoint_dirs(run_dir):
    if not os.path.isdir(run_dir):
        return []
    return sorted((os.path.join(run_dir, d) for d in os.listdir(run_dir) if _NAME.match(d) and os.path.isfile(os.path.join(run_dir, d, "COMPLETE"))))


def latest(run_dir):
    c = checkpoint_dirs(run_dir)
    return c[-1] if c else None


def resolve_checkpoint(path):
    """A checkpoint directory, or a run directory (-> its latest checkpoint)."""
    if os.path.isfile(os.path.join(path, "architecture.json")):
        return path
    l = latest(path)
    if l is None:
        raise FileNotFoundError(f"no complete checkpoint in {path}")
    return l


def save(run_dir, step, model, optimizer, state, model_cfg: ModelConfig, tokenizer_dir, manifest_path, metrics, keep=3, extra_arch=None):
    final = os.path.join(run_dir, f"checkpoint_{step:06d}")
    if os.path.exists(final):
        raise FileExistsError(f"{final} already exists; refusing to overwrite a checkpoint")
    tmp = final + ".partial"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    raw = model.module if hasattr(model, "module") else model
    raw = getattr(raw, "_orig_mod", raw)
    save_file({k: v.detach().cpu().contiguous() for k, v in raw.state_dict().items()}, os.path.join(tmp, "model.safetensors"),
              metadata={"architecture": ARCHITECTURE, "generation": str(GENERATION), "trail_version": __version__})
    if optimizer is not None:
        torch.save(optimizer.state_dict(), os.path.join(tmp, "optimizer.pt"))
    torch.save({"schedule": state.get("schedule", {}), "step": step}, os.path.join(tmp, "scheduler.pt"))
    write_json_atomic(os.path.join(tmp, "trainer_state.json"), state)
    write_json_atomic(os.path.join(tmp, "architecture.json"), {**model_cfg.to_dict(), "trail": {"generation": GENERATION, "trail_version": __version__, **(extra_arch or {})}})
    write_json_atomic(os.path.join(tmp, "metrics.json"), metrics)
    if tokenizer_dir and os.path.isdir(tokenizer_dir):
        shutil.copytree(tokenizer_dir, os.path.join(tmp, "tokenizer"))
    if manifest_path and os.path.isfile(manifest_path):
        shutil.copyfile(manifest_path, os.path.join(tmp, "dataset_manifest.json"))
    with open(os.path.join(tmp, "COMPLETE"), "w") as f:                      # written last: its presence means every file above is whole
        f.write(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    os.replace(tmp, final)
    for old in checkpoint_dirs(run_dir)[:-keep] if keep > 0 else []:
        if not os.path.exists(os.path.join(old, "KEEP")):
            shutil.rmtree(old, ignore_errors=True)
    return final


def load_model(ckpt_dir, device="cpu"):
    from ..model import TCEG1
    d = read_json(os.path.join(ckpt_dir, "architecture.json"))
    d.pop("trail", None)
    cfg = ModelConfig.from_dict(d)
    model = TCEG1(cfg)
    model.load_state_dict(load_file(os.path.join(ckpt_dir, "model.safetensors")), strict=True)
    return model.to(device), cfg


def load_training_state(ckpt_dir, optimizer=None, device="cpu"):
    state = read_json(os.path.join(ckpt_dir, "trainer_state.json"))
    if optimizer is not None and os.path.isfile(os.path.join(ckpt_dir, "optimizer.pt")):
        optimizer.load_state_dict(torch.load(os.path.join(ckpt_dir, "optimizer.pt"), map_location=device))
    return state
