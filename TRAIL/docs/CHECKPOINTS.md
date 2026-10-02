# Checkpoints

```
checkpoint_000500/
  model.safetensors      weights (metadata: architecture, generation, trail_version)
  optimizer.pt           AdamW state
  scheduler.pt           schedule parameters
  trainer_state.json     step, tokens, best_val, seed, config digest, precision, stage
  architecture.json      the exact ModelConfig + {"trail": generation, version, stage, base checkpoint hash for INSTRUCT}
  tokenizer/             the tokenizer the weights were trained with
  dataset_manifest.json  what data was used
  metrics.json           latest metrics
  COMPLETE               written last; a directory without it is ignored (crashed write)
```

Written to a `.partial` directory then renamed; an existing checkpoint is never overwritten; the newest `keep_checkpoints` are kept (add a `KEEP` file to pin one).
`trail train` resumes from the latest complete checkpoint, bit-for-bit (tested). INSTRUCT checkpoints live in their own run directory and record the hash of the BASE weights they started from.
