# TRAIL architecture: TCE-G1 (TRAIL Cognitive Engine, Generation 1)

TRAIL is a model lineage whose intelligence exists because this project trained it: random initial weights, its own tokenizer, its own architecture,
its own training stack, its own runtime. No pretrained weights, no model API, no other model underneath.

```
text -> TRAIL tokenizer -> TCE-G1 (our weights) -> TRAIL inference engine -> text
```

## What is built (V1)

| Part | Where | Notes |
|---|---|---|
| Tokenizer | `trail/tokenizer/bpe.py` | byte-level BPE trained here; 9 special tokens; exact round-trip for any Unicode |
| Embedding, RoPE | `trail/model/embeddings.py` | tied input/output embeddings (configurable) |
| RMSNorm | `normalization.py` | float32 statistics |
| Attention | `attention.py` | grouped-query (1 <= kv heads <= heads), preallocated KV cache, causal SDPA |
| Feed-forward | `feedforward.py` | SwiGLU |
| Block | `block.py` | pre-norm residual; every part built from the registry |
| Model | `architecture.py` | `TCEG1`: init, forward (loss with ignore index), cache creation, parameter count, summary |
| Config | `model/config.py`, `trail/config.py` | scale is data (`configs/*.yaml`), never code |

## Replaceable components

`config.components` maps `norm / position / attention / ffn / memory / router` to names in `trail/model/registry.py`. A future generation registers a new
implementation and changes one word in a config. Unbuilt futures are registered as **refusals**: `ffn: moe` and `memory: fabric` raise
`NotImplementedError` with the planned generation; they never silently fall back.

## Extension interfaces (declared, NOT implemented)

`trail/model/extensions.py` defines contracts for: `MemoryModule` (Memory Fabric), `ExpertRouter` (sparse experts), `DifficultyEstimator` and
`ParallelReasoner` and `Verifier` (Deliberation / verification), `ModalityEncoder` (native multimodality), `WorldState` (world model). Each class
carries `status = "INTERFACE ONLY"` and its planned generation. See `ROADMAP.md`.

## Properties that are tested (see `tests/`)

* causal (changing future tokens never changes earlier logits); KV-cached prefill / chunk / decode equals the full forward pass;
* parameter count equals the closed-form formula; MHA, GQA and MQA all run;
* initialisation is random and seeded; the loss at initialisation is near ln(vocab);
* a checkpoint reloads to identical weights; interrupted training resumes bit-for-bit; changing the weights changes the generated text.
