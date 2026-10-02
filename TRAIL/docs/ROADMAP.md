# Roadmap (generations are decided by measurements, not by this list)

| Gen | Theme | Status |
|---|---|---|
| V1 | Foundation: tokenizer, TCE-G1, Data Foundry, training, checkpoints, inference, evaluation, instruct stage | **built** (micro scale, trained on CPU) |
| V2 | Deliberation: difficulty estimation, variable compute, parallel candidates, verifier | interfaces only (`DifficultyEstimator`, `ParallelReasoner`, `Verifier`) |
| V3 | Memory Fabric + sparse Mixture-of-Experts | interfaces only (`MemoryModule`, `ExpertRouter`); `ffn: moe`, `memory: fabric` refuse honestly |
| V4 | Native multimodality | interface only (`ModalityEncoder`) |
| V5 | World model + long-horizon cognition | interface only (`WorldState`) |
| V6 | Large-scale integrated system | not started |

Controlled self-improvement is permitted only as: analyse -> propose experiment -> run -> objective evaluation -> human approval -> versioned change.
No uncontrolled recursive self-modification.

## Scaling path

`configs/trail_micro` (CPU) -> `trail_small` (one GPU) -> `trail_base` / `trail_large` (multi-GPU / cluster) -> `trail_frontier` (declared, not trainable
today). Distributed hooks: data parallelism is wired in `training/parallel.py` (DDP via torchrun) and **untested here**; tensor / pipeline / expert
parallelism, sharded datasets and distributed checkpoints are not built.
