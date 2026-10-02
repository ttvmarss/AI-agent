# PRAXIS: first run on your PC

Target: **Windows desktop, Ryzen 7 7700, 32 GB DDR5, RTX 3050** (the app reads your real VRAM, so it works for both the 8 GB and the 6 GB card).
About 20 minutes of setup, then you launch a native desktop window. No browser.

## 1. Get the code

On GitHub, open the repository `ttvmarss/ai-agent`, switch to the branch **`claude/praxis-architecture-rev0`**, then either `git clone` it or use **Code → Download ZIP** and unzip it (for example to `C:\PRAXIS`).

## 2. Python (the only hard requirement)

Install **Python 3.11 or newer** from <https://www.python.org/downloads/> and **tick "Add python.exe to PATH"** (the python.org installer includes Tk, which the window needs). PRAXIS itself has **zero** pip dependencies.

Fastest path, from the folder you unzipped:

```
powershell -ExecutionPolicy Bypass -File windows\Install-PRAXIS.ps1
```

It checks everything below, offers to install Python, creates a **PRAXIS** shortcut on your Desktop, and runs `praxis doctor`. Or just double-click `windows\PRAXIS.bat`.

## 3. Sign in to the tools you have (each is optional; PRAXIS uses whatever it finds)

| Tool | Install (from the vendors' docs) | Sign in |
|---|---|---|
| **Claude** subscription | PowerShell: `irm https://claude.ai/install.ps1 \| iex`  (or `winget install Anthropic.ClaudeCode`) | run `claude`, follow the browser prompt |
| **ChatGPT / Codex** | PowerShell: `powershell -ExecutionPolicy ByPass -c "irm https://chatgpt.com/codex/install.ps1 \| iex"` *(command from third-party guides; the official page is <https://learn.chatgpt.com/docs/cli>, check it)* or `npm install -g @openai/codex` | `codex login` → "Sign in with ChatGPT" |
| **Factory Droid** | follow <https://docs.factory.com/cli/getting-started/quickstart> *(I could not read the exact Windows command from their docs)* | set the `FACTORY_API_KEY` environment variable |
| **Devin** | nothing to install | set `DEVIN_API_KEY` and `DEVIN_ORG_ID`, then `enabled = true` under `[providers.devin]` in your user config (below). Every use asks your approval (it spends ACUs) |
| **Ollama** | <https://ollama.com/download/windows> (needs NVIDIA driver **551.61+**) | none; runs in the tray at `localhost:11434` |
| **Docker Desktop** *(optional but recommended)* | <https://www.docker.com/products/docker-desktop/> | lets PRAXIS run code in a **proven** sandbox. Without it, anything that executes code asks your approval each time (safe, just more clicks). Run `docker pull python:3.11-slim` once |

PRAXIS **strips** `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `CODEX_API_KEY` from the environment of the Claude and Codex calls, so they use your *subscription login* and can never silently bill an API key.

## 4. Local models for your hardware (do this while the downloads run)

Run `python -m praxis hardware` (or open **Models** in the app). For an RTX 3050 + 32 GB DDR5 the research says:

* Your GPU's 6 to 8 GB VRAM holds only small models. Anything bigger spills into system RAM, and speed then follows RAM bandwidth.
* **Dense 27B models (Qwen 3.6/3.8 27B) would crawl at roughly 2 to 3 tokens/s here.**
* **MoE models with about 3B active parameters are the sweet spot**: they read only ~2 GB per token, so DDR5 carries them at an *estimated* 15 to 22 tokens/s, and 32 GB holds them.

| Role | Model (exact Ollama tag) | Size | Why | Est. speed |
|---|---|---|---|---|
| daily driver | `qwen3.6:35b-a3b-coding` | 23.5 GB | 35B MoE, 3B active, coding tuned | ~19 tok/s |
| agentic alternatives | `laguna-xs-2.1` (20 GB), `north-mini-code-1.0` (19 GB) | | MoE built for agentic coding | ~21 tok/s |
| fast helper | `granite4.2:8b` (5.3 GB; on a 6 GB card use `granite4.2:3b`, 2.2 GB) | | fits fully in VRAM | ~24 tok/s |
| deep thinker | `qwen3.8:27b` / `granite4.2:30b` | 18 GB | dense; slow, for hard background work | ~2 tok/s |

*Sizes and tags were read from each model's Ollama library page on 2026-10-02. **Speeds are physics estimates, not measurements.***

```
ollama pull qwen3.6:35b-a3b-coding      (24 GB download)
ollama pull granite4.2:8b
python -m praxis bench --all-ollama      (measures real quality AND speed; the router then uses the measurements)
```

Recommended Ollama settings for a small-VRAM card (from Ollama's FAQ). Set as Windows user environment variables, then restart Ollama:
`OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0`, `OLLAMA_MAX_LOADED_MODELS=1`. Models are stored in `%HOMEPATH%\.ollama`; set `OLLAMA_MODELS` to move them to a bigger drive.

### Your config file (optional)

Copy `praxis.toml.example` to **`%USERPROFILE%\.praxis\praxis.toml`**. This is the only place provider hosts, sandbox, privacy and limits can be set. A `praxis.toml` inside a project folder is deliberately **untrusted** (a downloaded repo could ship one that points your "local" model at someone else's server), so it may only set `[hardware]`, `[role_tiers]` and `[roles]`.

## 5. First launch

Double-click the **PRAXIS** shortcut. The window opens on **Mission**:

1. **Models → Download** the recommended models if you have not yet. **System** shows each provider, its measured score and cost, and the sandbox state.
2. Run **`python -m praxis bench --max-cost 3`** (or the benchmark button on Models). This sends test tasks to every available model and writes measured quality, speed and cost to the registry. After that the router picks **the cheapest model that is as good as the best**. Heads-up: this uses real subscription usage; the `--max-cost` cap stops new providers once the estimate passes it.
3. Try a safe first goal on a scratch folder (**Open folder…** → make a new empty folder):
   * *"Create hello.txt containing exactly: Hello, Stark"*
   * *"Write a Python function slugify(text) in slug.py with a unit test, and run the tests."*
   * *"Read notes.txt and write a one-sentence summary to summary.txt."*

## 6. How to use it safely

* **STOP (Ctrl+.)** is always live. It kills in-flight model calls, stops before the next step, and **restores the workspace** to how it was before the goal.
* **Approval dialogs show the exact action** and default to **Deny**. Anything that sends your files to a cloud agent, spends money, or runs code without a proven sandbox asks you first. Closing the dialog or pressing Esc is a refusal.
* **A plan built from file contents can never exceed reversible actions**, even if you click "approve": this is what stops a malicious line inside a document from driving the machine.
* **What VERIFIED means:** the goal passed the checks listed under *Evidence*, and the Guard allowed every step. It does **not** prove the checks match what you meant. If a goal is ambiguous the model may write checks that encode a misreading (in a live test, "exactly: Hello, Stark. Then create..." produced `Hello, Stark.` with the period). Read the Evidence for important work, state exact values, and keep the *Second-opinion critic* on when you have two vendors installed.
* **Timeline → "Why did you do that?"** shows the causal chain for any action. **Verify log integrity** proves the history was not edited.
* **Resume**: if the app or PC dies mid-goal, the next launch offers *Resume interrupted goal*.
* Everything is stored in `<your folder>\.praxis\` (event log, checkpoints, registry). PRAXIS refuses to read or write that folder, `.git`, or `praxis.toml` on a plan's behalf.

## 7. What is verified, and what is not

**Verified in the build environment (Linux):** 258 automated tests, all green on Python 3.11 and 3.12; dozens of deliberate sabotage checks on the security-critical code were caught (every test gap they exposed was fixed and re-checked); real **Claude** subscription runs through PRAXIS: 30/30 capability tasks (18 tuned + 12 held-out), 12 trap runs with 0 attacks, 0 false "done" claims (one earlier held-out run, 1 of 15, failed once for an unrecorded reason and did not reproduce in 4 reruns); the desktop window was launched, driven and screenshotted under a virtual display.

**NOT verified, because it could not be run where this was built. Expect to find bugs here, and please tell me what breaks:**

* The window **on Windows itself** (layout/DPI/fonts), the `.bat` and `.ps1` launchers (no PowerShell available), and Docker as the Windows sandbox.
* **Codex, Droid, Devin and Ollama live.** They are tested against their *documented* interfaces with recording fake programs and local servers, which proves how PRAXIS calls them but not how the vendors behave today. `python -m praxis doctor --ping` and `bench` are how you find out. Droid's JSON output format is not documented in detail (the parser is defensive).
* The **speed numbers** for your GPU are estimates until you run `bench --all-ollama`.

## 8. If something goes wrong

| Symptom | Do this |
|---|---|
| Window will not open | `python -m praxis.desktop` in a terminal shows the error. "Needs Tk" → reinstall Python from python.org |
| A provider shows `SKIPPED` | `python -m praxis doctor` prints the reason (not installed / not logged in / Ollama not running) |
| Everything asks for approval | No proven sandbox: install Docker Desktop and run `docker pull python:3.11-slim`, then System → *Re-run sandbox self-attack* |
| Local model is slow | System/Models show measured tok/s; lower `num_ctx` in your user `praxis.toml`, set the Ollama variables above, or pick the 8B helper |
| Wrong GPU numbers | set `[hardware] vram_gb / ram_gb / ram_bw_gbps` in `%USERPROFILE%\.praxis\praxis.toml` (see `praxis.toml.example`) |
| Stuck on STOPPING | it is waiting for a model call to die; if a CLI ignores the kill, close the window (it will ask) |
