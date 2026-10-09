# Decision Register (M0)

Each row: what is open, the proposed choice, the exact empirical method that closes it, and who decides. "Owner" means owner approval is required. No row is closed by M0.

| # | Decision | Proposal | Empirical method to close | Milestone | Decider |
|---|---|---|---|---|---|
| D1 | Hardware reality | Treat RTX 3050 4 GB etc. as unverified | Run `scripts/audit_windows.ps1`; record in HARDWARE_PROFILE | **now (owner action)** | Owner |
| D2 | Mac availability | Assume none until stated | Owner states Mac model/macOS/chip; Apple Developer Program enrolment status | before M12M planning | Owner |
| D3 | Tokenizer | BPE vs unigram | Train both on the M2 corpus; compare fertility, round-trip, Unicode/code-indent tests, memory | M2 | Claude proposes |
| D4 | Model size / topology | 15–40M, ctx 256–512 | M3 sweep: params × seq × micro-batch → peak VRAM, tok/s over ≥30 min sustained | M3 | Claude proposes, owner approves |
| D5 | Training corpus | Permissively-licensed English text + code subset | Rights review per source into the ledger; leakage/dedupe report | M2 | Owner (legal basis) |
| D6 | Precision | bf16/fp16 autocast if stable | `torch.cuda.is_bf16_supported()`, NaN/divergence runs | M3 | Claude |
| D7 | First GUI | Localhost React web UI | M1 ADR + a11y test | M1 | Owner |
| D8 | DB | SQLite + FTS5 | Migration/crash-recovery smoke test | M1 | Claude |
| D9 | Speech engines | Local, permissive-licence STT/TTS | WER on lawful fixtures, latency, footprint, redistribution licence | M7 | Owner |
| D10 | Desktop shell | No choice yet | Prototype Electron/Tauri/native; score IPC security, a11y, signing, auto-update | after R2 | Owner |
| D11 | Hyper-V / VM testing | Use if available | `audit_windows.ps1` Hyper-V + edition lines | M1 | Owner |
| D12 | Test durations | 8 h / 24–48 h / 72 h per blueprint | Run `commit` baseline, derive minimum op counts and leak-slope thresholds **before** qualifying runs | M1 → M11T | Owner |
| D13 | Promotion thresholds | Set after first baseline | Frozen-baseline eval at M4; tolerance chosen *before* candidates are scored | M4 | Owner |
| D14 | Coding parity protocol | Held-out, matched-budget comparison (see TESTBENCH_ARCHITECTURE §9) | Pre-registration document; reference versions pinned on test date | M11P | Owner |
| D15 | Reference-system access | Need legitimate Claude Code and ChatGPT coding access for comparison | Owner confirms subscriptions/terms permit benchmarking use | M11P | Owner |
| D16 | Signing | Windows: code-signing cert (EV/OV or Azure Trusted Signing, to evaluate); macOS: Developer ID + notarisation | Cost/availability review; key custody plan (SEC-007) | before M12W/M | Owner |
| D17 | Domain / brand | "Zalius" availability unchecked | Trademark and domain search (REPRO-001: a novel name ≠ rights) | before R5 | Owner |
| D18 | Voice scope in browser | Browser mic via standard APIs | Capability test in Playwright with fixture audio | M7 | Claude |
| D19 | Hosted inference | Deferred (DEP-004) | Out of scope until R6 | — | Owner |
| D20 | Repo location & name | Currently `ttvmarss/ai-agent`; blueprint layout is `zalius/` root | Owner confirms whether to use this repo as the monorepo root | M1 | Owner |

## Facts the M0 session could not establish

- Everything about the owner's PC (D1).
- Whether openai.com primary pages say exactly what mirrors report (see GPT_FOUNDATIONS).
- Current PyTorch/CUDA support matrix for the owner's GPU and Python version.
