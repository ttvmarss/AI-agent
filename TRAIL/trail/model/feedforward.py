from torch import nn
from torch.nn import functional as F

from .registry import register


@register("ffn", "swiglu")
class SwiGLU(nn.Module):
    """Gated feed-forward: down(silu(gate(x)) * up(x))."""

    def __init__(self, cfg):
        super().__init__()
        h = cfg.ffn_hidden
        self.gate = nn.Linear(cfg.d_model, h, bias=False)
        self.up = nn.Linear(cfg.d_model, h, bias=False)
        self.down = nn.Linear(h, cfg.d_model, bias=False)
        self.drop = nn.Dropout(cfg.dropout)

    def forward(self, x):
        return self.down(self.drop(F.silu(self.gate(x)) * self.up(x)))


@register("ffn", "moe")
def _moe(cfg):
    raise NotImplementedError("sparse Mixture-of-Experts is planned for TRAIL V3 (see docs/ROADMAP.md); only the interface exists "
                              "(trail.model.extensions.ExpertRouter). Use ffn='swiglu'.")
