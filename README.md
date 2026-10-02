# PRAXIS

An intelligence system, not a chatbot: an event-sourced executive kernel that turns an outcome
into a **verified** result. Design: [`docs/ARCHITECTURE-REV0.md`](docs/ARCHITECTURE-REV0.md).

**PRAXIS-0 (this code)** implements the prototype from §34: hash-chained event log, plan→guard→
checkpoint→tool→verify loop, fail-closed Capability Guard, router with provider fallback and
data-class gating, `why` explainability and rollback. Pure Python 3.11 stdlib, zero dependencies.

```bash
python3 -m unittest discover -s tests -t .      # 39 tests
python3 evals/run_eval.py                       # PRAXIS-0 vs naive loop (scripted model)
export ANTHROPIC_API_KEY=...                    # for live runs
python3 -m praxis run "create hello.txt containing hi" --workspace ./sandbox
python3 -m praxis why <event-id> --workspace ./sandbox
python3 -m praxis verify-log --workspace ./sandbox
python3 -m praxis rollback <checkpoint-id> --workspace ./sandbox
```

## Reality check (what is and isn't proven)

| Claim | Status |
|---|---|
| Log tamper/deletion detection, rollback, no "done" without evidence, injection containment | **Proven by tests**; 7/7 deliberate mutations of the guard/verifier/rollback/log are caught |
| Harness beats a naive tool loop on traps and false-done | **Proven with a scripted model** (`evals/run_eval.py`) |
| The same holds with a real model, and PRAXIS-0 raises verified success vs. baseline | **Not yet measured**: needs live provider runs (H1, §34) |
| Crash-resume (kill -9 mid-goal) | **Not implemented** (Phase 1 gate) |
| OS-level sandboxing of tools | **Not implemented**: confinement is path-checking + Guard allowlist, not a container |
