import torch
from torch import nn

from .registry import register


class TokenEmbedding(nn.Module):
    def __init__(self, vocab_size, d_model):
        super().__init__()
        self.weight = nn.Parameter(torch.empty(vocab_size, d_model))

    def forward(self, ids):
        return nn.functional.embedding(ids, self.weight)


@register("position", "rope")
class RotaryEmbedding(nn.Module):
    """Rotary position representation: rotates query/key channel pairs by an angle proportional to position. No learned position table, so the same
    weights can be run at other context lengths (quality beyond the trained length is not guaranteed)."""

    def __init__(self, head_dim, max_seq_len, theta=10000.0):
        super().__init__()
        inv = 1.0 / (theta ** (torch.arange(0, head_dim, 2).float() / head_dim))
        ang = torch.outer(torch.arange(max_seq_len).float(), inv)
        self.register_buffer("cos", ang.cos(), persistent=False)
        self.register_buffer("sin", ang.sin(), persistent=False)

    def apply(self, x, start):
        """x: [B, H, T, D] -> rotated, positions start..start+T-1."""
        T = x.shape[2]
        if start + T > self.cos.shape[0]:
            raise ValueError(f"position {start + T} exceeds max_seq_len {self.cos.shape[0]}")
        cos = self.cos[start:start + T].to(x.dtype)[None, None]
        sin = self.sin[start:start + T].to(x.dtype)[None, None]
        x1, x2 = x[..., 0::2], x[..., 1::2]
        out = torch.stack((x1 * cos - x2 * sin, x1 * sin + x2 * cos), dim=-1)
        return out.flatten(-2)
