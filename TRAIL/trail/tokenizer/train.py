"""Train TRAIL Tokenizer V1 from the Data Foundry's cleaned documents (so the tokenizer sees exactly what the model will)."""
import hashlib
import json
import os

from ..utilities.log import get_logger
from . import bpe

log = get_logger("tokenizer")


def iter_clean_texts(clean_dir, max_bytes):
    """Balanced sample: documents are visited round-robin across categories so no single large source (e.g. code) decides the vocabulary."""
    by_cat = {}
    with open(os.path.join(clean_dir, "docs.jsonl"), "r", encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            by_cat.setdefault(d["category"], []).append(d)
    budget = max_bytes // max(len(by_cat), 1)
    for cat, docs in sorted(by_cat.items()):
        used = 0
        for d in docs:
            if used >= budget:
                break
            t = d["text"][: max(0, budget - used)]
            used += len(t.encode("utf-8", "replace"))
            yield t


def train_from_clean(clean_dir, out_dir, vocab_size, min_frequency=2, sample_bytes=20_000_000):
    texts = list(iter_clean_texts(clean_dir, sample_bytes))
    digest = hashlib.sha256("\n".join(t[:2000] for t in texts).encode("utf-8", "replace")).hexdigest()[:16]
    log.info("training tokenizer: vocab %d on %d text blocks", vocab_size, len(texts))
    tok = bpe.train(texts, vocab_size, min_frequency, progress=lambda s, n: log.info("  merge %d/%d", s, n),
                    meta={"version": bpe.TOKENIZER_VERSION, "corpus_sample_digest": digest})
    tok.save(out_dir)
    log.info("saved %s (vocab %d)", out_dir, tok.vocab_size)
    return tok


def roundtrip_check(tok, texts, limit=2000):
    """decode(encode(x)) must equal x exactly for every sample. Returns (n_checked, n_failed, bytes_per_token)."""
    bad = n = nb = nt = 0
    for t in texts:
        if n >= limit:
            break
        ids = tok.encode(t)
        n += 1
        nb += len(t.encode("utf-8"))
        nt += len(ids)
        if tok.decode(ids) != t:
            bad += 1
    return n, bad, (nb / nt if nt else 0.0)
