import torch
from torch import nn

from .registry import register


@register("norm", "rmsnorm")
class RMSNorm(nn.Module):
    """x / rms(x) * weight. Statistics in float32 so bf16/fp16 training stays stable."""

    def __init__(self, dim, eps=1e-5):
        super().__init__()
        self.eps = eps
        self.weight = nn.Parameter(torch.ones(dim))

    def forward(self, x):
        xf = x.float()
        return (xf * torch.rsqrt(xf.pow(2).mean(-1, keepdim=True) + self.eps)).to(x.dtype) * self.weight
