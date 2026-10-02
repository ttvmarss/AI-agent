import math
import re
import time
from collections import Counter

import torch


@torch.no_grad()
def candidate_logprob(engine, prompt, cand):
    """Sum log P(cand tokens | prompt) under the model."""
    p = engine.tok.encode(prompt, bos=True)
    c = engine.tok.encode(cand)
    ids = (p + c)[-engine.cfg.max_seq_len:]
    x = torch.tensor([ids], device=engine.device)
    lp = torch.log_softmax(engine.model(x)["logits"][0].float(), -1)
    n = len(c)
    return sum(lp[len(ids) - n - 1 + i, ids[len(ids) - n + i]].item() for i in range(n))


def multiple_choice(engine, items):
    """-> (accuracy, chance). Length-normalised so longer candidates are not punished for being longer."""
    correct, chance = 0, 0.0
    for prompt, cands, gold in items:
        scores = [candidate_logprob(engine, prompt, c) / max(1, len(engine.tok.encode(c))) for c in cands]
        correct += int(max(range(len(cands)), key=scores.__getitem__) == gold)
        chance += 1 / len(cands)
    return correct / len(items), chance / len(items)


def diversity(text):
    """distinct-n ratios and the fraction of generated tokens that sit in a repeated 4-gram loop."""
    w = re.findall(r"\w+|[^\w\s]", text.lower())
    out = {"words": len(w)}
    for n in (1, 2, 3):
        g = [tuple(w[i:i + n]) for i in range(len(w) - n + 1)]
        out[f"distinct_{n}"] = len(set(g)) / len(g) if g else 0.0
    g4 = [tuple(w[i:i + 4]) for i in range(len(w) - 3)]
    c = Counter(g4)
    out["repeated_4gram_fraction"] = sum(v for v in c.values() if v > 1) / len(g4) if g4 else 0.0
    return out


def word_validity(text, known_words):
    ws = re.findall(r"[a-z]{3,}", text.lower())
    return sum(w in known_words for w in ws) / len(ws) if ws else 0.0


def latency(engine, prompt_tokens=64, new_tokens=48):
    V = engine.cfg.vocab_size
    ids = [1] + [9 + (i * 7) % (V - 9) for i in range(prompt_tokens - 1)]
    t0 = time.perf_counter()
    first, n = None, 0
    for _ in engine.stream_ids(ids, max_new_tokens=new_tokens, temperature=0, stop_ids=()):
        n += 1
        if first is None:
            first = time.perf_counter() - t0
    total = time.perf_counter() - t0
    return {"time_to_first_token_ms": round(first * 1000, 1), "decode_tokens_per_s": round((n - 1) / max(total - first, 1e-9), 1)}
