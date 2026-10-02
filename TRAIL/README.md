# TRAIL

A model lineage built from scratch: random initial weights, its own tokenizer, its own architecture (TCE-G1), its own training stack and runtime. It does not wrap,
fine-tune or call any other model. V1 is real but tiny (5M parameters, trained on a CPU in about an hour): the point is the machinery, which scales by configuration.

```
text -> TRAIL tokenizer -> TCE-G1 + TRAIL weights -> TRAIL inference engine -> text
```

```
pip install -e .
trail hardware                                   # what this machine can train
python scripts/fetch_corpus.py                   # assemble the local corpus (public-domain / permissive; provenance recorded)
trail data prepare --config configs/trail_micro.yaml
trail train --config configs/trail_micro.yaml    # resumes automatically if interrupted
trail evaluate checkpoints/trail-micro
trail chat checkpoints/TRAIL-V1-INSTRUCT         # shipped, committed checkpoint; works offline
```

Read `docs/CURRENT_STATE.md` first (honest status and metrics), then `docs/ARCHITECTURE.md`. Scales: `configs/trail_{micro,small,base,large,frontier}.yaml`
(only micro has been trained). Everything unbuilt (memory, experts, deliberation, verification, multimodality, world model) is an interface that refuses to run
until it exists. Tests: `python -m unittest discover -s tests -t .` (54 tests, ~10 s).
