"""Distributed-training hooks. Single-process is the tested path. Data parallelism via torchrun/DDP is wired here but UNTESTED in this repository's
environment (no multi-device hardware); tensor / pipeline / expert parallelism are future work (docs/ROADMAP.md)."""
import os

import torch


def init_distributed():
    """-> (rank, world_size, local_rank). Reads torchrun's environment; a plain `trail train` is rank 0 of 1."""
    world = int(os.environ.get("WORLD_SIZE", "1"))
    if world <= 1:
        return 0, 1, 0
    import torch.distributed as dist
    rank, local = int(os.environ["RANK"]), int(os.environ.get("LOCAL_RANK", "0"))
    dist.init_process_group("nccl" if torch.cuda.is_available() else "gloo")
    if torch.cuda.is_available():
        torch.cuda.set_device(local)
    return rank, world, local


def wrap_model(model, world, local_rank, device):
    if world <= 1:
        return model
    from torch.nn.parallel import DistributedDataParallel as DDP
    return DDP(model, device_ids=[local_rank] if device.type == "cuda" else None)
