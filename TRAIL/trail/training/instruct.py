"""Stage 9: instruction training as an independent stage. The BASE checkpoint is never modified: a new run directory receives the INSTRUCT checkpoints.
Loss is computed only on the assistant's tokens; a share of ordinary pretraining windows is mixed in so the base abilities are not overwritten."""
import os
import time

import numpy as np
import torch

from ..config import load_config, resolve
from ..data_foundry.mixer import TokenStreams
from ..model.config import ModelConfig
from ..tokenizer.bpe import PAD, Tokenizer
from ..tokenizer.template import IDENTITY_SYSTEM, encode_training_example
from ..utilities.files import read_json, write_json_atomic
from ..utilities.log import get_logger
from ..utilities.seed import seed_everything
from . import checkpoint as ck
from .instruct_data import make_examples
from .schedule import lr_at
from .trainer import build_optimizer

log = get_logger("instruct")


def _batch(tok, examples, rng, bs, max_len):
    rows = [examples[int(i)] for i in rng.integers(0, len(examples), bs)]
    enc = [encode_training_example(tok, IDENTITY_SYSTEM, u, a) for u, a in rows]
    L = min(max_len, max(len(i) for i, _ in enc))
    x = np.full((bs, L), PAD, dtype=np.int64)
    y = np.full((bs, L), -100, dtype=np.int64)
    for r, (ids, mask) in enumerate(enc):
        ids, mask = ids[:L + 1], mask[:L + 1]
        n = len(ids) - 1
        x[r, :n] = ids[:-1]
        y[r, :n] = [t if m else -100 for t, m in zip(ids[1:], mask[1:])]
    return torch.from_numpy(x), torch.from_numpy(y)


def run_instruct(base_checkpoint, out_dir, config_path):
    cfg = load_config(config_path)
    base = ck.resolve_checkpoint(base_checkpoint)
    out_dir = out_dir if os.path.isabs(out_dir) else resolve(out_dir)
    if os.path.commonpath([os.path.abspath(out_dir), os.path.abspath(os.path.dirname(base))]) == os.path.abspath(out_dir) or os.path.abspath(out_dir) == os.path.abspath(os.path.dirname(base)):
        raise ValueError("the INSTRUCT run directory must differ from the BASE run directory: the base checkpoint is never overwritten")
    seed_everything(cfg.seed)
    model, mcfg = ck.load_model(base, "cpu")
    tok = Tokenizer.load(os.path.join(base, "tokenizer"))
    base_state = read_json(os.path.join(base, "trainer_state.json"))
    ic = cfg.instruct
    steps, bs = int(ic["steps"]), int(ic["batch_size"])
    opt = build_optimizer(model, ic["lr"], 0.0, cfg.training["betas"])
    shards = os.path.join(resolve(cfg.data["output"]), "shards")
    replay = TokenStreams(shards, "train")
    examples = make_examples(cfg.seed)
    log.info("instruct: %d examples, %d steps, base %s (step %d)", len(examples), steps, base, base_state["step"])
    rng = np.random.default_rng(cfg.seed)
    model.train()
    T = min(mcfg.max_seq_len, 192)
    t0 = time.time()
    for step in range(1, steps + 1):
        lr = lr_at(step - 1, steps, ic["lr"], max(1, steps // 20), 0.1, "cosine")
        for g in opt.param_groups:
            g["lr"] = lr
        x, y = _batch(tok, examples, rng, bs, T)
        loss_i = model(x, y)["loss"]
        rx, ry = replay.batch(cfg.seed + 1, step, max(2, bs // 2), T, cfg.data["mixture"])
        loss_r = model(torch.from_numpy(rx), torch.from_numpy(ry))["loss"]
        loss = loss_i + 0.3 * loss_r
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step(); opt.zero_grad(set_to_none=True)
        if step % 25 == 0 or step == steps:
            log.info("instruct step %d/%d loss(instr) %.4f loss(replay) %.4f lr %.2e (%.0fs)", step, steps, loss_i.item(), loss_r.item(), lr, time.time() - t0)
    st = {"step": steps, "tokens": 0, "best_val": None, "seed": cfg.seed, "config_digest": cfg.digest(), "stage": "instruct", "schedule": {},
          "base_checkpoint": base, "base_step": base_state["step"]}
    os.makedirs(out_dir, exist_ok=True)
    write_json_atomic(os.path.join(out_dir, "run_config.json"), {"config": cfg.raw, "digest": cfg.digest(), "stage": "instruct"})
    path = ck.save(out_dir, steps, model, opt, st, mcfg, os.path.join(base, "tokenizer"), os.path.join(shards, "manifest.json"),
                   {"step": steps, "instruct_loss": loss_i.item(), "replay_loss": loss_r.item()}, keep=2,
                   extra_arch={"stage": "instruct", "base_checkpoint_sha256": __import__("hashlib").sha256(open(os.path.join(base, "model.safetensors"), "rb").read()).hexdigest()})
    log.info("TRAIL-V1-INSTRUCT checkpoint -> %s", path)
    return 0
