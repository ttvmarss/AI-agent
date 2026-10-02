"""Training telemetry: every logged step goes to metrics.jsonl and to the console in one line. No spinners."""
import json
import os
import time


class Telemetry:
    def __init__(self, run_dir, total_steps, enabled=True):
        self.path = os.path.join(run_dir, "metrics.jsonl")
        self.total, self.enabled = total_steps, enabled
        self.t0 = time.time()
        os.makedirs(run_dir, exist_ok=True)

    def write(self, rec):
        if not self.enabled:
            return
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")

    def line(self, r):
        prog = r["step"] / max(self.total, 1)
        elapsed = time.time() - self.t0
        eta = elapsed / prog - elapsed if prog > 0 else float("nan")
        val = f" val {r['val_loss']:.4f}" if "val_loss" in r else ""
        return (f"step {r['step']:>6}/{self.total} ({prog * 100:5.1f}%) tokens {r['tokens']:>12,} loss {r['loss']:.4f}{val} lr {r['lr']:.2e} "
                f"gnorm {r['grad_norm']:.2f} {r['tok_s']:,.0f} tok/s mem {r['mem_mb']:.0f}MB eta {eta / 60:.1f}m")


def memory_mb(device):
    import torch
    if device.type == "cuda":
        return torch.cuda.max_memory_allocated() / 2**20
    try:
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024          # peak RSS (KB on Linux)
    except ImportError:
        return 0.0
