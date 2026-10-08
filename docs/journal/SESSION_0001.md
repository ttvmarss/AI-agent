# SESSION 0001 — M0 Research and Environment Audit (2026-10-08)

Scope: M0 only (per kickoff). No training, no application code, no services, no scheduled tasks, no soak runs.

## Activities
1. Extracted the v1.3 blueprint and kickoff; read the blueprint in full; copied both to `docs/blueprint/`.
2. Audited the **session container** (Linux, 4 vCPU, 15 GiB, no GPU, no PyTorch/.NET). The owner's Windows PC was **not** reachable; wrote read-only `scripts/audit_windows.ps1` (not run).
3. Fetched sources: arXiv 1706.03762, arXiv 2203.02155, GPT-1 PDF (text extracted) verified. openai.com pages returned 403 → secondary confirmation only. PyTorch install page fetched but selector content not extractable.
4. Generated `docs/specs/REQUIREMENTS_MATRIX.md` (256 rows) with `scripts/gen_requirements_matrix.py`.
5. Wrote the architecture, testbench, release/platform, rights, coding-research and decision documents.

## Deliverables (files)
`docs/research/GPT_FOUNDATIONS.md`, `docs/research/CODING_INTELLIGENCE_G0.md`, `docs/architecture/{SYSTEM_OVERVIEW,HARDWARE_PROFILE,DECISION_REGISTER,RELEASE_AND_PLATFORM_PLAN}.md`, `docs/specs/REQUIREMENTS_MATRIX.md`, `docs/qa/TESTBENCH_ARCHITECTURE.md`, `rights/SOURCE_RIGHTS_REGISTER.md`, `scripts/audit_windows.ps1`, `scripts/gen_requirements_matrix.py`, this journal.

## Verified facts vs assumptions
| Verified | Assumed / unverified |
|---|---|
| Container specs; tools present/absent there | Owner PC specs (all) |
| Transformer, GPT-1, InstructGPT bibliographic facts and abstracts | ChatGPT/GPT-2 blog wording (secondary only) |
| Matrix row count (256) reflects IDs found in the blueprint plus expanded ranges | The blueprint's "137 requirements audited" figure — my count differs (256 rows incl. TB-001..027, gates, and range-expanded IDs); definitions of "requirement" differ, so I make no claim either way |
| | VRAM arithmetic, model-size feasibility, any performance number |

## Risks
- Unknown hardware may change E1 sizing, Hyper-V testability, Python/PyTorch version choice.
- No Mac ⇒ the macOS half of the plan cannot be qualified.
- Quality ceiling of a 15–40M model is low; coding parity is a research aspiration only.
- Legal basis for training data is entirely unreviewed.
- Owner-supplied estimates of reference-tool benchmarking permissibility (D15) unresolved.

## Proposed repository layout and journal plan
Layout: blueprint §3.3 unchanged (`model/ services/ windows/ macos/ ui/ tests/ testbench/ benchmarks/ release/ rights/ scripts/ artifacts/`), with `docs/blueprint/` holding the frozen v1.3 inputs. Decision D20: confirm this repo is the monorepo root. Journal plan: one `docs/journal/YYYY-MM-DD.md` per working day plus `NEXT_STEP.md` at end of each session with exact restart commands; ADRs numbered in `docs/architecture/adr/`.

## Proposed M1 plan and acceptance tests (REQUIRES OWNER APPROVAL — not started)
**M1 — Engineering skeleton + testbench baseline.** Deliver: monorepo scaffold; pinned toolchain bootstrap (`scripts/bootstrap.*`) for Windows and Linux CI; typed config; testbench runner skeleton with `commit` profile and JSON/JUnit/HTML reports; requirement-matrix auto-update; ADRs (UI, DB, backend); threat-model v0; rights ledger CSV; CI workflow.
Acceptance tests:
1. **A1** Fresh clone + one bootstrap command yields a working env on the owner's Windows PC and on Linux CI.
2. **A2** `testbench/run commit` completes in ≤20 min, emits JSON+JUnit+HTML; deliberately failing test appears as FAIL; a deleted test appears as MISSING, not green.
3. **A3** Matrix regeneration: marking a row `implemented` with no test makes the check fail.
4. **A4** Resume/cancel/timeout of a runner job demonstrated with seeded tests.
5. **A5** SQLite migration + crash-recovery smoke test.
6. **A6** Secrets scan and dependency audit run and report.
7. **A7** Hardware audit output from the owner's PC recorded in HARDWARE_PROFILE.

**Needs from owner before M1:** run the audit script and share output; answer D2, D11, D20; confirm whether this repo is the project root; approve or amend the matrix milestone mapping.

## Status
M0 deliverables written; **STOPPED awaiting approval for M1.**
