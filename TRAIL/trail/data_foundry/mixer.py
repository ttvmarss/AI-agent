"""Training-mix sampler. Windows are drawn at random from per-category token streams with category weights from the (curriculum-scheduled) mixture.
Batch `step` is a pure function of (seed, step): a resumed run sees exactly the data an uninterrupted run would have seen."""
import json
import os

import numpy as np

from ..utilities.files import read_json


class TokenStreams:
    def __init__(self, data_dir, split):
        self.manifest = read_json(os.path.join(data_dir, "manifest.json"))
        self.split = split
        self.streams = {}                       # category -> list of memmaps
        for cat, parts in self.manifest["categories"].items():
            if split in parts:
                self.streams[cat] = [np.memmap(os.path.join(data_dir, s["file"]), dtype=np.uint16, mode="r") for s in parts[split]["shards"]]
        if not self.streams:
            raise ValueError(f"no {split} data under {data_dir}")
        self.sizes = {c: sum(len(a) for a in arrs) for c, arrs in self.streams.items()}

    def categories(self):
        return sorted(self.streams)

    def total_tokens(self):
        return sum(self.sizes.values())

    def _window(self, cat, pos, n):
        """n tokens starting at global offset `pos` within the category (concatenated shards)."""
        out, remaining = [], n
        for a in self.streams[cat]:
            if pos >= len(a):
                pos -= len(a)
                continue
            take = a[pos:pos + remaining]
            out.append(np.asarray(take))
            remaining -= len(take)
            pos = 0
            if remaining == 0:
                break
        return np.concatenate(out)

    def sample(self, rng, cat, seq_len):
        size = self.sizes[cat]
        if size < seq_len + 1:                  # tiny category: wrap around so it can still be sampled
            reps = (seq_len + 1) // size + 2
            flat = np.concatenate([self._window(cat, 0, size)] * reps)
            start = int(rng.integers(0, len(flat) - seq_len - 1))
            return flat[start:start + seq_len + 1].astype(np.int64)
        start = int(rng.integers(0, size - seq_len - 1))
        return self._window(cat, start, seq_len + 1).astype(np.int64)

    def batch(self, seed, step, batch_size, seq_len, weights):
        """-> (x, y) int64 arrays [B, T]. weights: {category: w}; categories without data are ignored and the rest renormalised."""
        w = {c: float(weights.get(c, 0.0)) for c in self.streams if weights.get(c, 0.0) > 0}
        if not w:
            raise ValueError(f"mixture {weights} matches no category with data ({self.categories()})")
        cats = sorted(w)
        p = np.asarray([w[c] for c in cats]) / sum(w.values())
        rng = np.random.default_rng([seed, step])
        picks = rng.choice(len(cats), size=batch_size, p=p)
        rows = np.stack([self.sample(rng, cats[i], seq_len) for i in picks])
        return rows[:, :-1], rows[:, 1:]

    def fixed_windows(self, seed, n, seq_len, cat=None):
        """A fixed validation set: the same windows every time for the same data (so validation loss is comparable across checkpoints)."""
        rng = np.random.default_rng([seed, 7777])
        cats = [cat] if cat else self.categories()
        rows = [self.sample(rng, cats[i % len(cats)], seq_len) for i in range(n)]
        r = np.stack(rows)
        return r[:, :-1], r[:, 1:]
