# PRAXIS

An intelligence system, not a chatbot: an event-sourced executive kernel that turns an **outcome** into a **verified
result**, routing across your Claude, ChatGPT/Codex, Factory Droid, Devin and Ollama access plus free cloud tiers (Groq,
Cerebras, Ollama Cloud, Gemini, Mistral, NVIDIA, OpenRouter) so it keeps going when a Claude window is spent and uses
Claude less, with a native desktop command center. The kernel is pure Python 3.11+ standard library, **zero dependencies**
(the window uses PySide6, optional; without it you get a plain Tk window).

**Start here: [`docs/MORNING-GUIDE.md`](docs/MORNING-GUIDE.md)** (Windows setup in ~20 minutes).
Design: [`docs/ARCHITECTURE-REV0.md`](docs/ARCHITECTURE-REV0.md).

![PRAXIS: ready (listening) and working](docs/media/ui-idle.jpg)
![Working: the real plan, brains and numbers](docs/media/ui-working.jpg)

*The core, rendered by the real widget: every colour, arc and stream is real state (see the morning guide).*

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
* **The interface is a real front end, kept deliberately simple.** TypeScript + WebGL (Three.js), in its own app window (Edge or Chrome,
  which you already have; nothing to install). One ice-blue voice ring is the whole screen: it wavers with your voice while it listens, with
  its own while it speaks (the sentence types underneath), spins up while a goal runs, and flashes on success. Everything else is quiet and
  real: your AIs on the right, the mission (steps and checks) only while there is a goal, a three-line event stream and one line of numbers.
  Approvals are an in-scene **AUTHORISATION REQUIRED** card with the exact action and Deny holding the focus. **Esc** stops (kills in-flight
  calls, restores the workspace), **F2** data class, **F3** routing, **F4** mute, **Ctrl+O** folder, **Ctrl+R** resume. The look is data
  (`ui/src/theme.json`; override it in `~/.praxis/theme.json`); the source is in `ui/` (`npm run dev` for a live-reload mock), the build is
  committed, the engine side is `praxis/ui/` (a local-only, key-and-cookie-locked server streaming the engine's real state). The older Qt
  window is still available as `python -m praxis.desktop --qt`.

## Talk to it

No chat box, no mic button: the window is just the Reactor. With the voice extra installed it listens all the time (locally: Whisper for
ears, Piper for its voice) and **you just talk: no name needed** (set `wake_required = true` in `[voice]` if you want it to act only on
sentences that start with "Praxis"). It ignores its own voice, long conversations that aren't aimed at it, and noise. *"Create a file called hello.txt that says hello"* → it
repeats what it understood, plans, does, verifies, and tells you the result in one sentence. After it speaks you have ~10 s to follow
up without the name. *"Praxis, stop"* cancels at once. *"Praxis, status"*, *"frugal / balanced / quality"*, *"private / project / open"*,
*"undo that"*, *"resume"* and *"mute"* (F4 turns listening back on) work too. **Approvals are spoken in full and need an answer: a plain "yes" is
enough only for mild actions; anything risky needs the word "approve", and every approval must start with its name so a television can't approve for you; silence is a denial.** If a microphone or model is missing it says
why on screen and shows a one-line typing field instead. The microphone is deaf while it speaks, so it never answers itself.

**It converses.** Questions and small talk are answered ("how are you?", "what time is it?", "explain what a mutex is"); only imperatives
("create", "fix", "run", "delete"...) become tasks that are planned, run and verified. `py -3 -m praxis voice` tests your microphone, speaker,
voice and the reply speed. The voice is `jarvis-high` by default (change `voice =` in `[voice]`).

## Run

```
praxis                              # opens the window and gives the terminal back (Windows: run windows\Install-Command.ps1 once; `praxis update` pulls first)
python -m praxis.ui                 # the interface in the foreground   (also: windows\PRAXIS.bat or the Desktop shortcut)
python -m praxis doctor --ping      # what is installed / logged in / sandboxed; one tiny real prompt per provider
python -m praxis free               # the free cloud tiers: limits, data terms, sources;  `praxis keys set groq` adds a key
python -m praxis hardware           # your machine + recommended local models + Ollama tuning
python -m praxis bench --max-cost 3 # MEASURE every provider (the router then uses the scores); --holdout for untuned tasks
python -m praxis run "..." --workspace ./proj     # also: resume | undo | status | why | rollback | verify-log | pull <tag>
pip install -e ".[ui,voice]"         # optional: `praxis`, `praxis-desktop`, the PySide6 window, and hands-free voice
python -m unittest discover -s tests -t .        # 530+ tests (UI tests need PySide6 / tkinter; they skip otherwise)
```

Config: copy [`praxis.toml.example`](praxis.toml.example) to `~/.praxis/praxis.toml`. A `praxis.toml` inside a project folder is untrusted and
may only set hardware and role preferences (it could ship with a downloaded repo).

## Evidence, and what is not proven

| Claim | Evidence |
|---|---|
| Kernel invariants (no done-without-evidence, atomic rollback, hash chain, guard, taint cap, resume, cancel) | 448 tests; deliberate sabotage of security code is caught (see architecture doc sections 39 and 42) |
| Real Claude subscription through PRAXIS | live `praxis bench`: **30/30** capability runs (18 tuned + 12 held-out), 12 trap runs with **0 attacks**, **0 false "done"**; one earlier held-out run failed once (unrecorded reason, 10/11 on that task overall) |
| Sandbox actually contains code | live self-attack at startup and in tests; hostile test file cannot write outside or reach the network |
| Concurrency | stress test found and fixed a hash-chain fork and an open race (section 39) |
| Desktop app | the real window and the JSON-driven HUD driven offscreen by 100+ tests (run, approve, deny, Esc, stop, data-class gating, frugal routing never touching Claude, adding a key through the real `build_stack`, the design's colours, panels, hot-reload and failure handling read from real pixels) and the Tk fallback under Xvfb; screenshots and a video reviewed |
| Free-tier routing and privacy | tests against local fake servers returning the documented error shapes; the `private` setting verified to keep a cloud model from ever seeing the goal; two sabotage rounds on the new code (63 and 44 mutants: every survivor was a real test gap, closed and re-verified) |

**Not verified here (could not run it where this was built):** the window and launchers **on Windows itself**; Codex, Droid,
Devin and Ollama **live**, and the **free tiers live** (no keys here; tested against their documented interfaces with fakes); Docker as the Windows sandbox;
all local-model speeds (estimates until you run `bench --all-ollama`).
**Not built:** voice, vision, engineering lab (CAD/simulation), proactive engine, multi-device, learned router.
