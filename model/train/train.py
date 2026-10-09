"""Bounded, resumable pretraining of Zalius Core (pipeline-proof run).

Everything reported comes from this script's own logs; nothing is hand-entered.
Checkpoints: atomic write (tmp + rename) with sha256 sidecar; contain weights, optimizer, step, config, tokenizer.
Usage: train.py --data DIR --out DIR [--max-minutes M] [--steps N] [--resume]
"""
import argparse, hashlib, json, math, os, resource, subprocess, sys, time
from pathlib import Path
import torch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
from zalius_core import CharTokenizer, CoreConfig, ZaliusCore

PROMPTS = ["It is a truth universally acknowledged", "\"Where are you going?\" said", "The next morning", "I do not know"]


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for ch in iter(lambda: f.read(1 << 20), b""): h.update(ch)
    return h.hexdigest()


def save_ckpt(path, model, opt, step, tok, best_val):
    tmp = str(path) + ".tmp"
    torch.save({"model": model.state_dict(), "opt": opt.state_dict(), "step": step, "config": model.c.to_dict(),
                "tok": tok.to_json(), "best_val": best_val}, tmp)
    os.replace(tmp, path)
    Path(str(path) + ".sha256").write_text(sha256(path))


def batch(data, bs, ctx, g):
    ix = torch.randint(0, len(data) - ctx - 1, (bs,), generator=g)
    x = torch.stack([data[i:i + ctx] for i in ix]); y = torch.stack([data[i + 1:i + ctx + 1] for i in ix])
    return x, y


@torch.no_grad()
def evaluate(model, data, ctx, bs=32, n=40):
    """Fixed, deterministic eval windows (same every call) so curves are comparable."""
    model.eval(); g = torch.Generator().manual_seed(1234); tot = 0.0
    for _ in range(n):
        x, y = batch(data, bs, ctx, g); tot += model(x, y)[1].item()
    model.train(); return tot / n


def bigram_baseline(train, test, V):
    """Add-one smoothed char bigram LM: a simple non-neural baseline (blueprint 4.6)."""
    c = torch.ones(V, V)
    c.index_put_((train[:-1], train[1:]), torch.ones(len(train) - 1), accumulate=True)
    p = c / c.sum(1, keepdim=True)
    return -torch.log(p[test[:-1], test[1:]]).mean().item()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--steps", type=int, default=6000); ap.add_argument("--max-minutes", type=float, default=30)
    ap.add_argument("--bs", type=int, default=32); ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--warmup", type=int, default=200); ap.add_argument("--eval-every", type=int, default=250)
    ap.add_argument("--ckpt-every", type=int, default=500); ap.add_argument("--seed", type=int, default=1337)
    ap.add_argument("--n-layer", type=int, default=6); ap.add_argument("--d-model", type=int, default=256)
    ap.add_argument("--n-head", type=int, default=4); ap.add_argument("--ctx", type=int, default=256)
    ap.add_argument("--resume", action="store_true")
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    torch.manual_seed(a.seed)
    D = Path(a.data)
    txt = {k: (D / f"{k}.txt").read_text(encoding="utf-8") for k in ("train", "val", "test")}
    ck = out / "last.pt"
    if a.resume and ck.exists():
        st = torch.load(ck, weights_only=False); tok = CharTokenizer.from_json(st["tok"])
        cfg = CoreConfig(**st["config"])
    else:
        st = None; tok = CharTokenizer(txt["train"])  # vocab from TRAIN only
        cfg = CoreConfig(vocab_size=tok.vocab_size, n_layer=a.n_layer, n_head=a.n_head, d_model=a.d_model, ctx=a.ctx)
    data = {k: torch.tensor(tok.encode(v)) for k, v in txt.items()}
    model = ZaliusCore(cfg)
    opt = torch.optim.AdamW(model.parameters(), lr=a.lr, betas=(0.9, 0.95), weight_decay=0.1)
    step, best_val = 0, float("inf")
    if st:
        model.load_state_dict(st["model"]); opt.load_state_dict(st["opt"]); step, best_val = st["step"], st["best_val"]
    log = open(out / "train_log.jsonl", "a")
    def emit(**k): k["t"] = time.time(); log.write(json.dumps(k) + "\n"); log.flush(); print(json.dumps(k), flush=True)

    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    if not st:
        run = {"git_commit": commit, "params": model.n_params(), "config": cfg.to_dict(), "args": vars(a),
               "torch": torch.__version__, "threads": torch.get_num_threads(), "device": "cpu",
               "corpus_manifest_sha256": sha256(D / "corpus_manifest.json"),
               "tokens": {k: len(v) for k, v in data.items()}}
        (out / "run_manifest.json").write_text(json.dumps(run, indent=2))
        base = {"uniform_loss": math.log(tok.vocab_size), "bigram_test_loss": bigram_baseline(data["train"], data["test"], tok.vocab_size),
                "untrained_val": evaluate(model, data["val"], cfg.ctx), "untrained_test": evaluate(model, data["test"], cfg.ctx)}
        (out / "baselines.json").write_text(json.dumps(base, indent=2))
        samples = {p: tok.decode(model.generate(torch.tensor([tok.encode(p)]), 160, seed=1)[0].tolist()) for p in PROMPTS}
        (out / "samples_before.json").write_text(json.dumps(samples, indent=2, ensure_ascii=False))
        emit(event="start", params=model.n_params(), **base)

    g = torch.Generator().manual_seed(a.seed + step)  # resume uses a new deterministic stream
    t0 = time.time(); tok_seen = 0; model.train()
    def lr_at(s):
        if s < a.warmup: return a.lr * (s + 1) / a.warmup
        return a.lr * (0.1 + 0.9 * 0.5 * (1 + math.cos(math.pi * (s - a.warmup) / max(1, a.steps - a.warmup))))
    stop = "steps_reached"
    while step < a.steps:
        if (time.time() - t0) / 60 > a.max_minutes: stop = "wall_time_budget"; break
        for gr in opt.param_groups: gr["lr"] = lr_at(step)
        x, y = batch(data["train"], a.bs, cfg.ctx, g)
        _, loss = model(x, y)
        if not torch.isfinite(loss): stop = "nan_loss"; emit(event="abort", reason=stop, step=step); break
        opt.zero_grad(set_to_none=True); loss.backward()
        gn = torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0).item()
        opt.step(); step += 1; tok_seen += a.bs * cfg.ctx
        if step % 50 == 0:
            emit(event="train", step=step, loss=loss.item(), lr=lr_at(step), grad_norm=gn,
                 tok_per_s=tok_seen / (time.time() - t0), max_rss_mb=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)
        if step % a.eval_every == 0:
            v = evaluate(model, data["val"], cfg.ctx); emit(event="val", step=step, val_loss=v)
            if v < best_val:
                best_val = v; save_ckpt(out / "best.pt", model, opt, step, tok, best_val)
        if step % a.ckpt_every == 0: save_ckpt(ck, model, opt, step, tok, best_val)
    save_ckpt(ck, model, opt, step, tok, best_val)
    final = {"event": "end", "stop_reason": stop, "step": step, "wall_min": (time.time() - t0) / 60,
             "val_loss": evaluate(model, data["val"], cfg.ctx), "test_loss": evaluate(model, data["test"], cfg.ctx),
             "ckpt_sha256": (Path(str(ck) + ".sha256")).read_text()}
    emit(**final)
    samples = {p: tok.decode(model.generate(torch.tensor([tok.encode(p)]), 160, seed=1)[0].tolist()) for p in PROMPTS}
    (out / "samples_after.json").write_text(json.dumps(samples, indent=2, ensure_ascii=False))
    (out / "final.json").write_text(json.dumps(final, indent=2))


if __name__ == "__main__":
    main()
