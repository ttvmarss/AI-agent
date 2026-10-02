# PRAXIS

An intelligence system, not a chatbot: an event-sourced executive kernel that turns an **outcome** into a **verified
result**, routing across your Claude, ChatGPT/Codex, Factory Droid, Devin and Ollama access plus free cloud tiers (Groq,
Cerebras, Ollama Cloud, Gemini, Mistral, NVIDIA, OpenRouter) so it keeps going when a Claude window is spent and uses
Claude less, with a native desktop command center. The kernel is pure Python 3.11+ standard library, **zero dependencies**
(the window uses PySide6, optional; without it you get a plain Tk window).

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
* **Routing**: per-model instances with tiers; once measured, the **cheapest model within 0.05 of the best score wins**.
  **Frugal mode** goes local, then free tiers, then Claude small to large, and a cheaper model whose work fails
  verification is retried by the next one up (workspace restored first). Rate limits rest until the provider's stated reset,
  then the next model serves; per-model usage and budgets are tracked (5h / 24h / 7d).
* **Privacy as a hard filter**: a goal is `private` (local only), `project` (+ providers that document no training) or `open`
  (+ free tiers that may train); an open tier never receives a prompt containing a credential. Every free tier carries its
  documented data terms and the source of its limits (`python -m praxis free`).
* **Hardware-aware local models**: reads your real VRAM/RAM, models speed with bandwidth physics (MoE vs dense), then
  *measures* tokens/s and quality. Dated, sourced catalog of Ollama models.
* **Desktop command center** (PySide6): a live core whose colour, progress ring and orbiting provider dots are real state (who is
  being called right now, whose allowance is nearly spent, who is resting, who this goal may not use); the plan as a dependency
  graph; **Fuel** page with the failover ladder and usage per model; DATA and FRUGALITY switches in the header; timeline with
  "why"; models (download + benchmark); live CPU/RAM/GPU/VRAM; approval dialogs show the exact action and default to Deny;
  **STOP** kills in-flight calls and restores the workspace.

## Run

```
python -m praxis.desktop            # the desktop app   (Windows: windows\PRAXIS.bat or the Desktop shortcut)
python -m praxis doctor --ping      # what is installed / logged in / sandboxed; one tiny real prompt per provider
python -m praxis free               # the free cloud tiers: limits, data terms, sources;  `praxis keys set groq` adds a key
python -m praxis hardware           # your machine + recommended local models + Ollama tuning
python -m praxis bench --max-cost 3 # MEASURE every provider (the router then uses the scores); --holdout for untuned tasks
python -m praxis run "..." --workspace ./proj     # also: resume | status | why | rollback | verify-log | pull <tag>
pip install -e ".[ui]"              # optional: `praxis`, `praxis-desktop` and the PySide6 command-center window
python -m unittest discover -s tests -t .        # 357 tests (UI tests need PySide6 / tkinter; they skip otherwise)
```

Config: copy [`praxis.toml.example`](praxis.toml.example) to `~/.praxis/praxis.toml`. A `praxis.toml` inside a project folder is untrusted and
may only set hardware and role preferences (it could ship with a downloaded repo).

## Evidence, and what is not proven

| Claim | Evidence |
|---|---|
| Kernel invariants (no done-without-evidence, atomic rollback, hash chain, guard, taint cap, resume, cancel) | 357 tests; deliberate sabotage of security code is caught (see architecture doc sections 39 and 42) |
| Real Claude subscription through PRAXIS | live `praxis bench`: **30/30** capability runs (18 tuned + 12 held-out), 12 trap runs with **0 attacks**, **0 false "done"**; one earlier held-out run failed once (unrecorded reason, 10/11 on that task overall) |
| Sandbox actually contains code | live self-attack at startup and in tests; hostile test file cannot write outside or reach the network |
| Concurrency | stress test found and fixed a hash-chain fork and an open race (section 39) |
| Desktop app | the real window driven offscreen by 24 tests (run, approve, deny, Esc, stop, data-class gating, frugal routing never touching Claude, adding a key through the real `build_stack`) and the Tk fallback under Xvfb; screenshots reviewed |
| Free-tier routing and privacy | tests against local fake servers returning the documented error shapes; the `private` setting verified to keep a cloud model from ever seeing the goal |

**Not verified here (could not run it where this was built):** the window and launchers **on Windows itself**; Codex, Droid,
Devin and Ollama **live**, and the **free tiers live** (no keys here; tested against their documented interfaces with fakes); Docker as the Windows sandbox;
all local-model speeds (estimates until you run `bench --all-ollama`).
**Not built:** voice, vision, engineering lab (CAD/simulation), proactive engine, multi-device, learned router.
