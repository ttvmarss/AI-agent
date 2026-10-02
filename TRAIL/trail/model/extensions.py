"""Extension points for later TRAIL generations. INTERFACES ONLY: nothing here is implemented, nothing here pretends to work in V1.

Each class states the contract a future component must meet so it can be registered (trail.model.registry) and swapped in via configuration,
without rewriting the base model. A component that is still a placeholder raises NotImplementedError when instantiated.
"""
from abc import ABC, abstractmethod

from .registry import register


class _Planned(ABC):
    status = "INTERFACE ONLY (not implemented)"
    planned_generation = ""


class MemoryModule(_Planned):
    """TRAIL Memory Fabric (V3). Working / episodic / semantic / project / procedural / relational memory as a first-class subsystem.
    forward(hidden, state) -> (hidden_update, new_state); `state` persists across calls so memory outlives a single context window."""
    planned_generation = "V3"

    @abstractmethod
    def read(self, hidden, state): ...
    @abstractmethod
    def write(self, hidden, state): ...


class ExpertRouter(_Planned):
    """Expert Fabric (V3). route(hidden) -> (expert_indices, weights) for sparse Mixture-of-Experts layers (token-choice or expert-choice)."""
    planned_generation = "V3"

    @abstractmethod
    def route(self, hidden): ...


class DifficultyEstimator(_Planned):
    """Deliberation Engine (V2). estimate(hidden) -> compute budget (fast / deep / parallel), so easy inputs do not cost what extreme ones do."""
    planned_generation = "V2"

    @abstractmethod
    def estimate(self, hidden): ...


class ParallelReasoner(_Planned):
    """Parallel reasoning (V2): propose several candidate solutions, hand them to a Verifier."""
    planned_generation = "V2"

    @abstractmethod
    def propose(self, prompt_ids, n): ...


class Verifier(_Planned):
    """Verification engine (V2): critique(candidate) -> score / revision. Objective is correctness, not longer outputs."""
    planned_generation = "V2"

    @abstractmethod
    def critique(self, prompt_ids, candidate_ids): ...


class ModalityEncoder(_Planned):
    """Native multimodality (V4): encode(raw) -> a sequence of vectors in the model's d_model space, consumed by the core in place of token embeddings."""
    planned_generation = "V4"
    modality = ""

    @abstractmethod
    def encode(self, raw): ...


class WorldState(_Planned):
    """World model (V5): persistent entities, relations, causality, space, time, goals and constraints that language reads from and writes to."""
    planned_generation = "V5"

    @abstractmethod
    def update(self, hidden): ...


@register("memory", "none")
def _no_memory(cfg):
    return None


@register("router", "none")
def _no_router(cfg):
    return None


@register("memory", "fabric")
def _memory(cfg):
    raise NotImplementedError("Memory Fabric is planned for TRAIL V3 (MemoryModule interface only).")
