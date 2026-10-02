# TRAIL current state

_Last updated by the build session after Stage 9 (2026-10-02)._

| | |
|---|---|
| Current generation | **V1** (TCE-G1), micro scale |
| Architecture | decoder-only transformer: RMSNorm pre-norm, RoPE, grouped-query attention (8 heads / 4 KV heads), SwiGLU, tied embeddings, KV cache; 6 layers, d_model 256, context 256 |
| Parameters | 4,951,296 (4.43M outside the embedding table) |
| Tokenizer | `trail-tokenizer-v1`, byte-level BPE, vocab 2048, trained on the cleaned corpus (2.30 bytes/token on validation text), round-trip exact |
| Dataset | 636 files -> 619 documents kept (17 duplicates dropped, 496 e-mail redactions); 9.36M train / 0.28M val tokens: code 3.39M, language 3.19M, structured 1.39M, technical 0.79M, science 0.39M, mathematics 0.19M. Gutenberg books, IETF RFCs, Python stdlib, structured files from local Python packages (provenance in the manifest). Two intended books failed to download (404): Einstein *Relativity* and Euclid *Elements*, so mathematics is one small book |
| Training status | base run complete: 3000 steps, 24.58M tokens, from random init, CPU, ~64 min |
| Latest checkpoints | `checkpoints/TRAIL-V1-BASE` (weights sha256 `8747e512...`) and `checkpoints/TRAIL-V1-INSTRUCT` (committed without optimizer state; full runs under `checkpoints/trail-micro*` are local and git-ignored) |

## Latest metrics (`evaluations/history.jsonl`)

| | BASE | INSTRUCT |
|---|---|---|
| validation loss / perplexity | 2.669 / 14.4 | 2.707 / 15.0 |
| bits per byte | 1.676 | - |
| val loss by category | structured 1.67, code 2.05, language 3.20, technical 3.26 | - |
| reasoning probe (12 items, chance 25%) | 25% | 25% |
| coding probe (10 items, chance 25%) | 80% (indicative only) | 80% |
| generation: distinct-2 / repeated 4-gram share / valid-word rate | 0.82 / 12% / 85% | - |
| decode speed (CPU, 1 thread-pool of 4) | ~270 tok/s, first token ~10 ms | - |
| peak memory (inference) | ~307 MB RSS | - |
| held-out identity (6 prompts) | n/a | 5/6 by a lenient rule, ~4/6 correct on reading |

## Definition-of-done checklist (V1)

- [x] repository exists; [x] tokenizer trained here and belongs to this project; [x] architecture executes; [x] parameters initialise randomly
- [x] data loads; [x] training loop runs; [x] loss decreases (7.1 -> 2.3); [x] checkpoints save and reload to identical weights
- [x] interrupted training resumes (bit-for-bit, tested); [x] evaluation runs; [x] inference and streaming generation run; [x] chat runtime works
- [x] no external model, API or downloaded weights required: chat was run with the network disabled in-process (all socket calls raise) and answered from `TRAIL-V1-INSTRUCT`
- [x] documentation reflects what exists; unbuilt parts are marked INTERFACE ONLY

## Known issues and limits

* The model is tiny and data-limited: it writes plausible local text, no real knowledge, no reasoning. Do not use its output as fact.
* The instruct stage is memorised templates; unseen tasks fail (see EXPERIMENT_LOG E-005).
* Only the CPU path has been run. GPU precision paths (bf16/fp16 autocast, GradScaler), `torch.compile`, gradient checkpointing under training, and DDP are written but unexercised on real hardware (gradient checkpointing's gradients are unit-tested on CPU).
* The corpus is small and unbalanced; mathematics and science are one or two books each.
* Interfaces for memory, MoE, deliberation, verification, multimodality and world model exist only as contracts.
* No licence chosen yet (`LICENSE`).

## Completed stages

1 repository, config, logging, hardware; 2 tokenizer; 3 TCE-G1; 4 Data Foundry; 5 training engine; 6 first checkpoint; 7 inference and chat; 8 evaluation (history recorded); 9 instruct stage (separate lineage entry).

## Active stage / next action

Stage 10 (optimisation) has not started: profile first. Highest-value next step is data, not architecture: broaden the language/science/math corpus (more public-domain and permissively licensed sources through the Data Foundry), retrain, and compare against the recorded baseline; then run `trail_small` on a GPU.

## Reproduce

```
cd TRAIL && pip install -e . && python scripts/fetch_corpus.py
trail data prepare && trail train && trail evaluate checkpoints/trail-micro
trail instruct checkpoints/trail-micro --out checkpoints/trail-micro-instruct && trail chat checkpoints/trail-micro-instruct
```
