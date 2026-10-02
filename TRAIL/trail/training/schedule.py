import math


def lr_at(step, total_steps, base_lr, warmup_steps, min_lr_ratio=0.1, kind="cosine"):
    """Linear warmup to base_lr, then cosine (or linear / constant) decay to base_lr * min_lr_ratio."""
    if warmup_steps > 0 and step < warmup_steps:
        return base_lr * (step + 1) / warmup_steps
    if kind == "constant":
        return base_lr
    prog = min(1.0, max(0.0, (step - warmup_steps) / max(1, total_steps - warmup_steps)))
    floor = base_lr * min_lr_ratio
    if kind == "linear":
        return base_lr + (floor - base_lr) * prog
    if kind == "cosine":
        return floor + 0.5 * (base_lr - floor) * (1 + math.cos(math.pi * prog))
    raise ValueError(f"unknown schedule {kind!r}")
