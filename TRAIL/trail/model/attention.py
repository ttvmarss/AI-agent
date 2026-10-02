import torch
from torch import nn
from torch.nn import functional as F

from .registry import register


class KVCache:
    """Preallocated key/value cache for one layer: appending is a copy into a slice, never a re-allocation."""

    def __init__(self, batch, n_kv, max_len, head_dim, dtype, device):
        self.k = torch.zeros(batch, n_kv, max_len, head_dim, dtype=dtype, device=device)
        self.v = torch.zeros_like(self.k)
        self.length = 0

    def append(self, k, v):
        T = k.shape[2]
        if self.length + T > self.k.shape[2]:
            raise ValueError("KV cache full (context length exceeded)")
        self.k[:, :, self.length:self.length + T] = k
        self.v[:, :, self.length:self.length + T] = v
        self.length += T
        return self.k[:, :, :self.length], self.v[:, :, :self.length]


@register("attention", "gqa")
class GroupedQueryAttention(nn.Module):
    """Causal self-attention with n_kv_heads <= n_heads key/value heads shared by groups of query heads (smaller KV cache, same quality at scale)."""

    def __init__(self, cfg):
        super().__init__()
        self.n_heads, self.n_kv, self.hd = cfg.n_heads, cfg.n_kv_heads, cfg.head_dim
        self.q_proj = nn.Linear(cfg.d_model, self.n_heads * self.hd, bias=False)
        self.k_proj = nn.Linear(cfg.d_model, self.n_kv * self.hd, bias=False)
        self.v_proj = nn.Linear(cfg.d_model, self.n_kv * self.hd, bias=False)
        self.o_proj = nn.Linear(self.n_heads * self.hd, cfg.d_model, bias=False)
        self.dropout = cfg.dropout

    def forward(self, x, rope, cache=None, start=0):
        B, T, _ = x.shape
        q = self.q_proj(x).view(B, T, self.n_heads, self.hd).transpose(1, 2)
        k = self.k_proj(x).view(B, T, self.n_kv, self.hd).transpose(1, 2)
        v = self.v_proj(x).view(B, T, self.n_kv, self.hd).transpose(1, 2)
        q, k = rope.apply(q, start), rope.apply(k, start)
        if cache is not None:
            k, v = cache.append(k, v)
        S = k.shape[2]
        if self.n_kv != self.n_heads:
            rep = self.n_heads // self.n_kv
            k, v = k.repeat_interleave(rep, dim=1), v.repeat_interleave(rep, dim=1)
        p = self.dropout if self.training else 0.0
        if T == S:
            y = F.scaled_dot_product_attention(q, k, v, dropout_p=p, is_causal=True)
        elif T == 1:
            y = F.scaled_dot_product_attention(q, k, v, dropout_p=p)
        else:                                                   # chunk appended to a non-empty cache: query i may see keys up to S - T + i
            mask = torch.ones(T, S, dtype=torch.bool, device=x.device).tril(diagonal=S - T)
            y = F.scaled_dot_product_attention(q, k, v, attn_mask=mask, dropout_p=p)
        return self.o_proj(y.transpose(1, 2).reshape(B, T, self.n_heads * self.hd))
