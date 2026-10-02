"""Architecture configuration for TCE-G1. Scale lives here, never in code: the same source builds Micro and Frontier."""
from dataclasses import asdict, dataclass, field, fields

ARCH_NAME = "TCE-G1"


@dataclass
class ModelConfig:
    vocab_size: int = 2048
    n_layers: int = 6
    d_model: int = 256
    n_heads: int = 8
    n_kv_heads: int = 4                  # < n_heads = grouped-query attention; == n_heads = multi-head; 1 = multi-query
    ffn_mult: float = 8 / 3              # hidden = round_up(ffn_mult * d_model, multiple_of)
    multiple_of: int = 64
    max_seq_len: int = 512
    rope_theta: float = 10000.0
    norm_eps: float = 1e-5
    dropout: float = 0.0
    tie_embeddings: bool = True
    init_std: float = 0.02
    # Replaceable components: each name is looked up in trail.model.registry. Future generations add names, not rewrites.
    components: dict = field(default_factory=lambda: {"norm": "rmsnorm", "position": "rope", "attention": "gqa", "ffn": "swiglu", "memory": "none", "router": "none"})
    gradient_checkpointing: bool = False

    @property
    def head_dim(self):
        return self.d_model // self.n_heads

    @property
    def ffn_hidden(self):
        h = int(self.ffn_mult * self.d_model)
        return ((h + self.multiple_of - 1) // self.multiple_of) * self.multiple_of

    def validate(self):
        if self.d_model % self.n_heads:
            raise ValueError("d_model must be divisible by n_heads")
        if self.n_heads % self.n_kv_heads:
            raise ValueError("n_heads must be divisible by n_kv_heads")
        if self.head_dim % 2:
            raise ValueError("head_dim must be even (rotary embeddings)")
        if self.vocab_size < 16 or self.n_layers < 1 or self.max_seq_len < 8:
            raise ValueError("vocab_size >= 16, n_layers >= 1, max_seq_len >= 8 required")
        return self

    def to_dict(self):
        d = asdict(self)
        d["architecture"] = ARCH_NAME
        return d

    @classmethod
    def from_dict(cls, d):
        names = {f.name for f in fields(cls)}
        unknown = set(d) - names - {"architecture"}
        if unknown:
            raise ValueError(f"unknown model config keys: {sorted(unknown)}")
        if d.get("architecture", ARCH_NAME) != ARCH_NAME:
            raise ValueError(f"checkpoint architecture is {d['architecture']!r}, this code is {ARCH_NAME}")
        return cls(**{k: v for k, v in d.items() if k in names}).validate()
