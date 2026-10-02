import os
import random


def seed_everything(seed: int):
    """Seed python, numpy and torch. Determinism is best effort: CPU is exact, CUDA kernels may differ across devices."""
    import numpy as np
    import torch
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    os.environ.setdefault("PYTHONHASHSEED", str(seed))
