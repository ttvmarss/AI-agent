from torch import nn

from .registry import build


class TransformerBlock(nn.Module):
    """x = x + attention(norm(x));  x = x + ffn(norm(x)). Every part comes from the registry, so each can be swapped by configuration."""

    def __init__(self, cfg):
        super().__init__()
        c = cfg.components
        self.attn_norm = build("norm", c["norm"], cfg.d_model, cfg.norm_eps)
        self.attn = build("attention", c["attention"], cfg)
        self.ffn_norm = build("norm", c["norm"], cfg.d_model, cfg.norm_eps)
        self.ffn = build("ffn", c["ffn"], cfg)
        self.memory = build("memory", c["memory"], cfg)          # None in V1
        self.drop = nn.Dropout(cfg.dropout)

    def forward(self, x, rope, cache=None, start=0):
        x = x + self.drop(self.attn(self.attn_norm(x), rope, cache, start))
        if self.memory is not None:
            x = x + self.memory(x)
        return x + self.drop(self.ffn(self.ffn_norm(x)))
