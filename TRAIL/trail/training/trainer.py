"""Autoregressive pretraining. Everything needed to reproduce and resume a run is derived from (config, seed, step): batches are a pure function of
(seed, step), the LR is a pure function of step, and a checkpoint carries model + optimizer + state, so an interrupted run continues bit-for-bit."""
import contextlib
import json
import os
import shutil
import signal
import time

import torch

from .. import ARCHITECTURE
from ..config import TrailConfig, project_root, resolve
from ..data_foundry import curriculum
from ..data_foundry.mixer import TokenStreams
from ..hardware.detect import detect
from ..model import TCEG1
from ..utilities.files import write_json_atomic
from ..utilities.log import get_logger
from ..utilities.seed import seed_everything
from . import checkpoint as ck
from .parallel import init_distributed, wrap_model
from .schedule import lr_at
from .telemetry import Telemetry, memory_mb

log = get_logger("train")


def build_optimizer(model, lr, weight_decay, betas):
    decay, no_decay = [], []
    for n, p in model.named_parameters():
        if not p.requires_grad:
            continue
        (decay if p.dim() >= 2 and "embed" not in n else no_decay).append(p)       # no decay on norms and the embedding table
    groups = [{"params": decay, "weight_decay": weight_decay}, {"params": no_decay, "weight_decay": 0.0}]
    return torch.optim.AdamW(groups, lr=lr, betas=tuple(betas), eps=1e-8)


@torch.no_grad()
def validate(model, streams, seed, seq_len, n_batches, batch_size, device, autocast, per_category=True):
    model.eval()
    out = {}
    sets = {"all": streams.fixed_windows(seed, n_batches * batch_size, seq_len)}
    if per_category:
        for c in streams.categories():
            sets[c] = streams.fixed_windows(seed, max(batch_size, 4 * batch_size // 2), seq_len, c)
    for name, (x, y) in sets.items():
        tot, n = 0.0, 0
        for i in range(0, len(x), batch_size):
            xb = torch.from_numpy(x[i:i + batch_size]).to(device)
            yb = torch.from_numpy(y[i:i + batch_size]).to(device)
            with autocast():
                loss = model(xb, yb)["loss"]
            tot += loss.item() * len(xb)
            n += len(xb)
        out[name] = tot / n
    model.train()
    return out


class Trainer:
    def __init__(self, cfg: TrailConfig, resume=True, max_steps=0, stage="pretrain"):
        self.cfg, self.resume, self.stop_at, self.stage = cfg, resume, max_steps, stage
        self.t = cfg.training
        self.interrupted = False

    def _autocast(self, device):
        prec = self.t["precision"]
        if prec == "auto":
            prec = "bf16" if device.type == "cuda" and torch.cuda.is_bf16_supported() else "fp16" if device.type == "cuda" else "fp32"
        self.precision = prec
        if prec == "fp32":
            return contextlib.nullcontext, None
        dt = torch.bfloat16 if prec == "bf16" else torch.float16
        scaler = torch.amp.GradScaler("cuda") if prec == "fp16" else None
        return (lambda: torch.autocast(device_type=device.type, dtype=dt)), scaler

    def run(self):
        cfg, t = self.cfg, self.t
        rank, world, local = init_distributed()
        seed_everything(cfg.seed)
        if t["num_threads"]:
            torch.set_num_threads(int(t["num_threads"]))
        device = torch.device("cuda", local) if torch.cuda.is_available() else torch.device("cpu")
        autocast, scaler = self._autocast(device)
        data_dir = resolve(cfg.data["output"])
        shards = os.path.join(data_dir, "shards")
        tok_dir = os.path.join(data_dir, "tokenizer")
        if not os.path.isfile(os.path.join(shards, "manifest.json")):
            raise FileNotFoundError(f"no prepared data in {shards}: run `trail data prepare --config ...` first")
        train_s, val_s = TokenStreams(shards, "train"), TokenStreams(shards, "val")
        model = TCEG1(cfg.model).to(device)
        run_dir = resolve(t["run_dir"])
        os.makedirs(run_dir, exist_ok=True)
        opt = build_optimizer(model, t["lr"], t["weight_decay"], t["betas"])
        total, step, tokens, best_val = int(t["max_steps"]), 0, 0, float("inf")
        latest = ck.latest(run_dir) if self.resume else None
        if latest:
            m, mc = ck.load_model(latest, device)
            if mc.to_dict() != cfg.model.to_dict():
                raise ValueError(f"{latest} was made with a different architecture than this config; use --fresh or another run_dir")
            model.load_state_dict(m.state_dict())
            st = ck.load_training_state(latest, opt, device)
            if st["config_digest"] != cfg.digest():
                log.warning("config changed since checkpoint (digest %s -> %s); continuing anyway", st["config_digest"], cfg.digest())
            step, tokens, best_val = st["step"], st["tokens"], st.get("best_val", float("inf"))
            log.info("resumed from %s at step %d", latest, step)
        elif self.resume is False and ck.checkpoint_dirs(run_dir):
            log.warning("--fresh: existing checkpoints in %s are kept; new ones continue the numbering only if steps do not collide", run_dir)
        if cfg.model.gradient_checkpointing:
            model.train()
        net = wrap_model(torch.compile(model) if t["compile"] else model, world, local, device)
        net.train()
        log.info("\n" + model.summary())
        info = detect(run_dir)
        log.info("device=%s precision=%s threads=%d | train tokens %s val tokens %s", device, self.precision, torch.get_num_threads(), f"{train_s.total_tokens():,}", f"{val_s.total_tokens():,}")
        shutil.copyfile(os.path.join(shards, "manifest.json"), os.path.join(run_dir, "dataset_manifest.json"))
        write_json_atomic(os.path.join(run_dir, "run_config.json"), {"config": cfg.raw, "digest": cfg.digest(), "hardware": info, "stage": self.stage})
        tele = Telemetry(run_dir, total, enabled=rank == 0)
        B, T, accum = int(t["batch_size"]), int(t["seq_len"]), int(t["grad_accum"])
        phases = cfg.curriculum
        curriculum.validate(phases)

        def on_signal(signum, frame):
            self.interrupted = True
        old = {s: signal.signal(s, on_signal) for s in (signal.SIGINT, signal.SIGTERM)}
        last_val, t_prev, tok_prev = None, time.time(), tokens
        schedule_cfg = {"base_lr": t["lr"], "warmup": t["warmup_steps"], "min_lr_ratio": t["min_lr_ratio"], "kind": t["schedule"], "total": total}

        def snapshot(metrics):
            st = {"step": step, "tokens": tokens, "best_val": best_val, "seed": cfg.seed, "config_digest": cfg.digest(), "schedule": schedule_cfg,
                  "stage": self.stage, "precision": self.precision, "world_size": world}
            if rank == 0:
                path = ck.save(run_dir, step, model, opt, st, cfg.model, tok_dir, os.path.join(shards, "manifest.json"), metrics, keep=int(t["keep_checkpoints"]))
                log.info("checkpoint -> %s", path)
                return path

        try:
            while step < total:
                mix = curriculum.mixture_at(step, total, cfg.data["mixture"], phases)
                lr = lr_at(step, total, t["lr"], t["warmup_steps"], t["min_lr_ratio"], t["schedule"])
                for g in opt.param_groups:
                    g["lr"] = lr
                loss_acc = 0.0
                for micro in range(accum):
                    x, y = train_s.batch(cfg.seed, (step * accum + micro) * world + rank, B, T, mix)
                    xb, yb = torch.from_numpy(x).to(device), torch.from_numpy(y).to(device)
                    with autocast():
                        loss = net(xb, yb)["loss"] / accum
                    if not torch.isfinite(loss):
                        raise FloatingPointError(f"non-finite loss at step {step}: {loss.item()}; lower the learning rate or check the data")
                    (scaler.scale(loss) if scaler else loss).backward()
                    loss_acc += loss.item()
                if scaler:
                    scaler.unscale_(opt)
                gnorm = torch.nn.utils.clip_grad_norm_(model.parameters(), t["grad_clip"]).item()
                if scaler:
                    scaler.step(opt); scaler.update()
                else:
                    opt.step()
                opt.zero_grad(set_to_none=True)
                step += 1
                tokens += B * T * accum * world
                rec = None
                if step % t["log_interval"] == 0 or step == total:
                    now = time.time()
                    rec = {"step": step, "tokens": tokens, "loss": loss_acc, "lr": lr, "grad_norm": gnorm, "tok_s": (tokens - tok_prev) / max(now - t_prev, 1e-9),
                           "mem_mb": memory_mb(device), "mixture": mix, "time": now}
                    t_prev, tok_prev = now, tokens
                if step % t["eval_interval"] == 0 or step == total:
                    v = validate(model, val_s, cfg.seed, T, t["eval_batches"], B, device, autocast)
                    last_val = v
                    best_val = min(best_val, v["all"])
                    rec = rec or {"step": step, "tokens": tokens, "loss": loss_acc, "lr": lr, "grad_norm": gnorm, "tok_s": 0.0, "mem_mb": memory_mb(device), "time": time.time()}
                    rec.update({"val_loss": v["all"], "val_by_category": {k: x for k, x in v.items() if k != "all"}})
                if rec and rank == 0:
                    tele.write(rec)
                    log.info(tele.line(rec))
                stop_now = self.interrupted or (self.stop_at and step >= self.stop_at)
                if (step % t["checkpoint_interval"] == 0 or step == total or stop_now) and rank == 0:
                    if not os.path.exists(os.path.join(run_dir, f"checkpoint_{step:06d}")):
                        snapshot({"step": step, "tokens": tokens, "loss": loss_acc, "val": last_val, "best_val": best_val})
                if stop_now:
                    log.info("stopping at step %d (%s)", step, "signal" if self.interrupted else "--max-steps")
                    break
        finally:
            for s, h in old.items():
                signal.signal(s, h)
        return 0
