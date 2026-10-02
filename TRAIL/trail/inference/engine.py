"""TRAIL inference runtime: loads a TRAIL checkpoint directly and runs TCE-G1 with a KV cache. Nothing else is involved: no other model, no network."""
import codecs
import hashlib
import os

import torch

from ..tokenizer.bpe import BOS, EOS, Tokenizer
from ..training import checkpoint as ck
from ..utilities.files import read_json, sha256_file
from .sampling import sample_next


class Engine:
    def __init__(self, model, cfg, tokenizer, path, device="cpu"):
        self.model, self.cfg, self.tok, self.path, self.device = model.eval(), cfg, tokenizer, path, device
        self.arch_meta = read_json(os.path.join(path, "architecture.json")).get("trail", {})

    @classmethod
    def load(cls, checkpoint, device=None):
        path = ck.resolve_checkpoint(checkpoint)
        device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        model, cfg = ck.load_model(path, device)
        tok = Tokenizer.load(os.path.join(path, "tokenizer"))
        if tok.vocab_size != cfg.vocab_size:
            raise ValueError("tokenizer and architecture disagree on vocab size: this checkpoint is inconsistent")
        return cls(model, cfg, tok, path, device)

    @property
    def stage(self):
        return self.arch_meta.get("stage", "pretrain")

    def fingerprint(self):
        """Proof of origin: the hash of the weights file this engine is running."""
        return sha256_file(os.path.join(self.path, "model.safetensors"))

    @torch.no_grad()
    def stream_ids(self, prompt_ids, max_new_tokens=200, temperature=0.8, top_k=50, top_p=0.95, repetition_penalty=1.0, seed=None, stop_ids=(EOS,)):
        """Yields token ids one at a time. A seed (or temperature 0) makes the output reproducible."""
        cfg = self.cfg
        if len(prompt_ids) >= cfg.max_seq_len:
            prompt_ids = prompt_ids[-(cfg.max_seq_len - 1):]
        gen = None
        if seed is not None:
            gen = torch.Generator().manual_seed(int(seed))
        caches = self.model.new_caches(1, self.device)
        x = torch.tensor([prompt_ids], dtype=torch.long, device=self.device)
        logits = self.model(x, caches=caches, start=0, last_only=True)["logits"][0, -1]
        pos, history = len(prompt_ids), list(prompt_ids)
        for _ in range(max_new_tokens):
            nxt = sample_next(logits.cpu(), history, temperature, top_k, top_p, repetition_penalty, gen)
            if nxt in stop_ids:
                return
            yield nxt
            history.append(nxt)
            if pos >= cfg.max_seq_len:
                return                                      # context full
            logits = self.model(torch.tensor([[nxt]], device=self.device), caches=caches, start=pos, last_only=True)["logits"][0, -1]
            pos += 1

    def stream(self, prompt, **kw):
        """Yields text pieces (never half a UTF-8 character)."""
        dec = codecs.getincrementaldecoder("utf-8")("replace")
        for i in self.stream_ids(self.tok.encode(prompt, bos=True), **kw):
            piece = dec.decode(self.tok.decode_bytes([i]))
            if piece:
                yield piece
        tail = dec.decode(b"", final=True)
        if tail:
            yield tail

    def generate(self, prompt, **kw):
        return "".join(self.stream(prompt, **kw))
