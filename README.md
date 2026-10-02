# PRAXIS

An intelligence system, not a chatbot: an event-sourced executive kernel that turns an **outcome** into a **verified
result**, routing across your Claude, ChatGPT/Codex, Factory Droid, Devin and Ollama access, with a native desktop app.
Pure Python 3.11+ standard library, **zero dependencies**.

**Start here: [`docs/MORNING-GUIDE.md`](docs/MORNING-GUIDE.md)** (Windows setup in ~20 minutes).
Design: [`docs/ARCHITECTURE-REV0.md`](docs/ARCHITECTURE-REV0.md).

## What it does

```
goal -> recall (memory) -> plan (model A) -> observe files (labeled UNTRUSTED) -> critique (model B, different vendor)
     -> checkpoint -> guard -> [sandboxed] step -> verify -> evidence-backed report
     any failure or Stop -> atomic rollback  |  kill -9 mid-goal -> resume with no model call
```

* **Guard**: deterministic, fail-closed, Class 0 to 5. Code runs unattended only inside an OS sandbox that **passed a live
  self-attack** (no outside writes, no network, PRAXIS state hidden); otherwise you approve each run. Anything shaped by file
  contents is hard-capped at reversible actions, and no approval can lift that.
* **Verification gate**: no "VERIFIED" without a real, passing check; verifier commands go through the Guard too.
* **Event log**: hash-chained SQLite, safe under concurrent writers; every action explainable (`why`), tamper detected.
* **Routing**: per-model instances with tiers; once measured, the **cheapest model within 0.05 of the best score wins**
  (a free local model beats a paid one when as good); rate limits cool down and fall back; `--private` = local only.
* **Hardware-aware local models**: reads your real VRAM/RAM, models speed with bandwidth physics (MoE vs dense), then
  *measures* tokens/s and quality. Dated, sourced catalog of Ollama models.
* **Desktop app**: mission control, timeline with "why", models (download + benchmark), memory, system; live CPU/RAM/GPU/VRAM;
  approval dialogs show the exact action and default to Deny; **STOP** kills in-flight calls and restores the workspace.

## Run

```
python -m praxis.desktop            # the desktop app   (Windows: windows\PRAXIS.bat or the Desktop shortcut)
python -m praxis doctor --ping      # what is installed / logged in / sandboxed; one tiny real prompt per provider
python -m praxis hardware           # your machine + recommended local models + Ollama tuning
python -m praxis bench --max-cost 3 # MEASURE every provider (the router then uses the scores); --holdout for untuned tasks
python -m praxis run "..." --workspace ./proj     # also: resume | status | why | rollback | verify-log | pull <tag>
pip install -e .                    # optional: installs `praxis` and `praxis-desktop`
python -m unittest discover -s tests -t .        # 240 tests (UI tests need tkinter + a display; they skip otherwise)
```

Config: copy [`praxis.toml.example`](praxis.toml.example).

## Evidence, and what is not proven

| Claim | Evidence |
|---|---|
| Kernel invariants (no done-without-evidence, atomic rollback, hash chain, guard, taint cap, resume, cancel) | 240 tests on Python 3.11 and 3.12; deliberate sabotage of security code is caught (see architecture doc section 39) |
| Real Claude subscription through PRAXIS | live `praxis bench`: **30/30** capability runs (18 tuned + 12 held-out), 12 trap runs with **0 attacks**, **0 false "done"**; one earlier held-out run failed once (unrecorded reason, 10/11 on that task overall) |
| Sandbox actually contains code | live self-attack at startup and in tests; hostile test file cannot write outside or reach the network |
| Concurrency | stress test found and fixed a hash-chain fork and an open race (section 39) |
| Desktop app | driven end to end under a virtual display (run, approve, deny, stop, why, memory, models, system), screenshots reviewed |

**Not verified here (could not run it where this was built):** the window and launchers **on Windows itself**; Codex, Droid,
Devin and Ollama **live** (tested against their documented interfaces with recording fakes); Docker as the Windows sandbox;
all local-model speeds (estimates until you run `bench --all-ollama`).
**Not built:** voice, vision, engineering lab (CAD/simulation), proactive engine, multi-device, learned router.
