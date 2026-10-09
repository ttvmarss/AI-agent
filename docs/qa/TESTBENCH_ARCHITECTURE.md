# Testbench Architecture (M0 design only)

Nothing in this document has been built or run. No marathon tests were run, no services installed.

## 1. Tool selection (candidates; versions/licences to be confirmed in M1 via `pip index`/`npm view`, not recalled)

| Layer | Choice | Why | Caveat |
|---|---|---|---|
| Python model/service | pytest (+ hypothesis for tokenizer property tests) | standard, JUnit output | pin versions |
| .NET bridge | xUnit | standard, JUnit-compatible loggers | .NET SDK absent here; verify on PC |
| Browser | Playwright (Chromium present in M0 container; Windows install to verify) | headless, traces, video, screenshots | does not validate native apps |
| Windows desktop | purpose-built C# harness over UI Automation (FlaUI is a candidate wrapper — maintenance status to be checked before adoption, per TB-004) | real native control | needs interactive desktop session; run in VM/dedicated user |
| macOS desktop | XCTest/XCUITest + Accessibility APIs on a real Mac | native | **requires Mac hardware (not known to exist)** |
| Orchestration | Python runner `testbench/run.py` + PowerShell entry `testbench/run.ps1`; Windows Task Scheduler for unattended runs (TB-025) | no new infrastructure | scheduler task is created only after owner enables it |
| Reports | JSON + JUnit + self-contained HTML | TB-005 | redact chats/secrets |

## 2. TB-001..TB-027 design map

| TB | Design | Milestone |
|---|---|---|
| 001 Orchestrator | Job spec (YAML): repo rev, checkpoint id, platform/build id, profile, fixture versions, permissions, resource budget, expected result. Runner supervises worker processes, timeouts, seeds, resume, cancel | M1 |
| 002 Traceability | `REQUIREMENTS_MATRIX.md` regenerated from test results; states planned…passing; CI fails if an `implemented` row has no test | M1 |
| 003 Fixtures | Temp DBs, scratch repos, fake docs, throwaway browser profiles, `HKCU\Software\ZaliusTest`, local web server, fixture audio; Hyper-V VM if D11 permits, else non-admin harness | M1+ |
| 004 Toolchain | Section 1 above | M1 |
| 005 Reporting | Result schema with PASS/FAIL/SKIP/FLAKY/BLOCKED; a missing test is reported `MISSING`, never green | M1 |
| 006–008 Model/data/training/independence | pytest suites; network-off tests via process-level egress block + socket-monkeypatch tripwire; sealed eval hashes | M3–M4 |
| 009–010 UI/storage/memory | Playwright against real backend + isolated DB | M5–M6 |
| 011 Voice | fixture WAVs; physical-device tests `SKIP(reason)` until hardware run | M7 |
| 012–013 Windows/agents/API | C# harness; disposable fixtures; denial paths | M8–M10 |
| 014 Security | path traversal, injection, IPC forgery, fake manifests, dependency audit | M5+ |
| 015 Installer | clean VM / real Mac; signed artifacts | M12 |
| 016–020 Soak/chaos/perf/triage | Section 3–4 | scaffold M1, full M11T |
| 021–024 Lanes/governor/separation/promotion | Section 5 | policy M1, working M11 |
| 025 Scheduling | Section 6 | M11T |
| 026–027 Matrix/stage gates | Section 7 | M11T, M12R |

## 3. Soak profiles (targets, not proof)

| Profile | Target | Mix | Exit criteria (to be fixed *before* the run) |
|---|---|---|---|
| `commit` | 5–20 min | unit + short integration + smoke browser | zero fail; no MISSING |
| `nightly` | ≥8 h | randomized seeded workflows (chat CRUD/search, restarts, project switching, model load/unload) | min operation count per workflow; error ratio ≤ threshold; RAM/VRAM/handle slope within limits |
| `extended` | 24–48 h | nightly mix + fault injection + upgrade/rollback | as above + recovery time bounds |
| `release-soak` | ≥72 h, repeated independent runs | full representative workload | zero release-blockers; leak slopes below threshold; repeated runs agree |

Thresholds come from `commit`/M4 baselines and are written to the profile YAML and hashed before qualifying runs (TB-019). Elapsed time alone never passes a profile: minimum operation counts and workload diversity are mandatory.

## 4. Fault injection catalogue (TB-018)

Kill API/inference mid-stream; kill training mid-checkpoint-write (atomic write + rename + hash verify, restart from last-known-good); corrupt a checkpoint (must be detected, never loaded); simulated CUDA OOM / device unavailable (CPU fallback or clean error); disk-full fixture (small quota volume/VHD); DB lock and failed migration; network drop/latency (via proxy); malformed API responses; inaccessible folder; permission denied; voice device loss. Never touches live profile, real registry keys, or system partitions; no power-pull.

## 5. Training/test lane coordination on a 4 GB GPU

- **Lane A** candidate training; **Lane B** CPU-light tests (UI, storage, mocks); **Lane C** GPU-heavy inference/benchmarks with an exclusive GPU window.
- A supervisor holds a GPU lease (file/OS mutex). Request from Lane C ⇒ signal Lane A to checkpoint (validated), release VRAM, run, then Lane A resumes from that checkpoint. Lane B runs concurrently only if CPU/RAM headroom (measured) allows and results don't depend on GPU timing.
- Serving weights are immutable during tests; candidates live in a separate directory; promotion is a separate, owner-approved, reversible step (TB-024).
- No claim of constant GPU-parallel training on 4 GB. True parallelism only if M3/M4 profiling shows headroom and the owner approves a budget.
- Pause triggers: owner command, game/stream detection, thermal, low disk/RAM.
- Data separation (TB-023): sealed eval fixtures stored with hash manifest, read-only mount for training jobs; training manifests list dataset hashes; failures reviewed → decontaminated → added to a *separate* training set.

## 6. Unattended execution and permissions (TB-025)

Runner is a normal-user process started by an owner-enabled Task Scheduler entry: command allow-list, per-job budgets, heartbeat file, hard timeouts, cleanup, emergency-stop file/command. Never indefinite admin. Claude Code is not the always-on worker; it reads reports in approved sessions and proposes fixes. M0 creates no scheduled task.

## 7. Verification matrix and stage gates

Matrix axes (TB-026): OS/build, CPU/GPU/driver, online/offline, Normal/Developer, clean/upgraded install, load level, training on/paused, permission granted/denied, standard/stress/chaos. Risk-based subset, documented.

Gates: **subsystem** (relevant suites pass, risks documented) → **R2 browser** (functional, security, recovery, performance, endurance on real model/backend; owner approves) → **R4 per-platform** (Windows on Windows, macOS on a real Mac, independently) → **R5 website** (link/hash/signature tests). A skipped critical test blocks "all green".

## 8. Defect handling (TB-020)

Failure ⇒ save seed/env/inputs/logs ⇒ severity label ⇒ local issue ⇒ isolated reproduction. Fixes need targeted + broad regression reruns. Test expectation changes require a written rationale and review.

## 9. Proposed same-tools coding comparison protocol (CODE-020; design, not to be run yet)

1. **Pre-registration** (hashed, committed before any scoring): task families, language set, margins for "comparable", trial counts, seeds, attempt cap, timeout, tool budget, scoring rubric.
2. **Task sources**: (a) newly authored, unseen repo tasks with hidden tests kept outside any training data; (b) owner's blind real problems; (c) public suites (SWE-bench Pro, Terminal-Bench, LiveCodeBench) with versions/licences recorded — contamination caveats stated. SWE-bench Verified only as historical baseline (blueprint §8A.5). These sources' current status must be re-verified at M11P.
3. **Same tools**: identical sandbox image, shell/file/edit/test tools, network policy, wall-clock and attempt budget for Zalius and each reference; reference model/client versions and dates pinned in the report.
4. **Scoring**: pass@1 on hidden tests, regressions, permission violations, time, compute, review load; failures/timeouts stay in the denominator; repeated runs with confidence intervals.
5. **Claim rule**: parity wording only per named task category and reference version when results are within the pre-declared margin with no safety regression. Until then the status is **NOT VERIFIED**.

Open: whether reference-tool terms of service allow benchmarking and automated harness use (D15).
