"""DEDUPLICATION: exact (hash of normalised text) and near-duplicate (MinHash over word 5-shingles, banded LSH)."""
import hashlib
import re
import struct

_WORD = re.compile(r"\w+")
NUM_PERM, BANDS = 32, 8
ROWS = NUM_PERM // BANDS
_MASK = (1 << 61) - 1


def _h(s: str, seed: int) -> int:
    return struct.unpack("<Q", hashlib.blake2b(s.encode("utf-8", "replace"), digest_size=8, key=seed.to_bytes(4, "little")).digest())[0]


def minhash(text: str, k=5):
    words = _WORD.findall(text.lower())
    if len(words) < k:
        return None
    shingles = {" ".join(words[i:i + k]) for i in range(0, len(words) - k + 1)}
    if len(shingles) > 4000:                                    # long documents: a stable sample is plenty to find near-copies
        shingles = set(sorted(shingles, key=lambda s: _h(s, 99))[:4000])
    return tuple(min(_h(s, seed) for s in shingles) for seed in range(NUM_PERM))


class Deduper:
    def __init__(self, threshold=0.8):
        self.exact, self.buckets, self.sigs, self.threshold = {}, {}, [], threshold

    def check(self, doc_id: str, text: str):
        """-> None if new, else the id of the document it duplicates."""
        digest = hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()
        if digest in self.exact:
            return self.exact[digest]
        self.exact[digest] = doc_id
        sig = minhash(text)
        if sig is None:
            return None
        cand = set()
        for b in range(BANDS):
            key = (b, sig[b * ROWS:(b + 1) * ROWS])
            cand.update(self.buckets.get(key, ()))
        for other_id, other in cand:
            if sum(x == y for x, y in zip(sig, other)) / NUM_PERM >= self.threshold:
                return other_id
        for b in range(BANDS):
            self.buckets.setdefault((b, sig[b * ROWS:(b + 1) * ROWS]), []).append((doc_id, sig))
        return None
