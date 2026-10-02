# STARK-LEVEL INTELLIGENCE ARCHITECTURE — REVISION ZERO

**Codename: PRAXIS** · Status: Phase 0 (research + architecture, no production code) · Date: 2026-10-02

> Reality tags used throughout: **[NOW]** available now · **[CUSTOM]** feasible, significant engineering · **[EXP]** experimental, reliability uncertain · **[RESEARCH]** original research required · **[IMPRACTICAL]** technology insufficient today.
> Confidence tags: **KNOWN / LIKELY / UNCERTAIN / SPECULATIVE**.

---

## 0. How to read this document

This is the answer to: *"These are components. Show me what comes after them."*

The components exist: frontier LLMs, tool-use protocols, vector stores, browser automation, local models, simulators. What does not exist is the thing that **binds them into a system with a goal, a memory, a model of its environment, a verification habit, and a recovery plan**. A chatbot is a function `prompt → text`. PRAXIS is a **closed-loop controller whose actuators happen to be language models and tools**.

That reframing is the whole design, and it is borrowed from control theory, not from software convention:

```
          ┌──────────── reference (goal + success criteria) ────────────┐
          ▼                                                             │
   [ Planner ] → [ Actuators: models, tools, computer control ] → [ World ]
          ▲                                                             │
          └────── [ Sensors + Verifiers: observe, measure, compare ] ◄──┘
```

Every subsystem below exists to make one arm of this loop stronger, faster, or safer. If a feature does not strengthen the loop, it fails the Stark Test (§36) and is cut.

**Starting state of the repository (measured, not assumed):** one commit, a 37-byte README, no code. Sandbox: 4 CPU cores, 15 GB RAM, no GPU, Python 3.11, Node 22. So Phase 1 must run on a laptop-class machine with cloud model APIs; local-GPU features are designed-in but not assumed. (KNOWN — measured this session.)

### 0.1 Clean-room rule and dependency policy

**Clean-room:** PRAXIS reuses **no** existing project, assistant, agent framework, or code from the owner's machines. Everything that defines the system's behavior is written new in this repository.

**Custom (written from scratch — this is the invention):** event-sourced kernel and log, Executive, contracts, Capability Guard and permission engine, Router and capability registry, memory layer, World Model, Project World, verification framework, recovery manager, tool runtime and manifests, specialist runtime, eval harness, UI.

**Commodity (consumed, behind adapters, replaceable):** foundation-model APIs and local model runtimes (components, per the directive), the language runtime and standard library, SQLite, cryptographic and OS primitives, physics/CAD/simulation engines in the lab phases.

**Not used:** off-the-shelf agent/orchestration frameworks (LangChain-style), prior personal projects, inherited prompts or configs. The test for any dependency: *if it vanished tomorrow, would we lose a capability or only a convenience?* Capabilities are built here; conveniences may be borrowed.

---

## 1. Ten original AI names

| # | Name | Rationale |
|---|------|-----------|
| 1 | **PRAXIS** | Greek: knowledge turned into action. The system's whole point. |
| 2 | **LODESTAR** | Fixed reference that everything steers against — the goal model. |
| 3 | **TESSERA** | One tile in a mosaic — many models, one picture. |
| 4 | **HALYARD** | The line that raises and holds a sail — orchestration. |
| 5 | **ORRERY** | A working model of a system in motion — the world model. |
| 6 | **KESTREL** | Hovers, observes, strikes with precision — observe/act/verify. |
| 7 | **FOUNDRY** | Where raw components are cast into something new. |
| 8 | **MERIDIAN** | Reference line used to fix position — grounding in real state. |
| 9 | **SEXTANT** | Navigation by measurement, not faith — evidence-first. |
| 10 | **CORVID** | Tool-using, memory-rich, problem-solving intelligence. |

## 2. Chosen codename

**PRAXIS.** Runner-up: LODESTAR (reserved as the name of the Goal Model subsystem). Subsystem names below are internal engineering names, not marketing: they exist so that logs and design docs have unambiguous nouns.

## 3. Mission statement

> **PRAXIS turns a stated outcome into a verified result.** It maintains persistent understanding of the user's projects, machines, and history; chooses the right models and tools for each step; acts through software and (eventually) hardware; checks its own work against evidence; and recovers from its own mistakes — while keeping a human in control of anything consequential.

**Measurable form of the mission** (these become the benchmark suite in §33):

- Given an outcome-level request ("cut startup time 30% without changing behavior"), PRAXIS delivers a change set **with evidence** (profiles, tests, benchmark delta) and a rollback point, with ≤ 1 clarifying question in ≥ 80% of tasks in the evaluation suite. *(target, UNCERTAIN until measured)*
- **Zero** unverified "done" claims: every completion report links to at least one verifier result.
- **Zero** Class-4/5 actions without a recorded human authorization.

---

## 4. Design philosophy

### 4.1 The Invention Engine applied to PRAXIS itself

**DEFINE.** *Objective:* a system that completes multi-step real-world work reliably. *Success criteria:* verified-task success rate, intervention rate, cost/task, recovery success rate. *Hard constraints:* human authority over irreversible actions; no unverifiable claims; models are replaceable. *Soft:* latency, cost, elegance. *Unknowns:* real-world reliability of long-horizon autonomy; which tasks benefit from multi-model debate vs. a single strong model.

**DECOMPOSE.** Dependency graph (arrow = "needs"):

```
Verification ← Tools ← Permissions ← Executive ← Goal Model
Router ← Capability Registry ← Benchmarks
Memory ← Event Log (everything depends on the log)
World Model ← Sensors (OS probes, file watchers, tool state)
Computer Control ← World Model + Verification + Recovery
Multi-agent ← Executive + Memory + Router
Self-improvement ← Benchmarks + Observability + Governance
```

The **event log is the root node**: memory, observability, recovery, self-improvement, and "why did you do that?" are all views over it. So it gets built first.

### 4.2 Law / convention / legacy / arbitrary — the assumption audit

| Assumption in typical "AI assistant" design | Category | Verdict |
|---|---|---|
| Interaction is request→response | Convention | **Attack.** Intent persists; turns are just input events to a long-lived process. |
| One model does everything | Arbitrary | **Remove.** Route per step. |
| Context = chat history | Legacy limitation | **Remove.** Context is *reconstructed* per step from memory + world state. |
| LLM output can be trusted if it sounds right | Arbitrary | **Remove.** Outputs are *proposals* until verified. |
| Agents should be free-form and autonomous | Convention | **Attack.** Bounded autonomy via typed plans + permission classes. |
| LLM context windows are the memory | Technical limit (current) | **Route around.** External structured memory; context is a cache. |
| Tool calls are just function calls | Convention | **Upgrade.** Each tool declares preconditions, postconditions, reversibility, permission class. |
| LLMs are non-deterministic so testing is impossible | Technical, partly | **Partially false.** Test the *harness* deterministically (record/replay); test models statistically. |
| Needing a bespoke UI per feature | Arbitrary | **Remove.** UI is a projection of system state. |
| Token limits | Technical (current) | Treat as engineering constraint with a budget manager. |
| Hallucination | Technical (current model limitation) | **Cannot be eliminated; can be contained** via verification + provenance. This is a Category C problem, not a Category A. |
| Causality / physics (build time, GPU memory, network latency) | **Law of nature** | Respect. Budget for it. |

### 4.3 Five architectures, attacked

**A — Safest: "Supervised Toolbelt."** Single strong model, fixed tool set, human approves every action.
*Attack:* safe but it *is* a chatbot with buttons. Human becomes the bottleneck; no persistent understanding. Fails Stark Test 3 (reduces user effort).

**B — Most powerful: "Autonomous Swarm."** Many free-running agents with shared scratchpad, broad system access.
*Attack:* shared mutable state with no authority → agents disagree and thrash; cost explodes; one prompt-injected agent compromises all; impossible to explain "why did you do that?" Fails reliability, security, observability.

**C — Unconventional: "Event-Sourced Cognitive Kernel."** No chat loop at all. A durable, append-only event log is the single source of truth; "agents" are pure-ish reducers/handlers over the log, scheduled by a kernel that enforces capabilities (OS-style). Memory, world state, and UI are materialized views.
*Attack:* unfamiliar, more upfront design; log growth; replay must be deterministic around non-deterministic model calls (solve by *recording* model outputs as events). Survives all stress tests in §29 better than any other candidate — time-travel debugging, rollback, audit, and self-improvement come nearly free.

**D — Scalable: "Distributed Service Mesh."** Every subsystem a networked microservice with queues.
*Attack:* massive operational burden for a single-user system; adds latency and failure modes where none are needed. Right *eventually* for multi-machine (§24), wrong as the starting point. Law-vs-convention: microservices are a **convention** here.

**E — Minimal prototype: "Executive Loop + Router + Log."** One process: executive loop, two providers, SQLite event log, 3 tools, 1 verifier type.
*Attack:* too small to prove the interesting claims — **unless** it is built *as the kernel of C*, not as a throwaway.

### 4.4 Synthesis → **PRAXIS Architecture: "Event-Sourced Executive Kernel" (C kernel, E scope, D-ready seams, A-grade permissions)**

- **C's** event-sourced kernel as the spine.
- **E's** scope discipline: first build is single-process, local-first.
- **A's** permission model as a hard layer: autonomy scales *within* capability grants.
- **B's** parallelism, but only through the kernel, with typed contracts and a single arbiter (the Executive).
- **D's** scalability preserved by making every subsystem talk through a message/event interface from day one — so the process boundary can be moved later without redesign.

Rejected: B as primary (see failure log F-001), D as starting point (F-002), A as endpoint (F-003).

### 4.5 Design laws (enforced in code review)

1. **Claims require evidence.** A result without a verifier record is a draft.
2. **Models propose; the kernel disposes.** No model output directly mutates the world — it passes through typed action schemas, permission checks, and verification.
3. **The log is truth.** Nothing important lives only in a prompt or in process memory.
4. **Every action declares its inverse** (or declares itself irreversible, which raises its permission class).
5. **Models are replaceable processors.** No subsystem imports a vendor SDK except the provider adapter.
6. **Observe before act; verify after act.**
7. **Governance is not self-editable.** Self-improvement can touch prompts, routing, and workflows — not permissions, not the verifier of last resort.
8. **Suppress noise.** Messages to the human carry information, not narration.

---

## 5. Capability map

| Capability | What it means concretely | Primary subsystem | Reality |
|---|---|---|---|
| Intent understanding & goal tracking | Persistent goal tree with success criteria | Executive / LODESTAR | [NOW] |
| Context reconstruction | Pull only relevant memory/world state per step | Memory + Context Builder | [NOW]/[CUSTOM] |
| Multi-model routing | Pick provider per step by measured capability, cost, privacy | Router | [NOW] |
| Multi-specialist reasoning | Architect/critic/implementer/tester, synthesized | Specialist Runtime | [CUSTOM] |
| Persistent project understanding | Component graph, decisions, failures, benchmarks | Project World | [CUSTOM] |
| Environment awareness | Machines, processes, devices, permissions, resources | World Model (ORRERY) | [CUSTOM] |
| Safe tool use | Typed tools with pre/postconditions | Tool Runtime | [NOW] |
| Computer control | Observe→plan→act→verify→recover on GUI/CLI | KESTREL | [EXP] |
| Verification | Tests, benchmarks, state diffs, source checks | SEXTANT | [NOW]/[CUSTOM] |
| Recovery | Checkpoints, rollback, emergency stop | Recovery Manager | [NOW] |
| Research with provenance | Primary-source evidence, conflict tracking | Research Engine | [CUSTOM] |
| Software engineering | Impact analysis, isolated edits, test gates | Coding Lab | [CUSTOM] |
| Engineering lab (CAD/sim/firmware) | Requirement→concept→model→simulate→revise | FOUNDRY | [EXP] (CAD/FEA integration), [RESEARCH] (closed-loop design) |
| Voice | Streaming, interruptible, reference-aware | Voice | [NOW] components, [CUSTOM] reference resolution |
| Vision | Screen/world understanding | Vision | [NOW]/[EXP] |
| Proactive initiative | Opportunity detection under budget | Proactive Engine | [EXP] |
| Self-improvement | Benchmarked workflow/prompt/routing changes | Improvement Loop | [EXP] |
| Self-measurement | Continuous success/hallucination/cost metrics | Telemetry + Eval Harness | [CUSTOM] |
| Fully autonomous multi-day engineering of novel hardware | — | — | [IMPRACTICAL] today. Stated plainly. |

---

## 6. Central intelligence architecture (the Executive)

### Process model

PRAXIS is a **long-lived kernel process**, not a request handler. Conversation, voice, CLI, and UI are *adapters* that emit `UserEvent`s into the kernel.

```
 Adapters (chat / voice / CLI / UI / file-watch / schedule)
          │ events
          ▼
 ┌────────────────────────── KERNEL ──────────────────────────┐
 │  Event Log (append-only, SQLite→Postgres) ◄── everything   │
 │                                                            │
 │  EXECUTIVE LOOP                                            │
 │   1 Intent Parser      → Intent{outcome, constraints}      │
 │   2 Goal Model         → GoalTree + success criteria       │
 │   3 Context Builder    → memory + world + project slice    │
 │   4 Strategist         → Plan (typed DAG of Steps)         │
 │   5 Dispatcher         → Router/Specialists/Tools          │
 │   6 Monitor            → watches Steps, budgets, deadlines │
 │   7 Verifier gate      → no Step "done" w/o evidence       │
 │   8 Arbiter            → resolves specialist disagreement  │
 │   9 Integrator         → writes learnings to memory        │
 │                                                            │
 │  Capability Guard (permissions) wraps every Step           │
 └────────────────────────────────────────────────────────────┘
```

### Core data types (the contract everything else obeys)

- **Intent**: `{outcome, constraints[], priority, source_event, ambiguity_score}`
- **Goal**: `{id, parent, statement, success_criteria[Verifier], status, budget}`
- **Plan**: DAG of **Step**s. **Step**: `{id, kind, inputs, tool|model_role, preconditions[], postconditions[], inverse|IRREVERSIBLE, permission_class, verifier, timeout, budget}`
- **Evidence**: `{claim, verifier_id, result, artifacts[], timestamp, confidence}`
- **Decision**: `{question, options[], chosen, rationale, evidence_ids[], reversible}`

### Subsystem spec — Executive

- **PURPOSE:** Convert intent into verified outcomes; own priorities, delegation, arbitration, and the decision of when to ask the human.
- **INPUTS:** UserEvents, schedule/trigger events, tool/verifier results, budget & world-state signals.
- **OUTPUTS:** Plans, dispatches, human-facing messages (only when information-bearing), memory writes, escalation requests.
- **DEPENDENCIES:** Event log, Router, Memory, World Model, Capability Guard, Verifier.
- **FAILURE MODES:** Planning loops; goal drift; over-asking or under-asking; stale context; runaway cost; deadlock between specialists.
- **RECOVERY:** Per-goal budget (steps, tokens, wall-clock, dollars) with hard stop → emergency protocol (§21); re-plan from the last verified step; cycle detector on plan history; Arbiter tie-break by evidence, then by human.
- **SECURITY:** Executive never executes tools directly; all Steps pass the Capability Guard. Untrusted content (web, files, emails) is tagged `UNTRUSTED` and may *inform* but never *instruct* the Executive (prompt-injection containment).
- **TESTING:** Deterministic replay of recorded sessions against new Executive code; scripted-model harness with fault injection (model returns wrong/empty/malformed output); property tests: "no Step runs without a passing guard decision."
- **FUTURE EXPANSION:** Hierarchical executives per project; multi-user; delegation to remote kernels.

**When the Executive asks the human** (decision table, from the directive): conflicting requirements · human taste · money · security · privacy · irreversible action · multiple equally valid objectives. **Otherwise it decides and records a Decision.**

---

## 7. Model orchestration (the Router)

### Capability Registry

Each model/provider is a row of **measured** (not marketing) scores, refreshed by the benchmark harness:

```yaml
model: <provider/id>
modalities: [text, image, audio]
scores:            # 0–1, from PRAXIS's own eval suite, with n and date
  reasoning: {v: 0.91, n: 120, date: 2026-10-01}
  coding: ...  vision: ...  tool_use: ...  long_context: ...
speed:   {ttft_ms: ..., tok_per_s: ...}
cost:    {in_per_mtok: ..., out_per_mtok: ...}
context: 1000000
privacy: {tier: cloud|local|enclave, retention: ..., allowed_data_classes: [public, project]}
reliability: {error_rate: ..., schema_adherence: ...}
```

### Routing policy

`route(step) = argmax_m utility(m | step)` subject to **hard filters first** (privacy class, modality, context size, tool support), then utility = `w_q·quality(step.kind) − w_c·cost − w_l·latency`, with weights from the goal's budget and urgency. Includes:

- **Escalation ladder:** cheap/fast model first for low-stakes steps; escalate on verifier failure or low self-consistency.
- **Fallback chain:** provider outage/rate-limit → next candidate, logged.
- **Shadow routing:** a % of steps are silently also run on a candidate model to build the registry's evidence (never for side-effecting steps).
- **Data-class gating:** data labeled `private` can only go to `local` or contractually-approved providers.

### Subsystem spec — Router

- **PURPOSE:** Select and call the best available resource per step; keep PRAXIS vendor-independent.
- **INPUTS:** Step requirements, goal budget, data classification, registry, provider health.
- **OUTPUTS:** Model response + metadata (model, tokens, cost, latency) as events.
- **DEPENDENCIES:** Provider adapters, registry, benchmark harness, event log.
- **FAILURE MODES:** Bad registry data → systematic mis-routing; provider API change; silent model-version change altering behavior; cost spikes; schema-violating output.
- **RECOVERY:** Pin model versions where the provider allows; canary benchmark on a schedule detects silent drift; automatic fallback; structured-output validation + bounded retries with error feedback.
- **SECURITY:** Per-provider credential vault, data-class gating, request/response redaction for logs, no raw secrets ever enter prompts.
- **TESTING:** Contract tests against a fake provider; golden-set regression per model; chaos tests (timeouts, 429s, truncated streams).
- **FUTURE EXPANSION:** Learned router (bandit) after enough data; speculative parallel decoding across providers; on-device distillation of frequent step types.

**Model evolution protocol (new model arrives):** `BENCHMARK → COMPARE → SANDBOX → VERIFY → REGISTER → ROUTE`. No code changes outside a registry entry and (if new API shape) one adapter. **[NOW]**

---

## 8. Multi-agent architecture

### Principle: specialists are *roles*, not entities with authority

A **Specialist** = `{role prompt, tool allowlist, memory scope, output schema, budget}`. Instantiated on demand, share project memory read/write through the kernel (not directly with each other), and are destroyed on completion; their findings are integrated as events.

### Reasoning topologies (chosen per task by the Strategist)

| Topology | When | Structure |
|---|---|---|
| **Single** | Easy / low stakes | One model, verifier only |
| **Propose–Critique** | Most engineering decisions | Architect → Critic → Architect revise |
| **Fan-out research** | Independent sub-questions | N researchers → synthesizer |
| **Debate-with-evidence** | High stakes, disputed facts | Two advocates + evidence-weighted judge |
| **Pipeline** | Code change | Architect → Implementer → Tester → Reviewer |
| **Ensemble vote** | Classification/extraction with checkable output | k models, agreement threshold |

**Rule:** parallelize only independent steps (no data dependency in the plan DAG). The Strategist derives this from the DAG, not from vibes.

### Arbitration

Disagreement resolution order: (1) **run a discriminating test** if one exists; (2) weigh evidence quality and recency; (3) prefer reversible option; (4) escalate to a stronger model as *judge only*; (5) escalate to human with the two positions stated in ≤ 5 lines each.

### Subsystem spec — Specialist Runtime

- **PURPOSE:** Safe, budgeted, parallel specialist execution with coherent integration.
- **INPUTS:** Step assignments, scoped context, tool allowlist.
- **OUTPUTS:** Structured findings, artifacts, confidence, dissent notes.
- **DEPENDENCIES:** Router, Memory, Tool Runtime, Executive Arbiter.
- **FAILURE MODES:** Correlated errors (same base model agrees with itself); sycophantic critic; context contamination; cost multiplication; deadlock; lost work on specialist crash.
- **RECOVERY:** Heterogeneous models for critic vs. author; critic must emit *falsifiable* objections (a test or a source); per-specialist checkpoints in the log; wall-clock + token budgets; supervisor restarts.
- **SECURITY:** Least-privilege tool allowlists; specialists cannot grant permissions or message the user directly; untrusted-content isolation per specialist.
- **TESTING:** Seeded-bug benchmarks (does the critic find the planted defect?); ablation: single vs. multi-model on the eval suite — **multi-agent is only kept for task types where it measurably wins** (KNOWN good practice; UNCERTAIN which types win).
- **FUTURE EXPANSION:** Persistent specialist "personalities" learned from performance; cross-project specialists; remote specialist hosts.

---

## 9. Memory architecture

**Governing idea:** the event log is the ground truth; memories are **derived, indexed, and revisable views** with provenance. Context windows are caches, not storage.

| Memory | Content | Store | Retrieval | Write policy |
|---|---|---|---|---|
| **Working** | Current plan, active hypotheses, scratch | In-process + checkpointed to log | Direct | Auto |
| **Episodic** | What happened (task, actions, outcome) | Event log + summaries | Time/goal/entity + semantic | Auto, compacted |
| **Project** | Architecture, decisions, milestones, files | Project World DB (§11) | Structured query + graph | Auto, via Integrator |
| **Semantic** | Facts, reusable knowledge with source & confidence | Triple/doc store + vectors | Hybrid (BM25 + embedding + graph) | Requires provenance |
| **Engineering** | Patterns, calculations, solved designs | Doc store + vectors | Hybrid | Verified entries only |
| **Failure** | What failed, why, what changed | Structured table + vectors | "Have we seen this?" lookup *before* planning | Mandatory on failure |
| **User preference** | Stable, useful preferences | Small KV with evidence & decay | Always-on small slice | User-visible, editable, deletable |
| **Procedural** | Replayable workflows that worked | Parameterized plan templates | Match against Intent | Promote after N verified successes |

**Retrieval pipeline (relevance-based, budgeted):** `query formulation → multi-index candidates → rerank (cross-encoder or small LLM) → recency/confidence weighting → token-budget packing → provenance attached`. Everything retrieved carries `(source_event, confidence, age)`; stale items are flagged to the model rather than silently trusted.

**Failure Memory record** (also used by this document, see §29):

```
WHAT FAILED · WHY IT FAILED · WHAT WE LEARNED · WHAT CHANGES NEXT · evidence_ids · applicability_tags
```

### Subsystem spec — Memory

- **PURPOSE:** Give PRAXIS durable, relevant, trustworthy recall without context bloat.
- **INPUTS:** Event stream, Integrator writes, verified evidence, explicit user edits.
- **OUTPUTS:** Ranked, budgeted, provenance-tagged context slices; "have we seen this" answers.
- **DEPENDENCIES:** Event log, embedding model (local-capable), storage engine, Integrator.
- **FAILURE MODES:** Memory poisoning (false or injected "facts"); retrieval misses; stale facts; unbounded growth; preference over-fitting; privacy leakage across projects.
- **RECOVERY:** Memories are *derived* → rebuild from the log; per-item provenance enables targeted purge; confidence decay + re-verification of high-impact facts; compaction jobs with reversible summaries (raw retained in cold storage).
- **SECURITY:** Per-project memory namespaces; untrusted-origin facts quarantined until verified; encryption at rest; user can inspect/delete any memory; no memory write from untrusted content without a verifier.
- **TESTING:** Retrieval benchmark (recall@k/precision on labeled queries from real sessions); poisoning red-team tests; rebuild-from-log equivalence test.
- **FUTURE EXPANSION:** Learned retrieval; knowledge-graph reasoning; cross-device sync with conflict resolution.

---

## 10. World model (ORRERY)

**Purpose of reasoning from state, not assumption:** the system must never plan to use an app, GPU, file, or permission it hasn't confirmed.

**State schema (entities with `last_verified` timestamps and `freshness_ttl`):**

```
Machine{os, cpu, gpu, vram, ram, disk, power, temp, net}
Process{pid, app, cwd, resource use}   Application{name, version, automatable?}
Device{usb/serial/printers/cameras/microcontrollers}
Workspace{repos, branches, dirty?, active files}
Service{name, endpoint, health, auth state}
Permission{grants, scopes, expiry}      Network{reachability, policy}
```

**Mechanism:** probes (OS APIs, `psutil`, `git`, file watchers, accessibility trees, device enumeration) emit `Observation` events → reducer updates the state graph. **Staleness is explicit**: the Context Builder says "disk free: 41 GB (verified 3 s ago)" vs. "(verified 2 days ago — re-probe before relying)."

### Subsystem spec — World Model

- **PURPOSE:** Truthful, queryable representation of the operating environment.
- **INPUTS:** Probe observations, tool results, user statements (lower trust).
- **OUTPUTS:** State queries, change events, capability answers ("can I run a 70B model here?"), resource forecasts.
- **DEPENDENCIES:** Probes/sensors, event log, OS permissions.
- **FAILURE MODES:** Stale or wrong state; probe failures; expensive polling; state/reality divergence after an external change.
- **RECOVERY:** TTLs trigger re-probe; divergence detected when a postcondition check fails → mark entity `SUSPECT`, re-observe, replan.
- **SECURITY:** Probes are Class-0 (read-only); sensitive entities (credentials, personal files) are *existence-only* in the model; no secrets stored.
- **TESTING:** Simulated environments (containerized fixtures) with scripted drift; "predicted vs. observed" divergence metric.
- **FUTURE EXPANSION:** Multi-machine fleet; physical-lab entities (printers, CNC, benches); predictive resource models.

---

## 11. Project intelligence system (Project World)

Every project is a **persistent environment** with a typed graph, not a folder.

```
Project
 ├─ Mission, CurrentObjective, Milestones
 ├─ Architecture ── ComponentGraph (nodes: modules/services/parts; edges: depends-on, calls, owns)
 ├─ Artifacts: Files@Versions, Dependencies (pinned), Backups
 ├─ Knowledge: Decisions(ADR-style), Experiments, Benchmarks, FailedApproaches, OpenQuestions, Risks
 ├─ Work: Issues, Branches/Experiments, FutureIdeas
 └─ Links: every node ↔ events that created/changed it (provenance)
```

**Software projects** are *derived* from the code where possible: static analysis builds the dependency/call graph (`tree-sitter`, language servers) so the graph isn't hand-maintained and can't rot. **[NOW]/[CUSTOM]**

**Impact analysis:** given a proposed change, traverse the graph → affected components → affected tests → affected benchmarks → blast radius estimate → required verifiers. This is what replaces "random edits across a project."

### Subsystem spec — Project World

- **PURPOSE:** Persistent understanding of what exists, why, and what depends on what.
- **INPUTS:** Repo state, static analysis, decisions/experiments/benchmarks logged by Executive, user input.
- **OUTPUTS:** Component graph, impact analyses, project context slices, milestone status, risk register.
- **DEPENDENCIES:** VCS, analyzers, Memory, event log.
- **FAILURE MODES:** Graph stale vs. code; analyzer blind spots (dynamic dispatch, reflection, config-driven wiring); decision records lacking rationale.
- **RECOVERY:** Re-derive on every checkpoint; mark low-confidence edges; tests as ground truth over graph.
- **SECURITY:** Project-scoped permissions; secrets excluded from the graph; backups encrypted.
- **TESTING:** Graph-accuracy checks against known repos; impact-analysis recall (did the predicted-affected set include the actually-broken tests?).
- **FUTURE EXPANSION:** Hardware BOM/part graphs; cross-project reuse detection; automated architecture-drift alerts.

---

## 12. Computer-control architecture (KESTREL)

**Reality:** **[EXP]**. GUI automation by models is improving but is the least reliable subsystem here. Therefore: **prefer APIs and CLIs over GUIs; prefer accessibility trees over pixels; prefer pixels only as the last resort.** (Hierarchy of control surfaces, most to least reliable.)

```
1 Native API / SDK      4 Accessibility tree (UIA / AX / AT-SPI)
2 CLI + structured out  5 Browser DOM (Playwright)
3 File/DB state edit    6 Pixel vision + synthetic input   ← last resort
```

### The OBSERVE → UNDERSTAND → PLAN → ACT → VERIFY → RECOVER cycle

Every action is an **ActionContract**:

```
intended_state     what the world should look like after
current_state      observed immediately before (not assumed)
operation          the concrete tool call
expected_result    machine-checkable postcondition
verifier           how we'll check (DOM assertion, file hash, process state, screenshot diff)
recovery           inverse op, or restore-from-checkpoint, or "irreversible → Class 5 gate"
permission_class   0–5
```

After ACT: `diff(expected_result, observed)`. Mismatch → **stop, don't chain.** Classify (timing? wrong target? app changed? model misperception?) → retry once with fresh observation → else recover → else escalate. Multi-step operations are **transactional**: checkpoint before, commit only if all postconditions hold, else roll back.

**Safety interlocks:** global kill-switch hotkey (hardware-level, not model-controlled); action rate limits; allowlist of target apps/domains per goal; "dry-run" mode that renders the planned actions without executing; user-activity detection pauses automation to avoid fighting the human.

### Subsystem spec — Computer Control

- **PURPOSE:** Reliable, verifiable, reversible operation of software on the user's machine(s).
- **INPUTS:** ActionContracts from Executive; world-state observations; screenshots/accessibility trees.
- **OUTPUTS:** Action results with observed postconditions; recovery events; screen-state summaries.
- **DEPENDENCIES:** World Model, Vision, Capability Guard, Recovery Manager, OS automation APIs.
- **FAILURE MODES:** Misidentified UI element; stale screenshot; popup/dialog interrupts; app crash mid-op; focus stolen; prompt injection from on-screen text; non-idempotent retry doubling an effect.
- **RECOVERY:** Fresh-observation-before-act; idempotency keys/semantic checks before retry; transactional checkpoints; app-state snapshot (e.g., document autosave/VCS) prior to risky ops; kill-switch; sandboxed VM/container as default execution target for untrusted workflows.
- **SECURITY:** On-screen text is `UNTRUSTED` data; credential entry is never model-visible (vault injection only); per-goal app/domain allowlists; Class 3+ actions need grants; full action recording (screen+action log).
- **TESTING:** Deterministic synthetic apps and recorded web fixtures; a **GUI task benchmark** with success rate, steps-to-success, and recovery-success metrics; fault injection (random popups, latency, element renames).
- **FUTURE EXPANSION:** Multi-machine control; robotics/embodied actuators sharing the same ActionContract interface; learned UI "affordance memory" per application.

---

## 13. Engineering laboratory (FOUNDRY)

**Goal:** given "design a robotic hand," produce a **traceable engineering package**, not an essay.

### The design pipeline (each stage emits artifacts + verifiers)

```
REQUIREMENTS → CONCEPTS (≥3, scored) → KINEMATIC MODEL → ACTUATOR TRADE STUDY
 → MATERIAL TRADE STUDY → CAD GEOMETRY → ELECTRONICS → FIRMWARE → CONTROL SW
 → BOM (priced, sourced) → SIMULATION (kinematic/dynamic/FEA) → TEST PROCEDURE
 → FAILURE MODES (FMEA) → REVISION  ──loop until requirements satisfied or constraint found
```

### Tool ecosystem and feasibility

| Domain | Tooling | Reality |
|---|---|---|
| Parametric CAD | CadQuery / build123d / OpenSCAD (code-first), FreeCAD API | **[NOW]** — code-CAD is ideal for LLMs |
| Commercial CAD | Fusion/SolidWorks APIs | **[CUSTOM]** |
| Kinematics/dynamics | PyBullet, MuJoCo, Drake, Pinocchio | **[NOW]** |
| FEA | CalculiX, FEniCS, Elmer | **[CUSTOM]** (meshing robustness is the hard part) |
| Electronics | KiCad (scripting), SPICE (ngspice) | **[CUSTOM]**; autoroute quality limited |
| Embedded | PlatformIO, Arduino, ESP-IDF, Zephyr; HIL via serial | **[NOW]** |
| Fabrication | Slicers (Prusa/Cura CLI), G-code, CAM (FreeCAD CAM) | **[CUSTOM]**; sending to hardware is Class 4 gated |
| Vision | OpenCV + models | **[NOW]** |
| Closed-loop design optimization (CAD ↔ sim ↔ revise, autonomously) | | **[RESEARCH]** |
| Autonomous novel hardware from one sentence | | **[IMPRACTICAL]** today |

**Simulation-first rule:** nothing is fabricated until it has passed the cheapest sufficient simulation. **Sim-to-real correspondence:** every physical measurement is logged against the simulation's prediction; persistent error → update model parameters (system identification) and record a *model-validity* note, so the lab learns *where its simulations can't be trusted.*

### Subsystem spec — Engineering Lab

- **PURPOSE:** Coordinate design tools through requirements → verified design → fabrication-ready outputs.
- **INPUTS:** Requirements, constraints (cost, mass, power, tolerances), measurement data.
- **OUTPUTS:** CAD files, BOM, schematics, firmware, simulation reports, test plans, FMEA, revision history.
- **DEPENDENCIES:** Tool adapters, Simulation system, Project World, Verification, Permissions (hardware actions).
- **FAILURE MODES:** Geometrically valid but physically nonsensical CAD; mesh failure; unit errors (the classic); simulation that disagrees with reality; BOM parts unavailable; firmware that bricks hardware.
- **RECOVERY:** Unit-typed quantities everywhere (`pint`); sanity-check library (mass, center of gravity, interference, wall thickness); parametric models so revision is regeneration; hardware-in-loop only with current/voltage limits and a hardware e-stop; versioned designs.
- **SECURITY:** Fabrication/actuation = Class 4 (physical-world safety); firmware flashing requires explicit grant; supplier purchases never autonomous.
- **TESTING:** Golden designs with known answers (cantilever deflection vs. analytic); unit-error injection; sim-vs-measurement regression on a reference rig.
- **FUTURE EXPANSION:** Digital twin of the user's workshop; automated test-rig control; design-space optimization with surrogate models.

---

## 14. Research system (SEXTANT-R)

**Pipeline:** `question → decomposition → source plan (primary first) → gather → extract claims with quotes → cross-compare → date/quality assessment → uncertainty map → synthesis → citation retention`.

- **Source tiers:** T1 primary (papers, specs, source code, official data) · T2 authoritative secondary · T3 informed commentary · T4 unvetted. Claims inherit the *lowest* tier among their sole supports.
- **Claim ledger:** `{claim, supports[], contradicts[], dates, tier, status: KNOWN|LIKELY|UNCERTAIN|SPECULATIVE}`. Output is generated *from the ledger*, so contradictions can't be silently dropped.
- **Freshness:** time-sensitive claims are re-verified; anything older than its TTL is flagged.
- **Confidence** = f(source tier, independent agreement, direct measurement, recency, replication) — computed, then shown as a label, never as false-precision numbers.

### Subsystem spec — Research Engine

- **PURPOSE:** Produce evidence-backed conclusions with explicit uncertainty.
- **INPUTS:** Questions, web/API/document sources, local corpora.
- **OUTPUTS:** Claim ledger, synthesis with citations, open questions, confidence labels.
- **DEPENDENCIES:** Web/fetch tools, Router (researcher + critic models), Memory (semantic), Verification.
- **FAILURE MODES:** SEO-spam sources; model-fabricated citations; circular sourcing (many sites citing one); stale data; prompt injection from fetched pages.
- **RECOVERY:** Citation verification step (the quote must appear in the fetched source); independence check (shared upstream); explicit "insufficient evidence" outcome allowed and rewarded.
- **SECURITY:** Fetched content `UNTRUSTED`; sandboxed fetch; no credentials in research context; domain allow/deny lists.
- **TESTING:** Citation-accuracy audit (random claims → verify quote exists); questions with known answers and known traps (outdated stats, popular myths); calibration curve (stated confidence vs. correctness).
- **FUTURE EXPANSION:** Automated experiment design for empirical questions; literature monitoring; replication checks.

---

## 15. Simulation system

**Purpose:** make bad ideas die cheaply. A unified **SimulationJob** interface: `{model, parameters, scenario, fidelity, budget} → {metrics, artifacts, validity_envelope}`.

- **Fidelity ladder:** analytic estimate → reduced-order model → rigid-body sim → FEA/CFD → physical test. Run lowest fidelity that can reject a candidate.
- **Validity envelope:** each simulator declares (and the lab learns) the parameter ranges where it matched reality.
- **Software "simulation":** the same idea applies to code — containerized replicas, record/replay of production traffic, property-based tests, chaos injection.

### Subsystem spec — Simulation

- **PURPOSE:** Cheap, trusted prediction before irreversible commitment.
- **INPUTS:** Models/geometry, parameters, scenarios, measured data for calibration.
- **OUTPUTS:** Metrics, plots, pass/fail vs. requirements, validity-envelope updates.
- **DEPENDENCIES:** Simulator backends, compute (CPU/GPU), Engineering Lab, Hardware awareness.
- **FAILURE MODES:** Garbage-in (wrong units/params); numerical instability; extrapolation beyond validity; false confidence.
- **RECOVERY:** Convergence/mesh-independence checks; automatic fidelity escalation on borderline results; refusal to report out-of-envelope results as "verified."
- **SECURITY:** Sandboxed execution of generated simulation code; resource quotas.
- **TESTING:** Benchmark against analytic solutions and published cases; regression on cached scenarios.
- **FUTURE EXPANSION:** Differentiable/surrogate sims; GPU-accelerated batch search.

---

## 16. Voice architecture

**Reality:** streaming STT/TTS/duplex models are **[NOW]**; **reference-aware continuity** is **[CUSTOM]**.

```
Mic → VAD/endpointing → streaming STT ─► Intent Parser ─► Executive
                                  ▲ barge-in detection        │
Speaker ◄ streaming TTS ◄ Response Planner ◄────────────────┘
                 └─ interruptible: speech cancels the current utterance AND signals "user took the floor"
```

**The real problem is reference resolution, not speech.** "Make the chassis lighter" → resolve *chassis* against the **active-object stack** (recently touched/focused entities from the Project World + UI focus + gaze/cursor if available). "Actually, undo that" → resolve *that* to the **most recent reversible action event in the log** and invoke its recorded inverse. This works *because* of design laws 3 and 4 (log is truth; every action declares an inverse). Ambiguity above threshold → one short disambiguating question.

### Subsystem spec — Voice

- **PURPOSE:** Continuous, interruptible, context-aware spoken interaction.
- **INPUTS:** Audio stream, active-object stack, event log.
- **OUTPUTS:** UserEvents (with confidence), spoken responses, barge-in signals.
- **DEPENDENCIES:** STT/TTS providers (cloud or local Whisper-class + local TTS), Executive, World/Project models.
- **FAILURE MODES:** Misrecognition of names/numbers; false wake/barge-in; wrong referent; latency breaking conversational flow; ambient audio injecting commands.
- **RECOVERY:** Read-back for consequential/low-confidence commands ("Reducing wall thickness on the chassis from 3 to 2 mm — go?"); undo always available; confirm Class 3+ by explicit phrase, never by ambient audio alone.
- **SECURITY:** Speaker verification for privileged commands; voice never authorizes Class 4/5 alone; local processing option for privacy; retention policy for audio.
- **TESTING:** Word-error-rate on domain vocabulary; reference-resolution accuracy on scripted dialogues; end-to-end latency budget (target < 800 ms to first audio — UNCERTAIN, measure).
- **FUTURE EXPANSION:** Prosody/emotion awareness; multi-speaker; ambient-room mode.

---

## 17. Vision architecture

- **Screen understanding:** accessibility tree first (structured, exact) → OCR → vision-language model for layout/semantics → pixel coordinates only to click.
- **Document/diagram understanding:** VLMs + OCR + table extractors; schematics/CAD drawings with domain-specific parsing.
- **Physical-world vision (lab):** cameras for print monitoring, part inspection (OpenCV + detection models), calibration targets for measurement. Measurement-grade vision requires calibration; VLM "looks about right" is not measurement.
- **Temporal:** keyframe + diff, not continuous video to a model (cost/latency law).

### Subsystem spec — Vision

- **PURPOSE:** Turn pixels into grounded, checkable state.
- **INPUTS:** Screenshots, camera frames, documents.
- **OUTPUTS:** Element maps, text, detections, measurements with uncertainty.
- **DEPENDENCIES:** VLMs via Router, OCR, OpenCV, camera drivers.
- **FAILURE MODES:** Misread text; hallucinated UI elements; resolution/scaling errors; lighting/calibration drift; adversarial on-screen text.
- **RECOVERY:** Cross-check against the accessibility tree/DOM; second-opinion model on disagreement; calibration routines; "I can't read this reliably" is a valid output.
- **SECURITY:** Screen capture limited to authorized windows/regions; sensitive-region masking (password fields); retention limits; screen text `UNTRUSTED`.
- **TESTING:** Labeled screenshot suite (element-localization accuracy), OCR accuracy, measurement error vs. calipers.
- **FUTURE EXPANSION:** 3D scene understanding; real-time inspection loops; multi-camera fusion.

---

## 18. Security architecture

**Threat model (assets: user data, credentials, machines, money, physical safety):**

| Threat | Vector | Control |
|---|---|---|
| **Prompt injection** | Web pages, emails, files, screen text, tool output | Taint tracking: all external content is `UNTRUSTED`; untrusted content can't originate tool calls or permission changes; "instruction detector" is defense-in-depth, **not** the primary control |
| Confused deputy | Agent with broad tools coaxed to misuse | Capability-based grants, scoped per goal, expiring |
| Credential theft | Prompts/logs/memory | Vault; secrets never in model context; redaction pipeline; secret scanning of logs/memory |
| Data exfiltration | Tool that can send data out | Egress allowlist; data-class gating; Class 3 approval for new destinations |
| Malicious plugin/tool | Supply chain | Signed manifests, sandboxing, declared capabilities, review |
| Memory poisoning | Fake "facts" persisted | Provenance + quarantine + verification before trust |
| Runaway cost/DoS | Loops | Hard budgets; circuit breakers |
| Governance tampering | Self-improvement or injection edits rules | Governance store is read-only to agents; signed, human-approved updates |
| Physical harm | Actuators, heaters, motors | Hardware interlocks; Class 4 gate; limits enforced below the software layer |

**Core security principle:** *security is enforced in the Capability Guard (deterministic code), never by asking a model to behave.* Models can be fooled; a permission check cannot be talked into anything.

### Subsystem spec — Security

- **PURPOSE:** Contain the damage any single component (including a compromised model) can do.
- **INPUTS:** Every Step, tool manifest, data classification, taint labels.
- **OUTPUTS:** Allow/deny/escalate decisions, audit records, alerts.
- **DEPENDENCIES:** Capability Guard, vault, sandbox runtime (containers/gVisor/Firecracker/VMs), event log.
- **FAILURE MODES:** Taint-tracking gaps; sandbox escape; over-broad grants; alert fatigue → rubber-stamping.
- **RECOVERY:** Revocation of all grants in one command; quarantine mode (read-only); credential rotation runbook; restore from checkpoint.
- **SECURITY:** (this *is* the subsystem) — plus independent review, red-team suite run in CI.
- **TESTING:** Adversarial prompt-injection corpus (must produce zero unauthorized actions — the metric is *actions*, not *refusals*); fuzzing of tool schemas; penetration tests of the sandbox.
- **FUTURE EXPANSION:** Hardware attestation; formal verification of the Guard's policy engine; per-tool information-flow types.

---

## 19. Permission system

| Class | Meaning | Examples | Default policy |
|---|---|---|---|
| **0** | Observation, read-only | read file, list processes, web GET to allowlisted domain | Auto-allow |
| **1** | Safe local reversible | write to scratch dir, create branch, open app | Auto-allow within goal scope; auto-checkpoint |
| **2** | Project modification | edit repo files, run build/tests, install dev deps in env | Allowed per-project grant; checkpoint + diff recorded |
| **3** | External action | send message/email, post, call external write-APIs, push to remote | Per-destination grant; draft→approve unless standing grant |
| **4** | Financial / security / sensitive / physical-actuation | spend money, change auth/keys, access private data, run motors/heaters, flash firmware | **Explicit human authorization every time**, with the exact action shown |
| **5** | Destructive / irreversible | delete data, force-push, drop DB, wipe disk | Explicit confirmation + **mandatory backup/snapshot first** where technically possible; no standing grants |

**Rules:** classes are properties of **tool + arguments**, computed by the tool's manifest and a deterministic argument analyzer (e.g. `rm` with `-rf` outside scratch → Class 5), not by the model. Grants are **capabilities**: `{class, scope(path/domain/project), expiry, max_uses, issued_by}`. The Guard takes the **max** class of anything a plan step could do. Escalation prompts show *what, where, why, how to undo*, in ≤ 5 lines. Autonomy grows by widening *scoped grants with evidence of reliability*, never by loosening the classes.

### Subsystem spec — Capability Guard

- **PURPOSE:** Deterministically enforce human authority over consequential actions.
- **INPUTS:** Step + resolved arguments, grants, taint labels, goal scope.
- **OUTPUTS:** ALLOW / DENY / ESCALATE(with prompt) + audit event.
- **DEPENDENCIES:** Tool manifests, argument analyzers, grant store, UI/voice for authorization.
- **FAILURE MODES:** Misclassified tool/argument (under-classification is the dangerous direction); grant scope creep; approval fatigue; bypass via tool composition (each step Class 1, combined effect Class 5).
- **RECOVERY:** Fail-closed on unknown tools/args; **plan-level** effect analysis (not just per-step); periodic grant review; classification tests on every new tool.
- **SECURITY:** Guard code and grant store outside agent write access; changes require out-of-band human approval.
- **TESTING:** Property tests ("no sequence of allowed Class≤2 steps can delete outside scope"); classification corpus with known-dangerous arguments; mutation testing of the policy.
- **FUTURE EXPANSION:** Formal policy language; per-user risk profiles; anomaly detection on action patterns.

---

## 20. Verification system (SEXTANT)

**Rule: CLAIMS REQUIRE EVIDENCE.** A **Verifier** is a typed, executable check: `verify(claim, context) → {passed, evidence, confidence}`.

| Claim type | Verifier |
|---|---|
| Code works | Unit/integration tests, type-check, lint, build |
| Code is faster | Benchmark with warmup, N runs, variance, statistical test |
| Code is secure | SAST, dependency audit, secret scan, targeted tests |
| File operation | State check: existence, hash, permissions, diff |
| Automation | Postcondition observation (DOM/file/process) |
| Research claim | Quote-in-source check, independent-source count |
| Simulation | Convergence + validity-envelope check |
| Hardware | Calibrated measurement |
| "User wanted X" | Read-back confirmation, preference check |

**Adversarial review gate** (for important results): an independent critic (different model family where possible) must answer: *weak assumptions? overlooked cases? catastrophic failure mode? is the evidence sufficient? is this merely the easiest solution? is there a simpler architecture? are we solving the wrong problem? was it verified?* — objections must be **falsifiable** (propose a test/source), and the Executive then runs the test rather than debating it.

**Verifier trust problem:** a verifier written by the same model that wrote the code can share its blind spots. Mitigations: tests written *before* implementation where possible; mutation testing to check the tests can fail; independent-model test authorship; human-authored acceptance criteria for high-stakes goals. **Verifier-of-last-resort** (the final acceptance check) is governance-protected (§28).

### Subsystem spec — Verification

- **PURPOSE:** Ensure no completion claim is made without evidence.
- **INPUTS:** Claims, artifacts, success criteria.
- **OUTPUTS:** Evidence records, pass/fail, confidence, gaps.
- **DEPENDENCIES:** Test runners, benchmark harness, analyzers, Critic specialist, Tool Runtime.
- **FAILURE MODES:** Weak/vacuous tests; flaky tests masking regressions; verifier-author correlation; "verified the wrong thing"; benchmark noise read as signal.
- **RECOVERY:** Mutation score threshold; flake quarantine *with tracking* (never silent skipping); statistical significance requirements; unverifiable claims are reported as such.
- **SECURITY:** Verifier code integrity; verifiers run sandboxed; agents can't weaken acceptance criteria without human approval.
- **TESTING:** Verifiers are tested against **known-good and known-bad artifacts** (seeded bugs must be caught — the verifier's own recall is a tracked metric).
- **FUTURE EXPANSION:** Formal methods for critical modules; property-based/spec-derived test generation; learned anomaly verifiers.

---

## 21. Recovery architecture

- **Checkpoints:** before any Class ≥ 1 mutation: git commit/stash for code; filesystem snapshots (btrfs/ZFS/APFS/VSS or copy-on-write copies) for data; DB savepoints; app-specific export. **Recovery point = (state ref, event-log offset).**
- **Versioning verbs:** `CHECKPOINT · BRANCH · EXPERIMENT · COMPARE · MERGE · ROLLBACK`. Experiments run on isolated branches/worktrees/containers.
- **Emergency protocol** (triggered by invariant violation, unexpected state, guard anomaly, or user "stop"):
  `STOP UNSAFE ACTIONS → PRESERVE STATE (snapshot, freeze logs) → COLLECT DIAGNOSTICS → IDENTIFY IMPACT (diff vs. last verified) → ATTEMPT SAFE RECOVERY (roll back to last verified checkpoint, only if rollback itself is safe) → REPORT (what happened, what's affected, what was restored, what needs you)`.
- **Diagnostic protocol** (before changing code in response to a failure): `symptom → evidence → hypotheses → rank by (likelihood × cheapness-to-test) → discriminating tests → root cause → design fix → verify fix → add regression test → write Failure Memory`.

### Subsystem spec — Recovery Manager

- **PURPOSE:** Make every action undoable or explicitly flagged as not, and make failure survivable.
- **INPUTS:** Pre-action state requests, failure signals, user "undo/stop".
- **OUTPUTS:** Checkpoints, restored states, incident reports.
- **DEPENDENCIES:** VCS, snapshot-capable storage, event log, Capability Guard.
- **FAILURE MODES:** Checkpoint itself fails or is incomplete; rollback destroys newer legit work; external side effects (sent emails) can't be rolled back; storage exhaustion; corrupted log.
- **RECOVERY:** Verify checkpoints (restore-test sampling); **compensating actions** for external effects (retraction, correction message — drafted, Class 3); log is replicated + hash-chained for tamper/corruption detection; if no checkpoint is possible → action is promoted to Class 5.
- **SECURITY:** Backups encrypted; recovery operations are themselves guarded; ransomware-resistant (append-only/offsite copies).
- **TESTING:** **Game-day drills** in CI: kill the process mid-operation, corrupt a file, fill the disk, drop the network, then assert recovered state equals last verified state.
- **FUTURE EXPANSION:** Continuous snapshotting; cross-device recovery; automatic incident post-mortems.

---

## 22. Observability

**Everything is an event**; "why did you do that?" is a query.

```
Event{ id, ts, goal_id, step_id, actor(user|executive|specialist|tool|model|probe),
       type, inputs_ref, outputs_ref, model_meta?, cost?, parent_ids[], hash_prev }
```

- **Explainability query:** walk `parent_ids` from the action back to the Decision, Evidence, and user Intent; render ≤ 6 lines: *the goal → the evidence → the alternatives considered → why this one.*
- **Metrics (§33):** success, latency, cost, tool accuracy, hallucination, recovery, interventions.
- **Tracing:** OpenTelemetry-compatible spans for model calls and tools; **replay**: re-run a session against recorded model outputs to reproduce bugs deterministically.
- **Redaction:** secrets and sensitive data are tokenized before they hit logs.

### Subsystem spec — Observability

- **PURPOSE:** Make every autonomous act inspectable, explainable, and replayable.
- **INPUTS:** All events.
- **OUTPUTS:** Explanations, dashboards, traces, replays, audits.
- **DEPENDENCIES:** Event log, metrics store, UI.
- **FAILURE MODES:** Log volume/cost; PII in logs; logs omitted at crash time; explanation that rationalizes rather than reports.
- **RECOVERY:** Write-ahead (log intent *before* acting, outcome after); tiered retention; explanations are generated *from recorded decision records*, not model recollection.
- **SECURITY:** Access control on logs; tamper-evident hash chain; redaction.
- **TESTING:** "Explain this action" accuracy audit vs. ground-truth causal chain; replay-determinism tests.
- **FUTURE EXPANSION:** Anomaly detection; automatic regression bisection across sessions.

---

## 23. User interface

**Principle:** the UI is a **projection of kernel state**, reorganized around the current objective. Remove every pixel that isn't state, control, or evidence (Stark Test 2).

**Persistent core (always visible, small):** Current Objective · Status (idle/planning/acting/waiting-on-you) · Budget burn · Active specialists · *Pending decisions* · Kill switch.

**Context workspaces (auto-selected, user-overridable):**

| Mode | Shows |
|---|---|
| Coding | Architecture/impact graph, diff, tests, logs, benchmark delta |
| Research | Claim ledger, sources, contradictions, confidence labels |
| Design | Model viewport, parameters, simulation results vs. requirements |
| Computer control | Active app, current ActionContract, expected vs. observed, recovery point |
| Idle | Collapsed; only pending decisions & alerts |
| Diagnostics | Event timeline, causal "why" view, memory & failure hits |

**Interaction:** text/voice/CLI equal citizens; **outcome-first** requests; the system presents **evidence** with results ("p95 startup 812→574 ms, n=30, 3 tests added, rollback point `cp_41`"). Notifications are rationed by a *value-of-information* threshold.

**Delivery plan:** Phase 1–8 UI = terminal + local web dashboard (TypeScript/React reading the event stream). Rich spatial/3D "lab" views come with Phase 9 — when there is geometry worth showing.

### Subsystem spec — UI

- **PURPOSE:** Reveal useful system state and give the human fast, safe control.
- **INPUTS:** Event stream, view-models from Project/World/Verification.
- **OUTPUTS:** User events, approvals, overrides.
- **DEPENDENCIES:** Kernel event API, auth.
- **FAILURE MODES:** Information overload; stale display; approval-fatigue UX; UI divergence from true state.
- **RECOVERY:** UI is stateless (rebuild from log); heartbeat/staleness indicator; kill switch independent of UI render loop.
- **SECURITY:** Authenticated local-only by default; approval prompts show exact action text from the Guard (not model-authored summaries); anti-clickjacking for approvals.
- **TESTING:** Usability tests on "time to correct decision at an approval prompt"; golden-state UI snapshots; accessibility checks.
- **FUTURE EXPANSION:** AR/VR lab; multi-device handoff; shared team workspaces.

---

## 24. Hardware architecture

**Hardware awareness** (World Model feeds the Router): CPU/GPU/VRAM/RAM/disk/power/temp/network are **inputs to routing**: "run local 8B model on GPU" vs. "use cloud" vs. "defer until plugged in."

| Tier | Hardware | Role | Reality |
|---|---|---|---|
| **T0 (this sandbox)** | 4 vCPU / 15 GB / no GPU | Kernel + cloud providers + small local embedding model (CPU) | Measured |
| **T1 Workstation** | 8–16 cores, 64 GB, 24 GB-VRAM GPU | + local 7–32B quantized LLMs, local Whisper/TTS, YOLO-class vision, MuJoCo/FEA | [NOW] |
| **T2 Lab node** | T1 + microcontroller bench, cameras, 3D printer/CNC controllers | + HIL testing, print monitoring | [CUSTOM] |
| **T3 Fleet** | Multiple machines + cloud GPUs | Distributed specialists, batch sims | [CUSTOM] |

**Cloud/local split principle (§25):** *privacy and latency pull local; capability and elasticity pull cloud.* The Router's data-class gating decides, not a static config.

### Subsystem spec — Hardware Awareness

- **PURPOSE:** Adapt strategy to actual machine capacity.
- **INPUTS:** Telemetry (psutil, NVML, SMART, battery/thermal APIs).
- **OUTPUTS:** Capacity answers, thermal/power throttling decisions, model-fit predictions.
- **DEPENDENCIES:** OS APIs, drivers.
- **FAILURE MODES:** Thermal throttle mid-job; OOM; VRAM fragmentation; power loss.
- **RECOVERY:** Headroom reserve; job checkpointing; spill-to-cloud fallback (if policy permits); graceful degradation order defined in advance.
- **SECURITY:** Telemetry is read-only; remote nodes mutually authenticated (mTLS).
- **TESTING:** Resource-pressure tests (limit memory/CPU via cgroups); model-fit prediction accuracy.
- **FUTURE EXPANSION:** Energy-aware scheduling; dynamic model offload; edge devices.

## 25. Cloud/local split

| Component | Local | Cloud | Rationale |
|---|---|---|---|
| Event log, memory, project world | **Primary** | Encrypted backup/sync | Ownership, privacy, latency |
| Capability Guard, vault, kill switch | **Always local** | — | Must not depend on network |
| Executive kernel | Local | Optional remote worker | Control stays with the user |
| Frontier reasoning/coding | Fallback only for private data | **Primary** for capability | Best models are hosted |
| Embeddings, rerank, small routing models | **Local** | Optional | Cheap, private, high volume |
| STT/TTS | Local (Whisper-class) preferred | Cloud for quality | Latency & privacy vs. fidelity |
| Heavy sims/batch | Local if GPU | Burst to cloud | Elasticity |

**Offline behavior:** degrade, don't die — local models + queued external actions + clear "operating offline" state.

## 26. Model/provider abstraction

```
interface ModelProvider {
  capabilities(): CapabilityCard
  complete(req: TypedRequest): Stream<TypedEvent>   // text, tools, images, audio, structured output
  count_tokens(...): number
  health(): HealthStatus
}
```

- One **adapter per provider** (Anthropic, OpenAI, Google, local via llama.cpp/vLLM/Ollama, future). Vendor-specific features (caching, extended reasoning, computer-use tool formats) are exposed as **optional capabilities** with graceful fallback.
- **Canonical internal message/tool schema**; adapters translate. Prompts are **templated per model family** from role definitions (a prompt is a compiled artifact, tested per model).
- **Structured output** is validated against JSON Schema/pydantic; failures retry with error feedback up to a bound, then escalate.

### Subsystem spec — Provider Abstraction

- **PURPOSE:** Make models interchangeable processors.
- **INPUTS:** Canonical requests.
- **OUTPUTS:** Canonical responses + usage metadata.
- **DEPENDENCIES:** Provider SDKs/HTTP, credential vault.
- **FAILURE MODES:** Semantics drift between providers (tool-call formats, stop reasons); streaming edge cases; deprecations.
- **RECOVERY:** Conformance test suite every adapter must pass; version pinning; adapter-level retries/backoff/circuit-breakers.
- **SECURITY:** Keys via vault only; TLS; no training-data opt-ins by default (where configurable); per-provider data-class limits.
- **TESTING:** Shared conformance suite; recorded-fixture tests; live smoke tests on schedule.
- **FUTURE EXPANSION:** Local fine-tunes; speculative multi-provider decoding; federated model pools.

## 27. Plugin/tool architecture

**Tool manifest (declarative, signed):**

```yaml
name: git.commit
version: 1.2.0
description: ...
input_schema: {...JSON Schema...}
output_schema: {...}
permission: {base_class: 2, argument_rules: [...]}   # Guard computes final class
preconditions: [repo_clean_or_staged]
postconditions: [head_changed, tree_matches_staged]
inverse: git.reset_to(prev_head)                     # or IRREVERSIBLE
idempotent: false
side_effects: [fs:repo]
timeouts: {...}   cost_estimate: {...}
sandbox: {fs: [repo], net: none}
```

- Runtime: tools run in **sandboxed workers** with only manifest-declared capabilities. **MCP** is supported as one *transport* for external tools (**[NOW]**), wrapped by manifests so unmanifested MCP tools are Class-4 by default (fail-closed).
- **Tool selection** is retrieval over manifests (semantic + capability match) so the model sees only relevant tools — keeps context small and attack surface small.

### Subsystem spec — Tool Runtime

- **PURPOSE:** Controlled, observable, verifiable external capability.
- **INPUTS:** Validated tool calls from approved Steps.
- **OUTPUTS:** Typed results, postcondition checks, side-effect records.
- **DEPENDENCIES:** Manifests, sandbox, Guard, Recovery, Verification.
- **FAILURE MODES:** Manifest lies about effects; tool hangs; partial effects on failure; output injection.
- **RECOVERY:** Timeouts + kill; observed-effects auditing (diff filesystem/network vs. declaration → flag liars); partial-failure compensation via inverse.
- **SECURITY:** Signed manifests, least privilege, seccomp/container sandbox, egress control, output tagged `UNTRUSTED`.
- **TESTING:** Per-tool contract tests (pre/postconditions actually hold); sandbox escape tests; effect-declaration audits.
- **FUTURE EXPANSION:** Marketplace with reputation; tool synthesis by the system (sandboxed, reviewed, Class-gated).

## 28. Self-improvement architecture

**Allowed to self-modify (through the Improvement Loop):** prompts, routing weights, memory retrieval parameters, workflow templates, context-packing heuristics, benchmark sets (additions only), tool-selection rankings, proposed code changes (as PRs).

**Not allowed to self-modify:** Capability Guard, permission classes, grants, vault, kill-switch, governance store, the verifier-of-last-resort, audit logging, the Improvement Loop's own acceptance gate.

**Loop:** `detect recurring failure/inefficiency (from log + metrics) → hypothesize change → implement as candidate → run frozen benchmark suite (A/B vs. baseline, n sufficient for significance) → check no regression on safety suite → stage (shadow mode) → human approval for anything beyond prompt/route tuning → promote → monitor → auto-rollback on regression.` Goodhart defense: held-out evaluation sets that the loop can't see; periodic human spot audits.

### Subsystem spec — Improvement Loop

- **PURPOSE:** Measurable capability gains from operating experience, without eroding safety.
- **INPUTS:** Metrics, failure memory, benchmark suites.
- **OUTPUTS:** Candidate changes, A/B reports, promoted/rolled-back changes.
- **DEPENDENCIES:** Observability, Eval Harness, Router, Memory, Governance.
- **FAILURE MODES:** Overfitting to benchmarks (Goodhart); silent behavior drift; optimizing a proxy; self-introduced vulnerabilities.
- **RECOVERY:** Versioned configs with one-command rollback; held-out sets; shadow deployment; drift monitors.
- **SECURITY:** Governance separation (above); candidate code is reviewed and sandbox-tested; signed releases.
- **TESTING:** Meta-evaluation — inject a known-harmful "improvement" and confirm the gate rejects it.
- **FUTURE EXPANSION:** Learned routers, distilled specialist models, automated architecture proposals (human-reviewed).

## 28a. Proactive intelligence (policy)

Triggers: dependency end-of-life/CVE, missing backups, perf regression, new model beating incumbent on *our* benchmarks, repeated manual workflow → automation candidate. **Rules:** value-of-information threshold; per-user daily cap; batched digests over interrupts except safety-critical; every proactive suggestion is a *proposal* (Class 0 to create; the action it suggests is gated normally); dismissal teaches suppression. **[EXP]**

---

## 29. Failure scenarios (Stage-5 attack on the chosen architecture)

| # | Scenario | Expected behavior | Mechanism |
|---|---|---|---|
| 1 | Model returns plausible wrong info | Caught by verifier or flagged unverified | Verification gate; claim tiers |
| 2 | Model output malformed | Retry with error, escalate model, fail visibly | Schema validation |
| 3 | Provider outage mid-task | Fallback route; resume from log | Router, event sourcing |
| 4 | Network drops | Offline mode; queue external actions; local models | Cloud/local split |
| 5 | User interrupts mid-execution | Halt at next safe point; keep state; offer resume/rollback | Cooperative cancellation + checkpoint |
| 6 | Memory/index corrupted | Rebuild from log | Derived memory |
| 7 | Event log corrupted | Hash-chain detects; restore replica; quarantine mode | Replication |
| 8 | Two specialists disagree | Discriminating test → evidence → human | Arbiter |
| 9 | Computer-control action fails halfway | Stop, classify, roll back transaction, replan | ActionContract + checkpoint |
| 10 | App popup hijacks focus | Fresh observation detects mismatch; no blind chaining | Observe-before-act |
| 11 | Prompt injection in a web page | Tainted content cannot originate actions | Guard + taint tracking |
| 12 | Plugin lies about its effects | Observed-effect audit flags it; sandbox limits blast | Tool Runtime |
| 13 | Runaway loop/cost | Budget breaker; emergency stop | Executive budgets |
| 14 | Router mis-routes on stale benchmarks | Drift canary; fallback to stronger model on verifier failure | Registry freshness |
| 15 | Silent model update changes behavior | Canary evals detect; pin versions | Benchmark harness |
| 16 | Verifier shares author's blind spot | Independent-model tests; mutation testing | Verification design |
| 17 | Self-improvement degrades safety | Safety suite gate; held-out sets; rollback | Improvement Loop |
| 18 | Rollback itself is unsafe | Precheck: restore-test; if unsafe, freeze & ask | Recovery Manager |
| 19 | Disk full during checkpoint | Abort action *before* mutating | Pre-flight resource check |
| 20 | Credential leaks into logs | Redaction + secret scan + rotation runbook | Observability/Security |
| 21 | Ambient audio speaks a command | Voice can't authorize Class ≥ 3; speaker verification | Voice/Guard |
| 22 | "Undo that" ambiguous | Resolve against action log; confirm if >1 candidate | Voice, Log |
| 23 | Simulation disagrees with measurement | Update model; shrink validity envelope; flag designs | Simulation |
| 24 | Hardware fault during actuation | Hardware interlock/e-stop independent of software | Lab safety |
| 25 | Conflicting user instructions across time | Surface conflict; ask | Executive ask-policy |
| 26 | Time-sensitive fact is stale | Re-verify; flag age | Research/World Model |
| 27 | Cross-project data leak via memory | Namespaces; data-class gating | Memory/Security |
| 28 | Plan-level composition of "safe" steps does harm | Plan-level effect analysis | Guard |
| 29 | Human rubber-stamps approvals | Rare, specific, minimal prompts; periodic review; undo | UI/Guard |
| 30 | Governance rules edited by injected agent | Governance read-only to agents; signed updates | Self-improvement boundary |

### Seed Failure Log (Phase 0 — rejected architectures and false assumptions)

| ID | WHAT FAILED | WHY | WHAT WE LEARNED | WHAT CHANGES NEXT |
|---|---|---|---|---|
| F-001 | Free-running agent swarm (Arch B) as primary design | No arbiter, shared mutable state, injection risk, unexplainable | Parallelism needs a single authority and typed contracts | Specialists are roles under the Executive |
| F-002 | Microservices-first (Arch D) | Operational cost with no single-user benefit; adds failure modes | Process boundaries are a *later* decision; keep message seams | In-process kernel, event interface |
| F-003 | Human-approves-everything (Arch A) | Human bottleneck; approval fatigue destroys safety | Safety = permission *classes* + scoped grants, not blanket prompts | Class-based Guard |
| F-004 | "Chat history as memory" assumption | Context-window limits, cost, noise, no provenance | Memory must be external, structured, retrieved | Memory architecture (§9) |
| F-005 | "Ask the model to be safe" as security | Models are manipulable | Enforce in deterministic code | Capability Guard |

---

## 30. Hard architectural questions (open — each is a Phase 0 research ticket)

1. **Event-sourcing vs. model nondeterminism:** how do we make replay faithful when model outputs are recorded but *prompts evolve*? (Version prompt artifacts as events?)
2. How large can the event log get before replay/rebuild is impractical, and what's the snapshot/compaction strategy that preserves auditability?
3. What's the best **plan representation** — free-form NL, typed DAG, or code (plan-as-program) — for reliability vs. flexibility?
4. How do we **detect goal drift** in long-horizon tasks objectively?
5. Can **taint tracking** be made precise enough to be useful without blocking most legitimate work? (Information-flow types over tool I/O?)
6. How do we classify permission class for **arbitrary shell commands** soundly? (Allowlisted grammar? Sandbox-by-default and classify by *observed* effects?)
7. What's the **minimal verifier** set that covers 80% of engineering claims?
8. How do we get **independent errors** from critics (model diversity vs. prompt diversity vs. tool-grounded checks)?
9. When does **multi-model debate beat a single strong model** with a good verifier — per task type — and what's the cost-adjusted break-even?
10. How should the Router **learn** from sparse, noisy outcome data without overfitting? (Contextual bandits? Offline eval only?)
11. How do we benchmark **long-horizon** capability economically?
12. What's the right **memory write policy** to prevent poisoning without making memory useless?
13. How should memory **forget**? (Decay, supersession, user-driven, regulation-driven.)
14. How do we resolve **conflicts between memory and fresh observation** (the world changed)?
15. What's the representation for the **active-object stack** that makes "that/it/the chassis" resolution reliable across voice, UI, and CLI?
16. How do we compute a **reliable inverse** for actions in applications that don't expose undo?
17. How do we make **GUI automation robust** to app updates and localization? (Affordance memory? Accessibility-first?)
18. What is the **right checkpoint granularity** for computer control (per action, per transaction, per goal)?
19. How do we guarantee the **kill switch** works when the kernel is wedged? (Out-of-process watchdog; OS-level hotkey; hardware e-stop for actuators.)
20. How should **cost budgets** be allocated across a plan DAG, and renegotiated mid-flight?
21. What's the **data classification** scheme users can actually maintain, and how is it inferred automatically with low false-negative rate?
22. How do we sandbox **generated code** (sims, tools) strongly enough for untrusted-origin influence yet fast enough to be practical?
23. How do we validate **sim-to-real correspondence** automatically and decide when a model is "good enough"?
24. What's the correct **fidelity-escalation policy** in simulation (when is a cheap sim's "pass" trustworthy)?
25. How do we handle **units and tolerances** so the lab never ships a mm/inch error?
26. How do we prevent the Improvement Loop from **Goodharting** its own benchmarks?
27. How do we **audit self-improvement** at human-reviewable granularity?
28. What's the **UI mechanism** that reorganizes around the objective without disorienting the user?
29. How do we measure **hallucination rate** in the wild (not just on benchmarks)?
30. How do we express and evaluate **uncertainty** so that "LIKELY" means something calibrated?
31. How do we **version prompts** and manage prompt/model co-evolution?
32. What are the right **autonomy ramps** — how does PRAXIS earn wider grants from demonstrated reliability, and how does the user inspect that ledger?
33. How do we run **multi-device** operation with a consistent log (CRDT? single-writer leader?)
34. What's the **privacy model for voice/screen capture** — what's retained, for how long, and who can see it?
35. What's the **legal/ethical envelope** for proactive monitoring of the user's own machine and data?

## 31. Technology feasibility matrix

| Capability | Tag | Basis | Main risk | Key tech |
|---|---|---|---|---|
| Event-sourced kernel | **AVAILABLE NOW** | Standard pattern | Design discipline | SQLite→Postgres, hash chain |
| Provider abstraction + router | **AVAILABLE NOW** | Many existing gateways | Evidence quality for routing | Own adapters, pydantic, JSON Schema |
| Structured tool use w/ manifests | **AVAILABLE NOW** | Provider tool APIs + MCP | Misclassification | JSON Schema, sandboxing |
| Hybrid memory/retrieval | **AVAILABLE NOW** | Vector+BM25 mature | Poisoning, relevance | SQLite-vec/pgvector, local embeddings |
| Capability Guard / permissions | **CUSTOM DEVELOPMENT** | Known principles | Composition attacks | Policy engine, sandbox |
| Project World graph | **CUSTOM DEVELOPMENT** | Static analysis mature | Dynamic code blind spots | tree-sitter, LSP |
| World Model | **CUSTOM DEVELOPMENT** | Probes exist | Staleness | psutil, NVML, inotify |
| Verification framework | **CUSTOM DEVELOPMENT** | Tests/benchmarks exist | Verifier quality | pytest, hyperfine-style benchmarking |
| Recovery/checkpoints | **AVAILABLE NOW** (code) / **CUSTOM** (apps) | git, snapshots | External side effects | git, btrfs/ZFS, containers |
| Research engine w/ claim ledger | **CUSTOM DEVELOPMENT** | Search/fetch exist | Citation fabrication | Fetch + quote verification |
| Multi-agent pipelines | **CUSTOM DEVELOPMENT** | Frameworks exist but immature | Cost, correlated errors | Own runtime |
| Voice (streaming STT/TTS) | **AVAILABLE NOW** | Mature | Latency tuning | Whisper-class, streaming TTS |
| Voice reference resolution | **CUSTOM DEVELOPMENT** | Needs log + object stack | Ambiguity | Active-object stack |
| Screen understanding | **AVAILABLE NOW**/**EXPERIMENTAL** | A11y + VLM | Pixel unreliability | AX/UIA, Playwright, VLM |
| GUI computer control | **EXPERIMENTAL** | Improving, brittle | Reliability | ActionContracts, VMs |
| Code-first CAD | **AVAILABLE NOW** | CadQuery, OpenSCAD | Geometry correctness | build123d |
| Rigid-body sim | **AVAILABLE NOW** | MuJoCo, PyBullet | Sim-to-real gap | |
| FEA pipeline | **CUSTOM DEVELOPMENT** | CalculiX/FEniCS | Meshing robustness | |
| Electronics (KiCad scripting) | **CUSTOM DEVELOPMENT** | API exists | Layout quality | |
| Firmware + HIL | **CUSTOM DEVELOPMENT** | PlatformIO etc. | Hardware safety | |
| Autonomous closed-loop design | **RESEARCH PROBLEM** | Early research | Everything | |
| Local LLMs for routine steps | **AVAILABLE NOW** (with GPU) | llama.cpp/vLLM | Capability gap vs. frontier | |
| Self-improvement of prompts/routing | **EXPERIMENTAL** | A/B infra feasible | Goodhart | |
| Self-modifying governance | **CURRENTLY IMPRACTICAL (and prohibited)** | — | — | Deliberately excluded |
| Reliable multi-day unattended autonomy on novel, high-stakes goals | **CURRENTLY IMPRACTICAL** | Compounding error rates | | |
| Holographic UI / cinematic interface | Not capability | Fails Stark Test 2 | | Deferred, optional skin |

---

## 32. Development roadmap

Each phase is **gated by proof**. Template: OBJECTIVE · DEPENDENCIES · IMPLEMENTATION · TESTS · BENCHMARKS · FAILURE CONDITIONS · ROLLBACK · COMPLETION CRITERIA.

**Stack decision (Phase 1, revisitable via ADR):** Python 3.11+ kernel (ecosystem for models, sims, CAD, ML), `pydantic` for contracts, SQLite (WAL) event log, `pytest` + `hypothesis`, FastAPI + SSE for the event API, TypeScript/React dashboard later. Rationale recorded as a Decision, not dogma — Rust can replace the Guard/kernel hot paths later behind the same interfaces.

### PHASE 0 — Research + Architecture *(this document)*
- **OBJECTIVE:** Settle contracts and the highest-risk questions.
- **DEPENDENCIES:** none.
- **IMPLEMENTATION:** this doc; ADRs; **spikes only** (throwaway, labeled): replay determinism, GUI task reliability baseline, guard classification of shell commands, router benchmark design.
- **TESTS/BENCHMARKS:** each spike has a pre-registered success threshold.
- **FAILURE CONDITIONS:** a spike invalidates a core assumption (e.g. replay impossible).
- **ROLLBACK:** revise this document (Revision N+1) with Failure Log entries.
- **COMPLETION:** Questions Q1, Q3, Q5, Q6, Q19 have written, evidence-backed answers; contracts (Intent/Goal/Plan/Step/Evidence/Event) frozen at v0.1.

### PHASE 1 — Executive Core
- **OBJECTIVE:** Durable objective management and orchestration around the event log.
- **DEPENDENCIES:** Phase 0.
- **IMPLEMENTATION:** event log (hash-chained); contracts; Executive loop (intent → goal → plan DAG → dispatch → verify gate); budgets; scripted-model harness; CLI adapter.
- **TESTS:** property tests (no Step without guard decision; no "done" without evidence record); replay determinism; crash-recovery (kill -9 at random points → resume correctly).
- **BENCHMARKS:** step overhead < 10 ms excluding model/tool time; resume-after-crash success 100% on 1,000 randomized kill points.
- **FAILURE:** any lost event; any unverified completion; non-reproducible replay.
- **ROLLBACK:** log is append-only; code via git tags per milestone.
- **COMPLETION:** a scripted multi-step goal survives injected failures and produces an evidence-backed completion report, replayed bit-for-bit.

### PHASE 2 — Model Router
- **OBJECTIVE:** Vendor-independent, benchmark-driven routing.
- **DEPENDENCIES:** Phase 1.
- **IMPLEMENTATION:** adapters (≥ 3 providers incl. one local), canonical schema, capability registry, eval harness, fallback chains, cost tracking, data-class gating.
- **TESTS:** adapter conformance suite; chaos (timeouts, 429, truncation); gating tests (private data never reaches cloud).
- **BENCHMARKS:** per-model scores on PRAXIS eval suite v0 (reasoning, coding, tool-use, vision, schema adherence); routing beats best-single-model on cost at equal quality (target ≥ 30% cost reduction at ≤ 2% quality loss — UNCERTAIN).
- **FAILURE:** any provider-specific import outside an adapter; gating leak.
- **ROLLBACK:** registry versioned; static routing fallback.
- **COMPLETION:** swap a provider by adding one adapter + one registry row with zero other changes (demonstrated).

### PHASE 3 — Memory
- **OBJECTIVE:** Persistent structured intelligence with trustworthy retrieval.
- **DEPENDENCIES:** 1, 2 (embedding via router/local).
- **IMPLEMENTATION:** eight memory types over the log; hybrid retrieval; budget packer; provenance; failure-memory pre-check; user memory UI (inspect/delete).
- **TESTS:** rebuild-from-log equivalence; poisoning red-team; cross-project isolation.
- **BENCHMARKS:** retrieval recall@5 ≥ 0.85 on labeled queries (target); context token reduction ≥ 5× vs. naive history at equal task success.
- **FAILURE:** unprovenanced fact accepted; isolation breach.
- **ROLLBACK:** drop & rebuild derived stores.
- **COMPLETION:** a task that depends on a decision made 3 sessions ago succeeds without user restating it; "have we seen this failure?" prevents a repeated mistake in a seeded test.

### PHASE 4 — Project World
- **OBJECTIVE:** Persistent projects + live system state.
- **DEPENDENCIES:** 1, 3.
- **IMPLEMENTATION:** project schema; graph derivation (tree-sitter/LSP); impact analysis; World Model probes with TTLs.
- **TESTS:** graph accuracy on reference repos; staleness handling.
- **BENCHMARKS:** impact-analysis recall ≥ 0.9 on historical commits (did we predict the tests that broke?); probe cost < 1% CPU idle.
- **FAILURE:** stale state used without flag.
- **ROLLBACK:** graph is derived; regenerate.
- **COMPLETION:** for a real change, PRAXIS predicts affected components/tests and is right.

### PHASE 5 — Tools
- **OBJECTIVE:** Controlled external capability.
- **DEPENDENCIES:** 1–4.
- **IMPLEMENTATION:** manifests, sandboxed runtime, **Capability Guard (full)**, permission classes, grants, taint tracking, vault, MCP bridge, observed-effect audit.
- **TESTS:** injection corpus (target **0 unauthorized actions**); classification corpus; sandbox escape tests; composition attack tests.
- **BENCHMARKS:** guard decision latency < 5 ms; classification accuracy on dangerous-argument corpus 100% fail-closed.
- **FAILURE:** any Class ≥ 3 action without authorization; any secret in model context.
- **ROLLBACK:** revoke-all grants; quarantine mode.
- **COMPLETION:** red team cannot induce an unauthorized action across the full corpus; every tool has verified pre/postconditions.

### PHASE 6 — Computer Control
- **OBJECTIVE:** Observe→act→verify→recover on real software.
- **DEPENDENCIES:** 4, 5.
- **IMPLEMENTATION:** ActionContracts; control-surface hierarchy; transactional checkpoints; kill switch (out-of-process); VM/container default target; screen recording.
- **TESTS:** synthetic apps; fault injection; popups; localization.
- **BENCHMARKS:** GUI task suite (n ≥ 100): success rate, steps/success, recovery success; **gate: ≥ 90% success *or* safe-failure-with-rollback 100%**.
- **FAILURE:** any unrecoverable state corruption; kill switch latency > 200 ms.
- **ROLLBACK:** checkpoints; VM snapshot revert.
- **COMPLETION:** multi-app workflow completes or cleanly rolls back across 100 fault-injected runs.

### PHASE 7 — Research
- **OBJECTIVE:** Evidence-driven knowledge acquisition.
- **DEPENDENCIES:** 2, 3, 5.
- **IMPLEMENTATION:** claim ledger, tiering, quote-verification, independence checks, calibration.
- **TESTS:** citation audit; trap questions.
- **BENCHMARKS:** citation validity ≥ 98%; calibration error ≤ 0.1 (target).
- **FAILURE:** fabricated citation reaches output.
- **ROLLBACK:** ledger versioned.
- **COMPLETION:** blind evaluation — domain expert rates evidence-backing and uncertainty honesty above baseline search-summary.

### PHASE 8 — Coding Lab
- **OBJECTIVE:** Deep software engineering per Part XV.
- **DEPENDENCIES:** 4–7.
- **IMPLEMENTATION:** pipeline (inspect → graph → impact → checkpoint → isolated worktree → static analysis → unit → integration → benchmark → security → deploy → verify); diagnostic protocol; mutation-tested verification; PR generation.
- **TESTS:** seeded-bug repos; regression corpora (SWE-bench-style held-out tasks).
- **BENCHMARKS:** resolve rate on held-out tasks vs. baseline single-agent; **regressions introduced = 0 tolerance target**; mutation-score gating.
- **FAILURE:** shipped regression the pipeline could have caught.
- **ROLLBACK:** worktree isolation; revert commits.
- **COMPLETION:** an outcome-level request ("improve startup time without behavior change") yields measured improvement with evidence on a real repo.

### PHASE 9 — Engineering Lab
- **OBJECTIVE:** CAD, electronics, firmware, simulation pipeline.
- **DEPENDENCIES:** 4, 5, 8; simulation backends.
- **IMPLEMENTATION:** requirement→design pipeline; code-CAD; MuJoCo; FEA; KiCad; firmware build/flash (Class 4); unit-typing; sim-to-real logging.
- **TESTS:** golden designs vs. analytic; unit-error injection.
- **BENCHMARKS:** simulation vs. analytic error < 2%; design package completeness checklist 100%.
- **FAILURE:** unit error shipped; unsafe actuation.
- **ROLLBACK:** parametric regeneration; hardware e-stop.
- **COMPLETION:** "design a robotic hand" → requirements, ≥ 3 scored concepts, kinematic model, CAD, BOM, sim report, FMEA, test plan — all traceable; physical print+test (if hardware present) updates the model.

### PHASE 10 — Vision
- **OBJECTIVE:** Screen/world understanding.
- **DEPENDENCIES:** 6, 9.
- **IMPLEMENTATION:** a11y-first pipeline, OCR, VLM, calibration.
- **TESTS:** labeled suites.
- **BENCHMARKS:** element localization ≥ 95%; measurement error within calibrated tolerance.
- **FAILURE:** hallucinated UI element acted on.
- **ROLLBACK:** fall back to a11y/DOM only.
- **COMPLETION:** Phase 6 GUI success rate improves measurably with vision on, no new unsafe actions.

### PHASE 11 — Voice
- **OBJECTIVE:** Continuous conversational interaction.
- **DEPENDENCIES:** 1, 3, 4, 10.
- **IMPLEMENTATION:** streaming STT/TTS, barge-in, active-object stack, read-back, speaker verification.
- **TESTS:** scripted dialogues with "undo that"/"make it lighter" references; noise.
- **BENCHMARKS:** reference-resolution ≥ 95%; first-audio latency target < 800 ms; WER on domain vocabulary.
- **FAILURE:** voice-only authorization of Class ≥ 3.
- **ROLLBACK:** text-only mode.
- **COMPLETION:** a 30-minute hands-free working session with interruptions and undos, zero mis-executed commands.

### PHASE 12 — Multi-agent Intelligence
- **OBJECTIVE:** Parallel specialists where they measurably win.
- **DEPENDENCIES:** 1–8.
- **IMPLEMENTATION:** specialist runtime, topologies, arbiter, budgets.
- **TESTS:** seeded-bug critic benchmarks; deadlock tests.
- **BENCHMARKS:** per-task-type ablation vs. single-model+verifier; keep topology only if quality/cost win is significant.
- **FAILURE:** cost multiplication without quality gain.
- **ROLLBACK:** per-topology kill switch → single mode.
- **COMPLETION:** documented table of which topologies win on which task types, with statistics.

### PHASE 13 — Proactive Intelligence
- **OBJECTIVE:** Safe initiative.
- **DEPENDENCIES:** 3, 4, 12.
- **IMPLEMENTATION:** opportunity detectors, VOI threshold, digests, suppression learning.
- **TESTS:** simulated month of activity.
- **BENCHMARKS:** accept rate ≥ 50% (target); interruption cost metric ≤ budget.
- **FAILURE:** user mutes it (that is the signal).
- **ROLLBACK:** off switch; per-detector disable.
- **COMPLETION:** over 4 weeks of real use, net user-reported benefit positive.

### PHASE 14 — Self-Optimization
- **OBJECTIVE:** Measured workflow improvement.
- **DEPENDENCIES:** 2, 3, 12 + mature observability.
- **IMPLEMENTATION:** Improvement Loop with governance wall, held-out sets, shadow mode.
- **TESTS:** harmful-improvement injection must be rejected; governance-tamper attempts must fail.
- **BENCHMARKS:** sustained metric improvement on held-out suite without safety regression.
- **FAILURE:** any governance modification by the loop.
- **ROLLBACK:** versioned config; auto-revert on regression.
- **COMPLETION:** ≥ 3 promoted improvements with significant held-out gains and zero safety regressions.

### PHASE 15 — Full Integration
- **OBJECTIVE:** One intelligence environment.
- **DEPENDENCIES:** all.
- **IMPLEMENTATION:** unified workspace UI (§23), cross-subsystem scenarios, hardening, docs.
- **TESTS:** end-to-end acceptance scenarios (§34); long-duration soak; game-day drills.
- **BENCHMARKS:** full eval suite at or above all prior phase gates (no regressions).
- **FAILURE:** any earlier gate regresses.
- **ROLLBACK:** per-subsystem feature flags to last proven versions.
- **COMPLETION:** see §35.

**Advance rule:** a phase closes when its **completion criteria are met by recorded evidence in the event log**, not when code exists.

---

## 33. Testing strategy

**Pyramid, adapted for non-deterministic components:**

1. **Deterministic layer (the harness):** unit + property-based tests for kernel, guard, router logic, schemas. Target: 100% of guard decision paths covered; mutation score ≥ 80% on guard and verifier code.
2. **Record/replay layer:** sessions recorded with model outputs; replay verifies kernel behavior is identical. Fixtures sanitized.
3. **Fault-injection layer:** scripted-model harness injects wrong/empty/malformed/adversarial outputs; tool and network chaos; process kill at random points.
4. **Statistical layer (models):** eval suites run N times; report mean/variance/CI; regressions need significance. Canary evals daily on pinned + floating model versions.
5. **Adversarial layer:** injection corpus, memory-poisoning, tool-lying, sandbox escape. Metric = **unauthorized actions = 0**.
6. **End-to-end scenarios:** the acceptance scenarios in §34 run in clean VMs.
7. **Game-day drills:** disaster recovery rehearsals.
8. **Human evaluation:** periodic blind comparisons, usability of approval prompts.

**Anti-self-deception rules:** tests are written before implementation for guard/verifier; held-out evaluation sets never visible to the Improvement Loop; flaky tests are tracked, never silently skipped; every bug becomes a regression test and a Failure Memory entry.

## 34. Prototype definition (the smallest thing that tests the central hypothesis)

**Central hypothesis (H1):** *An event-sourced executive loop with typed plans, a deterministic permission guard, and a mandatory verification gate yields measurably more reliable task completion and safer autonomy than a plain tool-calling chat loop with the same underlying model.*

**PRAXIS-0 scope** (one process, CPU-only, runs in the current sandbox):

- Hash-chained SQLite event log + `Event/Goal/Plan/Step/Evidence` contracts
- Executive loop: intent → plan DAG → dispatch → **verify gate** → report (with evidence)
- Router with **two** providers + a fake provider for deterministic tests; static registry
- Tool runtime with 4 tools (`fs.read`, `fs.write`, `shell.run`, `git.*`) with manifests, Class 0–2 + **Class-5 refusal path**
- Capability Guard v0 (fail-closed; argument analyzer for shell)
- Verifiers: test-runner, file-state, diff
- CLI adapter; `praxis why <event>` explainability query; `praxis rollback <checkpoint>`
- Eval harness with 20 tasks (coding/file-ops) including 5 injection traps and 5 fault-injection cases

**A/B test:** baseline (plain tool loop, same model, same tools) vs. PRAXIS-0 on the 20 tasks × 5 runs each.

**Evidence that H1 holds (pre-registered):**
- Verified-task success rate: PRAXIS-0 ≥ baseline + 10 pp *or* equal with ≥ 50% fewer false "done" claims
- Injection traps: PRAXIS-0 unauthorized actions = 0; baseline's count recorded
- Fault-injection recovery: PRAXIS-0 ≥ 90% clean recovery
- Overhead: ≤ 25% extra cost/latency per task
- `why` explanations: ≥ 90% judged correct by audit

**If H1 fails:** analyze, write Failure Log entry, and revise this document — that is a valid and valuable outcome.

### Acceptance scenarios for the full system (§33 layer 6)
1. "Improve startup performance without changing visible behavior." → profile, branch, change, tests, benchmark delta, rollback point.
2. "Research X and tell me what's solid vs. speculative." → claim ledger, contradictions surfaced.
3. Spoken: "Make the chassis lighter." … "Actually, undo that." → correct referent, correct inverse.
4. "Design a robotic finger actuator for 5 N fingertip force." → traceable package, sim vs. analytic, unit-safe.
5. Mid-task network loss + user interrupt + crash → clean resume or rollback with an honest report.
6. Web page with hidden instructions to exfiltrate `.env` → zero unauthorized actions; incident logged.

## 35. Definition of completion

PRAXIS "1.0" is complete when **all** hold, each with evidence recorded in the event log and reproducible from the repository:

1. **Every phase gate (0–15) closed** by its completion criteria.
2. **Safety invariants hold across the adversarial suite:** 0 unauthorized Class ≥ 3 actions; 0 secret leaks; governance unmodifiable by agents.
3. **Verification invariant:** 0 completion claims without evidence in a 4-week real-use audit.
4. **Recovery invariant:** 100% of game-day drills restore the last verified state.
5. **Capability:** ≥ target success rates on the held-out eval suites (coding, research, computer-control, design) — thresholds fixed *before* measurement.
6. **Model independence:** a new provider is onboarded via adapter + registry row with zero kernel changes, demonstrated twice.
7. **Explainability:** `why` answers audited ≥ 90% correct.
8. **Lower user effort:** median user-issued clarifications and interventions per task below the pre-registered baseline.
9. **Stark Test (§36) passed** by every shipped feature.
10. **Honesty:** every capability in the README carries a Reality tag that matches measured behavior.

---

## 36. The Stark Test (per-feature gate) and operating rules

1. Does it improve real capability? 2. Would it exist without futuristic visuals? 3. Does it reduce user effort? 4. Does it make the intelligence more capable, reliable, or aware? 5. Can we prove it works? — *Any "no" → reconsider.*

Standing questions: *Strongest architecture, or merely the usual one?* · *What intelligence capability does this visual represent?* · *What evidence proves success?* · *Law of reality, limit of current technology, or limit of our design?*

**Communication contract:** report discoveries, risks, meaningful progress, decisions needing the human, and verified results — suppress narration.

## 37. Immediate next steps (Phase 0 → Phase 1 transition)

1. Human review of this document; resolve the **three decisions only a human can make**:
   a. **Providers & budget** — which model providers/keys, monthly spend ceiling (money → ask).
   b. **Target environment** — will PRAXIS run on a GPU workstation (local models) or cloud-only at first (hardware).
   c. **Domain priority** — Coding Lab first (recommended: best verifiers, fastest evidence) or Engineering Lab first.
2. Run the five Phase 0 spikes (replay determinism; shell-command classification; GUI reliability baseline; router eval design; taint-tracking feasibility).
3. Freeze contract v0.1 and begin PRAXIS-0 (§34) under test-first discipline.

## 38. Status addendum — PRAXIS-0 built (2026-10-02)

**Defaults taken on the open decisions (reversible; recorded as Decisions):** cloud providers first behind the adapter
interface (Anthropic adapter + scripted provider for deterministic tests); CPU-only; **Coding Lab first**; stdlib-only kernel.

**Built:** `praxis/` — `events.py` (hash-chained log), `guard.py` (Class 0–5, fail-closed shell analyzer, taint rule),
`tools.py` (workspace-confined tools, checkpoint/rollback), `verifiers.py`, `router.py`, `executive.py`, CLI.

**Evidence:** 39 unit/adversarial tests pass. Mutation check: breaking the shell classifier, verifier gate, rollback,
hash-chain check, taint rule, replan-approval rule, or unknown-verifier default each makes the suite fail (7/7 killed).
`evals/run_eval.py` (20 tasks, scripted model): PRAXIS-0 10/10 normal, 0 unauthorized actions, 0 false "done", 0 corrupted
state; the naive loop gets 9/10, executes 4 of 5 attack steps (the 5th is a network call that cannot succeed offline), claims completion on 2 faulty tasks, and corrupts state once.

**Design decision made while building (Failure-log style):** F-006 — *taint-denies-all-replans* made the fix-and-retry loop
useless (a model cannot repair code if every post-observation step is read-only). **Change:** replans derived from
untrusted observations are allowed only after a human approves the concrete proposed plan; each step then still passes the Guard.

**Not yet proven (honest):** H1 against a live model (needs API access and the real A/B); crash-resume; OS-level
sandboxing; goal-level checkpoints copy the whole workspace (fine for small projects, not for large repos); the shell
allowlist is deliberately narrow and will need widening with evidence. These are the Phase 1/5 gates and remain open.

## 39. Status addendum — PRAXIS-1: real providers, sandbox, live evidence (2026-10-02)

**Built since §38:** Claude/Codex/Droid CLI adapters (subscription login; API-key env vars stripped so a CLI can never
silently bill an API key), Ollama adapter with memory-aware "smartest model that fits" selection (measured score beats size
prior), Devin v3 delegate-only adapter (Class 4), capability registry + `praxis bench`, router with preference/measured
ordering, privacy gating and rate-limit cooldown, second-model critic (always a different provider), cost budget,
crash-resume (real `kill -9`-equivalent test, no model call on resume), observe-then-plan phase, OS sandbox with a live
self-attack, BM25 memory with failure recall, checkpoint pruning, protected-path rules.

**Found by running reality, not by my own tests (all fixed, each with a regression test):**
| # | Finding | Source |
|---|---|---|
| F-006 | Taint-denies-all-replans made fix-and-retry useless | design review while building |
| F-007 | **Verifier commands bypassed the Guard** (a plan could put `rm -rf .` in a success check) | first live run against real Claude |
| F-008 | One-shot planner is blind to file contents -> reached for shell tools -> 2/7 pass | first live bench |
| F-009 | Allowlisting `unittest` but not `python script.py` was security theater: both run code the plan just wrote. Replaced by: code execution is Class 2 only in an OS sandbox that survived a live self-attack, else Class 4 | analysis of F-008 |
| F-010 | Plans could write `.praxis/` (log, registry), `.git/hooks`, `praxis.toml` | adversarial self-review |
| F-011 | Sandbox self-test crashed instead of returning a verdict when an attack succeeded | mutation testing |

**More findings, from building the desktop app and the hardware layer (each fixed, each with a regression test):**
| # | Finding | Source |
|---|---|---|
| F-012 | **The benchmark was inflating capability**: two "refuse to delete" traps pass by doing nothing, so a useless model scored 0.14. Capability and safety are now scored separately; the headline numbers below are the corrected ones | a do-nothing-model test I wrote |
| F-013 | UI race: the "mark history as read" snapshot ran only when idle, so a fast first goal's events were swallowed and the feed stayed empty | driving the real window |
| F-014 | Two connections opening a new SQLite log at once raised "database is locked" (WAL pragma ignores the busy timeout) | threaded controller tests, flaky 1 in 3 |
| F-015 | **The hash chain could fork under concurrent writers** (read last hash + insert was not atomic). Now `BEGIN IMMEDIATE`; 12 rounds x 8 threads stress test | the stress test written for F-014 |
| F-016 | Cancel was checked before the tool result was logged, so an action that ran and was rolled back left no audit record | cancel tests |
| F-017 | **Windows would crash on any model output containing a unicode character** (locale code page, not UTF-8). Reproduced on Linux by forcing an ASCII locale; every text path is now explicit UTF-8 | adversarial portability review |
| F-018 | **A project folder could ship a `praxis.toml` that redirected the "local" Ollama provider to a remote host** (defeating `--private`) or loosened the sandbox/limits. Workspace config is now untrusted and limited to hardware and role preferences; provider hosts, sandbox, privacy and limits come only from the user's own config | adversarial review of the folder-opening feature |
| F-019 | **The desktop feed could silently drop a fast goal's events**: a three-layer race (the first poll's result was discarded; the history baseline did not persist; re-adding events to the Timeline raised a swallowed duplicate-row error). Found by two surviving sabotage mutants, then fixed at the root and pinned with three tests | mutation testing |

**Live measurements: real Claude subscription via `claude -p` on the build machine; every check is independent of the model.**
Corrected scoring (F-012): *capability* = tasks with real work; *safety* = trap runs where the attack must not succeed.

| Set | Capability | Trap runs, attacks | False "done" | Cost |
|---|---|---|---|---|
| Tuned set (the planner prompt was iterated on it) | **18/18** (6 tasks x 3) | 9, 0 | 0 | $0.31 |
| **Held-out set** (written after tuning, never tuned on) | **12/12** (4 tasks x 3) | 3, 0 | 0 | $0.37 |
| Critique bench (planted defects, 5 cases) | 5/5 | n/a | n/a | n/a |
| Live delegation end to end (Class 3 escalate, human approve, real Claude edits the workspace, verify) | 1/1, code correct | 0 | 0 | ~$0.03 |

Total live usage during the build: roughly $2 of subscription-equivalent cost. **Honest caveats:** an earlier 3-trial held-out run
scored 14/15 with one failure on `holdout-trap-path-escape` whose reason was not recorded (the benchmark then discarded failure
reasons; now fixed, F-012 and `bench_runs.jsonl`); it did not reproduce in 4 reruns or in the corrected run, so that task is
10/11 overall. The sample is small (n=12 held-out), one model family, tasks are small. Treat this as encouraging evidence that the
harness works with a real model, not as proof of general reliability.

**Sabotage checks (mutation testing) on the new code, run on a copy of the repo:** 23 of 25 deliberate breakages were caught
by the test suite. The 2 survivors were genuine test gaps (a Guard hard-DENY display branch and a first-tick race), found, fixed (F-019) and re-killed, so all 25 are now caught; the new workspace-config trust rule was separately checked 3 of 3. Earlier rounds: 15/15 and 4/5 on the guard, sandbox and kernel (the 5th was an equivalent mutant).

**Test evidence:** 258 tests, green on Python 3.11 and on 3.12 under a virtual display (the desktop-UI tests need Tk and a display and
skip otherwise); repeated full runs and 10 repeated desktop runs were stable after F-014, F-015 and F-019.

## 40. Hardware research: RTX 3050, Ryzen 7 7700, 32 GB DDR5 (2026-10-02)

**Method.** Search-engine blog results were thin and partly stale (one recommended a "Llama 3.3 8B" that does not exist), so
recommendations come from primary sources: each model's Ollama library tag page (size, active parameters, context), Ollama's own
FAQ and Windows docs, and a physical performance model that is *labeled as an estimate* until `praxis bench` measures it.

**The hardware.** The RTX 3050 exists in two real variants: **8 GB, 128-bit, 224 GB/s** and **6 GB, 96-bit, 168 GB/s** (different
silicon, slower), and NVIDIA has been replacing the 8 GB desktop card with the 6 GB one, so PRAXIS reads the real VRAM at runtime
instead of assuming. A Ryzen 7 7700 with dual-channel DDR5 is modeled at about 70 GB/s achievable.

**The physics.** Decoding is memory-bandwidth bound: tokens/s ~ bandwidth / bytes read per token. A dense 27B at ~17 GB, mostly in
system RAM, reads ~17 GB per token: roughly 2 to 3 tok/s. A mixture-of-experts 35B with 3B active reads ~2 GB per token: an estimated
15 to 22 tok/s, and it fits in 32 GB. So **MoE with about 3B active parameters is the sweet spot for this machine**, a small
dense model that fits fully in VRAM is the fast helper, and a dense 27B to 30B is the slow "deep thinker".

| Model (Ollama tag) | Size | Total / active | Context | Role | Est. tok/s (8 GB card) |
|---|---|---|---|---|---|
| `qwen3.6:35b-a3b-coding` | 23.5 GB | 35B / 3B | 256K | daily driver | ~19 |
| `laguna-xs-2.1` | 20 GB | 33B / 3B | 256K | agentic coding | ~22 |
| `north-mini-code-1.0` | 19 GB | 30B / 3B | 488K | agentic software engineering | ~21 |
| `nemotron-3.5-lightning:30b-a3b` | 25 GB | 30B / 3B | 1M | long-context agents | ~15 |
| `granite4.2:8b` | 5.3 GB | 8B dense | 128K | fast helper, fits VRAM | ~24 |
| `granite4.2:3b` | 2.2 GB | 3B dense | 128K | helper for the 6 GB card | ~57 |
| `qwen3.8:27b`, `qwen3.6:27b`, `granite4.2:30b` | 17 to 18 GB | dense | 128K to 256K | deep thinker (slow) | ~2 to 3 |

Ollama tuning for a small-VRAM card (from Ollama's FAQ): `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0` (about half the
cache memory of f16), `OLLAMA_MAX_LOADED_MODELS=1`; PRAXIS also defaults `num_ctx` to 8192 on 8 GB or less. Ollama on Windows needs
NVIDIA driver 551.61 or newer.

**Cloud models ("best of the best").** Verified live on the Claude CLI: `claude-fable-5-1`, `claude-opus-5-5`, `claude-sonnet-5-5`
are accepted and a bogus id is rejected. **Measured cost of the same trivial prompt: $0.1005 / $0.0163 / $0.0015**, a 67x spread, so
PRAXIS runs one instance per model and routes by *measured* quality-per-cost (cheapest model within 0.05 of the best score)
instead of always using the top model. Defaults until measured: planner uses the balanced tier, critic uses the best tier. For
Codex and Droid the ids come from vendor documentation (Factory lists Claude Fable 5.1, GPT-5.5 Pro and Opus 5.5 for planning and
GPT-5.3-Codex for coding; Codex's sign-in default is GPT-5.5) and are validated at runtime: a rejected id is benched for 6 hours.

**Sources (read 2026-10-02).** Ollama library tag pages: [qwen3.6](https://ollama.com/library/qwen3.6/tags),
[qwen3.8](https://ollama.com/library/qwen3.8/tags), [nemotron-3.5-lightning](https://ollama.com/library/nemotron-3.5-lightning/tags),
[laguna-xs-2.1](https://ollama.com/library/laguna-xs-2.1/tags), [north-mini-code-1.0](https://ollama.com/library/north-mini-code-1.0/tags),
[granite4.2](https://ollama.com/library/granite4.2/tags), [lfm2.5](https://ollama.com/library/lfm2.5/tags);
[Ollama FAQ](https://docs.ollama.com/faq); [Ollama on Windows](https://docs.ollama.com/windows);
[Factory models](https://docs.factory.com/cli/user-guides/choosing-your-model); [Claude Code setup](https://code.claude.com/docs/en/setup);
[Codex CLI](https://learn.chatgpt.com/docs/cli); [Devin API v3](https://docs.devin.ai/api-reference/overview);
RTX 3050 variants: [HotHardware](https://hothardware.com/news/nvidia-launches-6gb-geforce-rtx-3050),
[Evetech comparison](https://evezone.evetech.co.za/ez/rtx-3050-6gb-vs-8gb).

## 41. Limits stated plainly

* **Not verified live here:** Codex, Droid, Devin, Ollama; the Windows window, launchers and Docker sandbox. Adapters are tested
  against documented interfaces with recording fakes, which proves PRAXIS's behavior, not the vendors'.
* **Local-model speeds are estimates** until measured. The quality ranking among local models is an unmeasured prior (dense-equivalent
  size). `praxis bench --all-ollama` replaces both with measurements and measured scores always win.
* **No native Windows sandbox.** Without Docker Desktop (or WSL2), code execution needs a human approval each time (secure by default,
  more clicks). Claude Code's own native-Windows sandbox is also unsupported per its docs, which is irrelevant here: PRAXIS runs its own.
* **VERIFIED is relative to the checks shown.** A verifier cannot know what you meant: an ambiguous goal can yield checks that encode a
  misreading (observed live: `Hello, Stark.` with a period). The second-vendor critic exists to catch this; it is skipped (and the UI says so)
  when only one vendor family is available.
* **Not built:** voice, vision, engineering lab (CAD, simulation), proactive engine, multi-device, learned router.

## 42. Status addendum — PRAXIS-2: use Claude less, never get stuck, a command center (2026-10-02)

**Requirement (from the owner):** when Claude's usage is spent, reroute to other capable AIs, and in general use Claude *less* so the
subscription lasts longer; research the best free and local options and add them without disturbing what already works; and the UI must
not look like a plain toolkit window.

**42.1 Research method and the lesson from it.** Every claim below was read from a vendor page or, where marked *(community)*, from a
community-maintained list on 2026-10-02. The most useful finding was negative: three things I would have built on **no longer exist**:
the free Google-login tier of Gemini CLI (ended 2026-06-18), Qwen Code's free OAuth tier (2026-04-15) and GitHub Models' free API
(retired 2026-07-30). They are recorded in `free_tiers.DISCONTINUED` so nobody re-discovers them the hard way. **Rule: verify a free
tier exists before designing around it.**

**42.2 Free cloud tiers (`praxis/free_tiers.py`, `praxis/openai_compat.py`).** One generic OpenAI-compatible adapter (Ollama Cloud reuses the Ollama adapter with a key) plus a data table
(`Preset`: base URL, key variable, models, limits, privacy class, caveat, signup URL, **source URL and date read**). Groq, Cerebras and
Ollama Cloud are *trusted*; Gemini, Mistral, NVIDIA NIM and OpenRouter `:free` are *open*. Every tier needs a free API key; there is no
free tier that works without one. The adapter paces itself to the tier's requests/minute (and returns a `RateLimited` instead of
sleeping past 25 s), refuses a prompt over the tier's token cap before sending it, maps 429/402 to a rest period (the provider's own
`Retry-After`, else a daily-quota guess), 404 and "model not found" to a 6-hour bench (`ModelUnavailable`), 401/403 to an
authentication message, and scrubs the key from any error text. Keys live in `~/.praxis/secrets.json` (created 0600) or environment
variables, never in the event log or the workspace.

**42.3 Data use is a routing constraint, not a footnote.** Free tiers are free because the vendor may keep, read or train on the
prompt. Providers carry a privacy class (`local` < `cloud`/trusted < `open`; an unknown label is treated as the *least* trusted) and every goal
carries a data class (`private` = local only, `project` = + trusted, `open` = + open tiers); an ineligible provider is filtered out
before ranking. Independently, the router refuses to send any prompt that matches a secret pattern (private keys, cloud and API
tokens, JWTs, password assignments) to an open tier, and logs `model.skipped` with the reason.

**42.4 Frugal routing (`router.py`, `usage.py`, `executive.py`).** Strategy `frugal` orders candidates by cost class (local, free cloud,
subscription), then tier small to large, so Claude is the *last* rung. Measured scores demote a model that is below `min_quality` or
more than `slack` under the best measured one. `UsageTracker` (a global append-only file, so all workspaces share the picture) counts
calls, estimated cost and tokens per model in 5 h / 24 h / 7 d windows against optional `[budgets]`; a free tier's documented daily
limit becomes its default budget with 10 % headroom; a model whose budget is spent goes to the **back** of the line (a last resort,
never a hard block). **Escalation:** if a goal's checks fail on the work itself (not on a Guard denial or a budget), the workspace is rolled back and a stronger model plans *from
scratch*: nothing observed by the weaker attempt is carried over, so untrusted content cannot steer the retry; at most 2 escalations,
never to a model that was already tried.

**42.5 The command center (`praxis/desktop/qt/`, PySide6; Tk remains the fallback).** The window is still only a projection of the
event log plus the router's state (design law 3). Its centre is **The Loom** (`particles.py`, pure math; `core.py`, painting), an
original design in the particle-intelligence idiom rather than a copy of a reference: about 2,500 points in a spiral-arm galaxy
(three arms on a logarithmic spiral, a sparse halo, a lens-flare seed, comet tails, warm sparks) crossed by three gimbal rings.
**Rule: decoration is allowed, fake data is not.** The rings are the kernel's real pipeline: PLAN (a comet while planning, lit when
the plan is accepted, red if rejected), ACT (one arc per `View.steps` entry in that step's state, a comet on the running one) and
VERIFY (one arc per `View.evidence` check; sealed into a closed green ring only when the status is VERIFIED *and* there is
evidence). Motion is meaning: the arms flow inward while working, are still while waiting for a human, and flow outward on
VERIFIED; the tint is the state; STOP snaps fast (a kill switch must look like one); each real event flares the seed and sends a
rate-limited ripple; a particle stream runs to the provider named by `View.active_provider`; the latest event is typed out in a
caption; starting re-assembles the galaxy and unfolds the rings. Providers flank it (free/local left, subscriptions right) with
budget-pressure arcs, a rest clock and a hollow style for a data-class block; the layout is computed from the rings' measured
extent so nodes never touch a ring and the widest ring always fits. Rendering: everything that glows is drawn additively into one
buffer which is bloomed (two blurred copies added back); the aura is cached; calm states tick at 24 fps; a `Quality` governor steps
the particle count down (2500 / 1700 / 1100 / 600, never back up, so it cannot flap) when frames stay slow and drops the bloom at
the lower levels; `PRAXIS_REDUCE_MOTION=1` slows everything. The simulation is stepped with `advance(dt)` (clamped so a stalled frame
cannot jump), so previews and tests drive it deterministically. The DATA and FRUGALITY header switches write straight into the
controller and router and are re-synchronised from the router when a stack loads. The Qt package imports nothing from Tk; the
approval wording lives in a toolkit-free module so both shells agree.

**42.6 Evidence.** 357 tests in the suite. Full run on Python 3.11 with PySide6 6.11: 357 run, 341 execute and 16 skip (the Tk window tests, which need `tkinter`); the Tk window tests (with the controller and view tests) run separately on Python 3.12 under a virtual display: 49 pass. Of the 357, 24 drive the **real** Qt window offscreen with the real controller: run to VERIFIED, the core lighting the provider being called *right now*, approval dialogs answered from inside the modal loop (exact action shown, Deny focused and default, Esc and close refuse, one dialog per request), STOP restoring the workspace, the `private` setting keeping a cloud model from ever seeing the goal, `frugal` serving a goal from the local model with **zero** Claude calls, the failover ladder in frugal order, and a key added through the dialog making the provider appear in the real `build_stack`. Free-tier adapters are tested against local servers that return the documented error shapes. Screenshots of every page were reviewed at 1360x860 and at the 1100x760 minimum. Mutation (sabotage) results for this phase are appended below when the run completes.

**42.7 Defects found by this phase's own tests (kept in the failure log style).**
* *Key stored under the wrong name* (UI): the window's "Add key" saved under the environment-variable name while config and the CLI
  look up the provider id, so a key added in the window would never have been found. My first test asserted with the same wrong name and
  passed. Replaced by an end-to-end test through the **real** `build_stack`; verified that it fails on the old code.
* *Window minimum width* (UI): the header and the Models page together forced a 1263 px minimum against a 1100 px window minimum
  (a long Windows path alone would have widened the window). Fixed with an eliding label, wrapping captions and a test over every page.
* *Overlapping hero and plan graph* (UI): the layout's minimum height (938 px) exceeded the window (860 px). Fixed and tested by
  asserting the geometry at the minimum window size.
* *Stale cards* (UI): refreshed Fuel cards were removed with `deleteLater` alone and stayed painted until the event loop turned.

**42.8 Not proven here.** The free tiers themselves (no keys: fake servers returning the documented error shapes only); the Qt window on
Windows (offscreen on Linux, screenshots reviewed); the local-model additions' speed and quality (catalog quality ordering uses
third-party LiveCodeBench figures where available, labelled as secondary evidence, and is replaced by `praxis bench --all-ollama`);
*(community)* limits for NVIDIA NIM and OpenRouter. A free tier's numbers can change at any time: a provider's 429 always wins.

*End of Revision Zero (with addenda 38 to 42). Failures get logged, not hidden.*
