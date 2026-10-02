# Training

```
trail hardware
python scripts/fetch_corpus.py              # once: assemble the local corpus
trail data prepare --config configs/trail_micro.yaml
trail train --config configs/trail_micro.yaml
trail evaluate checkpoints/trail-micro
trail chat checkpoints/trail-micro
trail instruct checkpoints/trail-micro --out checkpoints/trail-micro-instruct
```

Features: AdamW (no decay on norms/embeddings), warmup + cosine (or linear/constant), gradient accumulation and clipping, bf16/fp16 autocast on GPU (fp32 on CPU),
optional gradient checkpointing and `torch.compile`, validation (overall and per category) on fixed windows, telemetry (`metrics.jsonl` and one console line per log:
step, tokens, loss, val loss, lr, grad norm, tokens/s, memory, % complete, ETA), checkpoint rotation, SIGINT/SIGTERM save-and-exit, non-finite-loss abort,
curriculum scheduling from config, and DDP hooks (untested). Deterministic seeding; the CPU path is exactly reproducible.
