"""TCE-G1: TRAIL Cognitive Engine, Generation 1. Decoder-only autoregressive core assembled from replaceable components."""
import math

import torch
from torch import nn
from torch.nn import functional as F
from torch.utils.checkpoint import checkpoint

from .attention import KVCache
from .block import TransformerBlock
from .config import ARCH_NAME, ModelConfig
from .embeddings import TokenEmbedding
from .registry import build


class TCEG1(nn.Module):
    def __init__(self, cfg: ModelConfig):
        super().__init__()
        cfg.validate()
        self.cfg = cfg
        c = cfg.components
        self.embed = TokenEmbedding(cfg.vocab_size, cfg.d_model)
        self.rope = build("position", c["position"], cfg.head_dim, cfg.max_seq_len, cfg.rope_theta)
        self.blocks = nn.ModuleList(TransformerBlock(cfg) for _ in range(cfg.n_layers))
        self.final_norm = build("norm", c["norm"], cfg.d_model, cfg.norm_eps)
        self.lm_head = None if cfg.tie_embeddings else nn.Linear(cfg.d_model, cfg.vocab_size, bias=False)
        self.reset_parameters()

    def reset_parameters(self):
        """Random initialisation (no pretrained weights exist anywhere in TRAIL). Residual output projections are scaled by 1/sqrt(2L)."""
        std = self.cfg.init_std
        for m in self.modules():
            if isinstance(m, nn.Linear):
                nn.init.normal_(m.weight, 0.0, std)
        nn.init.normal_(self.embed.weight, 0.0, std)
        scaled = std / math.sqrt(2 * self.cfg.n_layers)
        for b in self.blocks:
            nn.init.normal_(b.attn.o_proj.weight, 0.0, scaled)
            nn.init.normal_(b.ffn.down.weight, 0.0, scaled)

    def new_caches(self, batch=1, device=None, dtype=None):
        p = next(self.parameters())
        return [KVCache(batch, self.cfg.n_kv_heads, self.cfg.max_seq_len, self.cfg.head_dim, dtype or p.dtype, device or p.device) for _ in self.blocks]

    def forward(self, ids, targets=None, caches=None, start=0, last_only=False):
        """ids [B,T] -> {'logits': [B,T,V] (or [B,1,V] if last_only), 'loss': scalar or None}. Targets equal to -100 are ignored."""
        x = self.embed(ids)
        for i, blk in enumerate(self.blocks):
            cache = caches[i] if caches is not None else None
            if self.cfg.gradient_checkpointing and self.training and cache is None:
                x = checkpoint(blk, x, self.rope, None, start, use_reentrant=False)
            else:
                x = blk(x, self.rope, cache, start)
        x = self.final_norm(x)
        if last_only:
            x = x[:, -1:]
        logits = F.linear(x, self.embed.weight) if self.lm_head is None else self.lm_head(x)
        loss = None
        if targets is not None:
            loss = F.cross_entropy(logits.float().reshape(-1, logits.size(-1)), targets.reshape(-1), ignore_index=-100)
        return {"logits": logits, "loss": loss}

    # -- introspection -----------------------------------------------------------------------------------------------------------------------
    def num_parameters(self, exclude_embeddings=False):
        n = sum(p.numel() for p in self.parameters())
        return n - self.embed.weight.numel() if exclude_embeddings else n

    def summary(self):
        c = self.cfg
        tot, core = self.num_parameters(), self.num_parameters(True)
        return "\n".join([
            f"{ARCH_NAME}  layers={c.n_layers} d_model={c.d_model} heads={c.n_heads} kv_heads={c.n_kv_heads} head_dim={c.head_dim} ffn_hidden={c.ffn_hidden}",
            f"vocab={c.vocab_size} max_seq_len={c.max_seq_len} tied_embeddings={c.tie_embeddings}",
            f"components={c.components}",
            f"parameters: {tot:,} total ({tot / 1e6:.2f}M), {core:,} outside the embedding table",
            f"KV cache per token: {2 * c.n_layers * c.n_kv_heads * c.head_dim * 2} bytes (bf16)"])
