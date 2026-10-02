# PRAXIS

An intelligence system, not a chatbot: an event-sourced executive kernel that turns an outcome into a
**verified** result, routing across your Claude, ChatGPT/Codex, Factory Droid, Devin and Ollama access.
Design: [`docs/ARCHITECTURE-REV0.md`](docs/ARCHITECTURE-REV0.md). Pure Python 3.11 stdlib, zero dependencies.

## What it does

```
goal → recall (memory) → plan (model A) → observe files (read-only, labeled UNTRUSTED)
     → critique (model B ≠ A) → checkpoint → guard → sandboxed step → verify → report
     └─ any failure → atomic rollback; replans need a human; kill -9 mid-goal → `praxis resume`
```

* **Guard** (deterministic, fail-closed): Class 0–5. Code execution is Class 2 *only inside an OS sandbox that
  passed a live self-attack* (no writes outside the workspace, no network); otherwise Class 4 (you approve).
  Anything derived from untrusted content is hard-capped at Class 2; no approval can lift that.
* **Verification gate**: no "VERIFIED" without a passing, real success check. Verifier commands go through the Guard too.
* **Event log**: hash-chained SQLite; `why <event>` explains any action; tamper/deletion is detected.
* **Multi-model**: planner and critic are different providers whenever two exist; rate-limited subscriptions
  cool down and the router falls back; `private` data only ever reaches local Ollama.
* **Memory**: past goals and *failures with reasons* are recalled by relevance and shown to the planner.

## Setup (once, on your machine)

| Tool | How PRAXIS uses it | You do |
|---|---|---|
| **Claude** subscription | `claude -p` (headless). `ANTHROPIC_API_KEY` is stripped so it never bills an API key | install Claude Code, run `claude`, log in |
| **ChatGPT / Codex** | `codex exec` (read-only for planning, `workspace-write` for delegation). `OPENAI_API_KEY`/`CODEX_API_KEY` stripped | install Codex CLI, `codex login` |
| **Factory Droid** | `droid exec` (read-only default; delegation = `--auto low`) | install droid, `export FACTORY_API_KEY=...` |
| **Devin** | v3 API sessions, delegate-only, Class 4 (spends ACUs) | `DEVIN_API_KEY` (service user `cog_…`), `DEVIN_ORG_ID`, `enabled = true` in config |
| **Ollama** | `/api/chat`, local & private; picks the best installed model that fits your memory | install Ollama, `ollama pull <model>` |
| **Sandbox** | Linux: bubblewrap or rootless `unshare`; any OS: Docker | `praxis doctor` tells you what it found |

```bash
python3 -m praxis doctor --ping        # what's installed, logged in, sandboxed; sends 1 tiny real prompt each
python3 -m praxis models               # Ollama models: fits? measured? which one is selected
python3 -m praxis bench --all-ollama   # MEASURE every provider/local model; scores drive routing
python3 -m praxis bench --holdout      # tasks never used for tuning; report this number
python3 -m praxis run "fix the failing tests in calc.py" --workspace ./proj
python3 -m praxis run "..." --private  # local models only
python3 -m praxis resume               # recover a goal killed mid-flight
python3 -m praxis why <event-id> | verify-log | rollback <checkpoint> | status
```

Config: copy [`praxis.toml.example`](praxis.toml.example). Tests: `python3 -m unittest discover -s tests -t .`

## Evidence (what is measured, what is not)

| Claim | Evidence |
|---|---|
| Kernel invariants (no done-without-evidence, rollback, hash chain, guard, taint cap, resume) | 110+ tests; **15/15** deliberate mutations of security-critical code are caught |
| Sandbox actually contains code | self-attack at startup + hostile-test-file test: outside write and network both fail |
| **Real Claude subscription through PRAXIS** | live `praxis bench`: see numbers in the architecture doc §38 (tuned set and held-out set reported separately) |
| Kill -9 mid-goal resumes with zero model calls | real process death test (`os._exit`), final state + log chain verified |

**Not verified live in this build (no access here): Codex, Droid, Devin, Ollama.** Their adapters are tested against
the *documented* interfaces with recording fake binaries and local HTTP servers: that proves how PRAXIS invokes them
(flags, stdin, env stripping, parsing, polling, cooldown) but not that the vendors behave as documented today.
Run `praxis doctor --ping` then `praxis bench` on your machine: it measures them for real and records the scores.

Not built: voice, vision, engineering lab (CAD/sim), proactive engine, graphical UI, multi-machine. See the roadmap.
