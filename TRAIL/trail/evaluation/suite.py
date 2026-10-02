"""`trail evaluate <checkpoint>`: loss / perplexity / bits-per-byte, token efficiency, generation diversity, latency, memory, reasoning + coding probes.
Every run is appended to evaluations/history.jsonl so progress is a measured series, not a claim."""
import json
import math
import os
import time

import numpy as np
import torch

from ..config import load_config, project_root, resolve
from ..data_foundry.mixer import TokenStreams
from ..training import checkpoint as ck
from ..utilities.files import read_json
from ..utilities.log import get_logger
from . import metrics, probes
from ..inference.engine import Engine

log = get_logger("eval")
PROMPTS = ["The history of", "def main():\n", "In the beginning", "{\"name\":", "To compute the sum of"]


def _data_dir(ckpt, config_path):
    run = os.path.dirname(ckpt)
    rc = os.path.join(run, "run_config.json")
    if config_path:
        return resolve(load_config(config_path).data["output"])
    if os.path.isfile(rc):
        return resolve(read_json(rc)["config"]["data"]["output"])
    raise FileNotFoundError("cannot find the dataset for this checkpoint: pass --config")


def _known_words(data_dir):
    p = os.path.join(data_dir, "clean", "docs.jsonl")
    words = set()
    if os.path.isfile(p):
        import re
        from collections import Counter
        c = Counter()
        for line in open(p, encoding="utf-8"):
            d = json.loads(line)
            if d["category"] == "language":
                c.update(re.findall(r"[a-z]{3,}", d["text"].lower()))
        words = {w for w, n in c.items() if n >= 3}
    return words


def run_suite(checkpoint, config_path=None, record=True, n_val=48, gen_tokens=120):
    path = ck.resolve_checkpoint(checkpoint)
    eng = Engine.load(path, device="cpu")
    state = read_json(os.path.join(path, "trainer_state.json"))
    res = {"checkpoint": os.path.relpath(path, project_root()) if path.startswith(project_root()) else path, "step": state["step"], "tokens_seen": state["tokens"],
           "stage": eng.stage, "parameters": eng.model.num_parameters(), "weights_sha256": eng.fingerprint(), "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    data_dir = _data_dir(path, config_path)
    val = TokenStreams(os.path.join(data_dir, "shards"), "val")
    T = min(eng.cfg.max_seq_len, 256)
    x, y = val.fixed_windows(1234, n_val, T)
    tot, n = 0.0, 0
    with torch.no_grad():
        for i in range(0, len(x), 8):
            xb, yb = torch.from_numpy(x[i:i + 8]), torch.from_numpy(y[i:i + 8])
            tot += eng.model(xb, yb)["loss"].item() * len(xb)
            n += len(xb)
    loss = tot / n
    bytes_per_tok = np.mean([len(eng.tok.decode_bytes(row.tolist())) / len(row) for row in x])
    res["language_modeling"] = {"val_loss": round(loss, 4), "perplexity": round(math.exp(loss), 2), "bits_per_byte": round(loss / math.log(2) / bytes_per_tok, 4),
                                "random_baseline_loss": round(math.log(eng.cfg.vocab_size), 4)}
    per = {}
    with torch.no_grad():
        for c in val.categories():
            xc, yc = val.fixed_windows(1234, 16, T, c)
            per[c] = round(sum(eng.model(torch.from_numpy(xc[i:i + 8]), torch.from_numpy(yc[i:i + 8]))["loss"].item() * len(xc[i:i + 8]) for i in range(0, 16, 8)) / 16, 4)
    res["language_modeling"]["val_loss_by_category"] = per
    res["token_efficiency"] = {"bytes_per_token": round(float(bytes_per_tok), 3)}
    known = _known_words(data_dir)
    gens = []
    for i, p in enumerate(PROMPTS):
        gens.append(eng.generate(p, max_new_tokens=gen_tokens, temperature=0.8, top_k=40, seed=100 + i, repetition_penalty=1.1))
    div = metrics.diversity(" ".join(gens))
    div["valid_word_rate"] = round(metrics.word_validity(" ".join(gens), known), 3) if known else None
    div["samples"] = [{"prompt": p, "continuation": g[:300]} for p, g in zip(PROMPTS, gens)]
    res["generation"] = div
    res["latency"] = metrics.latency(eng)
    res["peak_rss_mb"] = round(__import__("resource").getrusage(__import__("resource").RUSAGE_SELF).ru_maxrss / 1024, 0)
    for name, items in (("reasoning", probes.REASONING), ("coding", probes.CODING)):
        acc, chance = metrics.multiple_choice(eng, items)
        res[name] = {"accuracy": round(acc, 3), "chance": round(chance, 3), "items": len(items), "note": "likelihood-scored multiple choice; near chance means no measurable skill yet"}
    if record:
        hist = os.path.join(project_root(), "evaluations", "history.jsonl")
        os.makedirs(os.path.dirname(hist), exist_ok=True)
        with open(hist, "a", encoding="utf-8") as f:
            f.write(json.dumps({k: v for k, v in res.items() if k != "generation"} | {"generation": {k: v for k, v in res["generation"].items() if k != "samples"}}) + "\n")
    return res
