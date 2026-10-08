# System Overview — Architecture Boundaries (M0 proposal)

Design only. No component exists yet. Decisions marked **[ADR]** must be confirmed by evidence before adoption.

## 1. Subsystems and boundaries

| Subsystem | Language / runtime | Owns | Must NOT |
|---|---|---|---|
| **Core / training** (`model/`) | Python + PyTorch | tokenizer, Transformer, training, checkpoints, eval | reach the network at inference; load third-party LM weights (OWN-001) |
| **Inference service** (`services/api` + core loader) | Python (FastAPI-class) | checkpoint loading, streaming generation, cancellation, token accounting, resource metadata (DEP-005) | host more than one copy of a model (DEP-007); fall back to a remote model (DEP-006) |
| **Chat / memory / projects** (`services/memory`, SQLite) | Python + SQLite/FTS | conversations, projects, memories with scopes, migrations | train weights from stored chats (REPRO-008, §3.2) |
| **Orchestrator** (`services/orchestrator`) | Python | plans, typed tool manifests, permission checks, verification vs external state | execute raw model text; grant itself privileges (§3.2) |
| **Coding agent** (`services/coding-agent`) | Python | repo map, edit engine, build/test loop (CODE-001..020) | claim success from narrative alone (CODE-018) |
| **Windows Bridge** (`windows/bridge`) | C# / .NET, non-elevated | UIA / Win32 / PowerShell adapters behind the platform-neutral contract (XP-002/003) | run elevated |
| **Admin Broker** (`windows/admin-broker`) | C# / .NET, separate elevated process | allow-listed, schema-validated privileged handlers | accept arbitrary shell; persist blanket tokens; bypass UAC (OWN-005, SEC-004) |
| **macOS Bridge** (`macos/bridge`) | Swift (future, M12M) | Accessibility/Apple Events/TCC-scoped actions | reuse Windows code or claim Windows tests prove it (REL-005) |
| **UI** (`ui/`) | TypeScript + React, local browser first | views of real backend state | enable a control with no implemented action (§2 feature rule) |
| **Evolution Engine** (`services/evolution`) | Python | experiment manifests, candidate/champion gates, promotion & rollback | auto-promote; train on sealed eval data (TB-023) |
| **Testbench / Benchmark lab** | Python (+ .NET, Playwright) | see `docs/qa/TESTBENCH_ARCHITECTURE.md` | share mutable state with serving model |
| **Updater / Deployment** | per-platform | signed manifests, staged install, rollback | install unsigned/unknown artifacts (UPD-002) |

## 2. Trust boundaries

1. Browser UI ⇄ local API: loopback-only bind, per-session auth token, strict Origin/CSRF checks (SEC-003).
2. API ⇄ Orchestrator: typed contracts; model output is data until validated.
3. Orchestrator ⇄ Bridge: authenticated local IPC (named pipe with ACL on Windows) carrying a scope-bound authorization id.
4. Bridge ⇄ Admin Broker: separate process boundary; signed/authenticated requests with the operation schema from blueprint §6.4 (`action_id, target, parameters, requested_privilege, authorization_id, expected_effect, recovery_plan`).
5. Untrusted content (web pages, repo files, tool output, pasted text) is tagged data and filtered **at the tool gate**, not only in the prompt (SEC-005).

## 3. Contracts to define first (M1, schema-first)

- Model-serving contract: checkpoint id + hash, tokenizer id, max context, streaming events, cancel, error taxonomy, resource metrics.
- Platform-neutral action contract: capability discovery, normalized errors, permission category, audit record.
- Operation result object (§3.2): requested action, method, scope, status, evidence, duration, reversible actions.
- Job state machine: queued → running → paused/resumed → done/failed/cancelled, idempotency keys.

## 4. Alternative decisions (options and current recommendation; evidence needed before adopting)

| Question | Options | Recommendation now | Evidence needed |
|---|---|---|---|
| Backend framework | FastAPI, Litestar, aiohttp | FastAPI (typed, streaming, mature) | M1 spike: streaming + cancel latency |
| Position encoding | learned vs RoPE | undecided; RoPE likely | M3 small-scale ablation |
| Tokenizer | BPE vs unigram | undecided | M2 fertility/round-trip on real corpus |
| Desktop shell | Electron, Tauri, native WinUI+SwiftUI | **no pick** (XP-006) | prototype: IPC security, a11y, signing, update reliability, footprint |
| IPC to Bridge | named pipes, gRPC over loopback | named pipes (ACL-able) | threat-model review |
| Storage | SQLite + blobs | SQLite (per blueprint) | M1 migration/recovery smoke test |
| Speech | local STT/TTS with permissive licences | undecided | licence + quality + footprint review; must be labelled as non-Core (OWN-001) |
| Python version | 3.12 (blueprint) vs 3.13 | verify PyTorch wheel support on owner's PC first | `audit_windows.ps1` output |

## 5. Security model summary

Least privilege (non-elevated main app), deny-by-default elevated ops, per-scope time-boxed grants, emergency stop that revokes grants and drains queues, audit log the agent cannot erase, secrets only in DPAPI/Credential Manager (Keychain on macOS), local-only default networking. UAC, credential prompts and other products' protections are never bypassed. Full threat model is an M1 artifact; human security review is required for high-risk components (SEC-G1).
