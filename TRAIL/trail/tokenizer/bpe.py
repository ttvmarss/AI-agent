"""TRAIL Tokenizer V1: byte-level BPE, trained here, on our corpus. Not borrowed from any other model.

* Every byte is a token, so any Unicode (or binary) input is representable and decode(encode(x)) == x exactly.
* Merges are learned from the supplied corpus; pre-tokenisation splits on a regex that keeps words, numbers, punctuation runs and whitespace runs
  apart (so code indentation, paths, JSON punctuation and Markdown markers get their own merges).
* A small, fixed set of special tokens carries architecture functions (see SPECIAL_TOKENS). Ids: specials first, then 256 bytes, then merges.
"""
import json
import re
from collections import Counter, defaultdict

from ..utilities.files import write_json_atomic

TOKENIZER_VERSION = "trail-tokenizer-v1"
SPECIAL_TOKENS = ["<PAD>", "<BOS>", "<EOS>", "<SYSTEM>", "<USER>", "<TRAIL>", "<TOOL>", "<MEMORY>", "<CODE>"]
N_SPECIAL = len(SPECIAL_TOKENS)
PAD, BOS, EOS = 0, 1, 2
# words (with one optional leading space), digits one at a time, runs of punctuation, whitespace (a trailing space stays with the next word)
PRETOKEN = r"""'(?:s|t|re|ve|m|ll|d)| ?[^\W\d_]+| ?\d| ?(?:[^\s\w]|_)+|\s+(?!\S)|\s+"""
_SPECIAL_RE = re.compile("(" + "|".join(re.escape(s) for s in SPECIAL_TOKENS) + ")")


def byte_id(b):
    return N_SPECIAL + b


class Tokenizer:
    def __init__(self, merges, meta=None, vocab_size=None):
        self.merges = [tuple(m) for m in merges]
        self.meta = meta or {}
        natural = N_SPECIAL + 256 + len(self.merges)
        self.vocab_size = max(natural, vocab_size or 0)       # ids beyond the learned merges are reserved (never produced, decode to nothing) so the model's table size is stable
        self.rank = {p: i for i, p in enumerate(self.merges)}
        self.pair_to_id = {p: N_SPECIAL + 256 + i for i, p in enumerate(self.merges)}
        self.pre = re.compile(PRETOKEN)
        self.special_ids = {s: i for i, s in enumerate(SPECIAL_TOKENS)}
        self._bytes = {byte_id(b): bytes([b]) for b in range(256)}
        for (a, b), i in self.pair_to_id.items():
            self._bytes[i] = self._bytes[a] + self._bytes[b]
        self._cache = {}

    # -- encode / decode ---------------------------------------------------------------------------------------------------------------------
    def _encode_word(self, w):
        hit = self._cache.get(w)
        if hit is not None:
            return hit
        ids = [byte_id(b) for b in w.encode("utf-8", "replace")]
        while len(ids) > 1:
            best, best_rank = None, None
            for p in zip(ids, ids[1:]):
                r = self.rank.get(p)
                if r is not None and (best_rank is None or r < best_rank):
                    best, best_rank = p, r
            if best is None:
                break
            new, out, i = self.pair_to_id[best], [], 0
            while i < len(ids):
                if i < len(ids) - 1 and (ids[i], ids[i + 1]) == best:
                    out.append(new); i += 2
                else:
                    out.append(ids[i]); i += 1
            ids = out
        if len(self._cache) < 200_000:
            self._cache[w] = ids
        return ids

    def encode(self, text, allow_special=False, bos=False, eos=False):
        out = [BOS] if bos else []
        parts = _SPECIAL_RE.split(text) if allow_special else [text]
        for part in parts:
            if allow_special and part in self.special_ids:
                out.append(self.special_ids[part])
                continue
            for m in self.pre.finditer(part):
                out.extend(self._encode_word(m.group()))
        if eos:
            out.append(EOS)
        return out

    def decode_bytes(self, ids):
        return b"".join(self._bytes.get(i, b"") for i in ids)

    def decode(self, ids, skip_special=True):
        if skip_special:
            return self.decode_bytes(ids).decode("utf-8", errors="replace")
        out, buf = [], []
        for i in ids:
            if i < N_SPECIAL:
                out.append(self.decode_bytes(buf).decode("utf-8", errors="replace")); buf = []
                out.append(SPECIAL_TOKENS[i])
            else:
                buf.append(i)
        out.append(self.decode_bytes(buf).decode("utf-8", errors="replace"))
        return "".join(out)

    # -- persistence -------------------------------------------------------------------------------------------------------------------------
    def save(self, directory):
        import os
        os.makedirs(directory, exist_ok=True)
        write_json_atomic(os.path.join(directory, "tokenizer.json"), {
            "version": TOKENIZER_VERSION, "type": "byte-level-bpe", "pretoken_regex": PRETOKEN, "special_tokens": SPECIAL_TOKENS,
            "vocab_size": self.vocab_size, "merges": [list(m) for m in self.merges], "meta": self.meta})

    @classmethod
    def load(cls, directory):
        import os
        p = directory if directory.endswith(".json") else os.path.join(directory, "tokenizer.json")
        with open(p, "r", encoding="utf-8") as f:
            d = json.load(f)
        if d.get("version") != TOKENIZER_VERSION or d.get("special_tokens") != SPECIAL_TOKENS or d.get("pretoken_regex") != PRETOKEN:
            raise ValueError(f"{p} was not produced by {TOKENIZER_VERSION} with this pre-tokeniser; refusing to load a mismatched tokenizer")
        return cls(d["merges"], d.get("meta"), d.get("vocab_size"))


def train(texts, vocab_size, min_frequency=2, progress=None, meta=None):
    """Learn merges from an iterable of strings. Deterministic: ties break on the pair of ids."""
    n_merges = vocab_size - N_SPECIAL - 256
    if n_merges < 0:
        raise ValueError(f"vocab_size must be at least {N_SPECIAL + 256}")
    pre = re.compile(PRETOKEN)
    counts = Counter()
    nbytes = 0
    for t in texts:
        nbytes += len(t.encode("utf-8", "replace"))
        counts.update(m.group() for m in pre.finditer(t))
    words = [[byte_id(b) for b in w.encode("utf-8", "replace")] for w in counts]
    freqs = list(counts.values())
    stats, where = defaultdict(int), defaultdict(set)
    for wi, w in enumerate(words):
        for p in zip(w, w[1:]):
            stats[p] += freqs[wi]
            where[p].add(wi)
    merges, next_id = [], N_SPECIAL + 256
    for step in range(n_merges):
        if not stats:
            break
        best = max(stats.items(), key=lambda kv: (kv[1], -kv[0][0], -kv[0][1]))
        pair, c = best
        if c < min_frequency:
            break
        merges.append(pair)
        for wi in list(where.pop(pair, ())):
            w, f = words[wi], freqs[wi]
            for p in zip(w, w[1:]):                         # remove this word's old pairs
                stats[p] -= f
                if stats[p] <= 0:
                    del stats[p]
            out, i = [], 0
            while i < len(w):
                if i < len(w) - 1 and (w[i], w[i + 1]) == pair:
                    out.append(next_id); i += 2
                else:
                    out.append(w[i]); i += 1
            words[wi] = out
            for p in zip(out, out[1:]):                     # and add the new ones
                stats[p] += f
                where[p].add(wi)
        stats.pop(pair, None)
        next_id += 1
        if progress and (step + 1) % 250 == 0:
            progress(step + 1, n_merges)
    m = dict(meta or {})
    m.update({"trained_on_bytes": nbytes, "distinct_pretokens": len(counts), "requested_vocab_size": vocab_size, "min_frequency": min_frequency})
    return Tokenizer(merges, m, vocab_size)
