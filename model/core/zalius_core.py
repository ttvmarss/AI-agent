"""Zalius Core: decoder-only causal Transformer, randomly initialised (OWN-001: no pretrained weights).

Pre-norm blocks, learned absolute positions, tied input/output embeddings, causal attention
via torch scaled_dot_product_attention (is_causal=True). Character-level tokenizer is a
deliberate PIPELINE-PROOF choice; BPE/unigram is decided at M2 (D3).
"""
from dataclasses import dataclass, asdict
import json, math
import torch
import torch.nn as nn
import torch.nn.functional as F


class CharTokenizer:
    """Reversible char tokenizer built only from training text. id 0 = <unk>."""
    def __init__(self, chars: str):
        self.itos = ["<unk>"] + sorted(set(chars))
        self.stoi = {c: i for i, c in enumerate(self.itos)}

    @property
    def vocab_size(self): return len(self.itos)
    def encode(self, s): return [self.stoi.get(c, 0) for c in s]
    def decode(self, ids): return "".join(self.itos[i] for i in ids)
    def to_json(self): return json.dumps({"itos": self.itos}, ensure_ascii=False)
    @classmethod
    def from_json(cls, s):
        t = cls(""); t.itos = json.loads(s)["itos"]; t.stoi = {c: i for i, c in enumerate(t.itos)}; return t


@dataclass
class CoreConfig:
    vocab_size: int
    n_layer: int = 6
    n_head: int = 4
    d_model: int = 256
    ctx: int = 256
    dropout: float = 0.1

    def to_dict(self): return asdict(self)


class Block(nn.Module):
    def __init__(self, c: CoreConfig):
        super().__init__()
        self.n_head = c.n_head
        self.ln1, self.ln2 = nn.LayerNorm(c.d_model), nn.LayerNorm(c.d_model)
        self.qkv = nn.Linear(c.d_model, 3 * c.d_model)
        self.proj = nn.Linear(c.d_model, c.d_model)
        self.mlp = nn.Sequential(nn.Linear(c.d_model, 4 * c.d_model), nn.GELU(), nn.Linear(4 * c.d_model, c.d_model))
        self.drop = nn.Dropout(c.dropout)
        self.p = c.dropout

    def forward(self, x):
        B, T, C = x.shape
        q, k, v = self.qkv(self.ln1(x)).split(C, dim=2)
        q, k, v = (t.view(B, T, self.n_head, C // self.n_head).transpose(1, 2) for t in (q, k, v))
        a = F.scaled_dot_product_attention(q, k, v, is_causal=True, dropout_p=self.p if self.training else 0.0)
        x = x + self.drop(self.proj(a.transpose(1, 2).reshape(B, T, C)))
        return x + self.drop(self.mlp(self.ln2(x)))


class ZaliusCore(nn.Module):
    def __init__(self, c: CoreConfig):
        super().__init__()
        self.c = c
        self.tok = nn.Embedding(c.vocab_size, c.d_model)
        self.pos = nn.Embedding(c.ctx, c.d_model)
        self.blocks = nn.ModuleList(Block(c) for _ in range(c.n_layer))
        self.ln_f = nn.LayerNorm(c.d_model)
        self.head = nn.Linear(c.d_model, c.vocab_size, bias=False)
        self.head.weight = self.tok.weight  # tied
        self.apply(self._init)
        for n, p in self.named_parameters():  # GPT-2-style scaled residual init
            if n.endswith("proj.weight") or n.endswith("mlp.2.weight"):
                nn.init.normal_(p, 0.0, 0.02 / math.sqrt(2 * c.n_layer))

    @staticmethod
    def _init(m):
        if isinstance(m, nn.Linear):
            nn.init.normal_(m.weight, 0.0, 0.02)
            if m.bias is not None: nn.init.zeros_(m.bias)
        elif isinstance(m, nn.Embedding):
            nn.init.normal_(m.weight, 0.0, 0.02)

    def n_params(self): return sum(p.numel() for p in self.parameters())

    def forward(self, idx, targets=None):
        B, T = idx.shape
        assert T <= self.c.ctx, "sequence longer than context"
        x = self.tok(idx) + self.pos(torch.arange(T, device=idx.device))
        for b in self.blocks: x = b(x)
        logits = self.head(self.ln_f(x))
        loss = None if targets is None else F.cross_entropy(logits.view(-1, logits.size(-1)), targets.view(-1))
        return logits, loss

    @torch.no_grad()
    def generate(self, idx, max_new, temperature=0.8, top_k=40, seed=0):
        g = torch.Generator().manual_seed(seed)
        was = self.training; self.eval()
        for _ in range(max_new):
            logits, _ = self(idx[:, -self.c.ctx:])
            logits = logits[:, -1] / max(temperature, 1e-5)
            if top_k:
                v, _ = torch.topk(logits, min(top_k, logits.size(-1)))
                logits[logits < v[:, [-1]]] = -float("inf")
            nxt = torch.multinomial(F.softmax(logits, -1), 1, generator=g)
            idx = torch.cat([idx, nxt], 1)
        self.train(was)
        return idx
