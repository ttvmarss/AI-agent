# Zalius AI — Claude Code M0 Kickoff (HOLD until owner approval)

Read `ZALIUS_AI_MASTER_ENGINEERING_BLUEPRINT_v1.3_RELEASE_ARCHITECTURE.md` in full. You are the implementation engineer; your model may build Zalius but must not serve as Zalius's runtime intelligence. Zalius Core must have its own independently trained weights. The owner will eventually transition development to Zalius's own agent, but only after objective tests prove that agent's abilities.

**Authorized work for the first session: M0 ONLY — research and environment audit.**

1. Inspect the local Windows environment and verify CPU, GPU, VRAM, RAM, Python, PyTorch CUDA capability, .NET, Node, Git, drive space. Never infer hardware from the blueprint alone.
2. Research original Transformer/GPT 2018, GPT-2, and the publicly documented 2022 ChatGPT supervised fine-tuning + RLHF workflow; cite official/public sources and distinguish history from Zalius's modern implementation.
3. Present full architecture boundaries: PyTorch Core/training, local inference service, chat/memory projects, C# Windows Bridge, scoped Admin Broker, UI, orchestration, Evolution Engine.
4. Create a requirement-to-milestone-to-test traceability matrix covering ALL specified systems and modes, including Section 8A coding intelligence, Section 10A testbench (TB-001..TB-027), Sections 10B–10G final systems (DEP/SEC/UPD/BENCH/XP/REPRO), and Section 10H release stages (REL-001..REL-012). Propose a rigorous same-tools Claude Code/ChatGPT coding comparison protocol, but **do not** claim parity or build the entire agent now. Identify open decisions and exact empirical methods to close them.
5. Design (do not yet run) the automated testbench architecture: choose current Windows-compatible frameworks, require unattended browser testing first and independently qualified Windows/macOS desktop testing afterwards, define 8h/24–48h/72h soak profiles, fault injection and evidence reports, and plan training/test lane coordination for the 4 GB GPU. Specify signed clean-install packaged-Windows and packaged-macOS tests on supported hardware, R2 browser qualification before desktop packaging and R4 independent platform gates before R5 website downloads. Propose the six final-system designs, rights ledger, optional disclosed local/first-party-hosted deployment (future), reproducibility, signing/updates, macOS hardware requirements and official website integrity plan. Establish a proposed repository layout and development journal plan; do not build a fake front end or train a large model at this stage.
6. Return M0 evidence, files created, verified facts vs assumptions, risks, and a proposed M1 acceptance test plan. STOP and request approval before M1.

**Non-negotiable:** never silently call Claude/Anthropic/OpenAI language models from the shipped Zalius runtime. If the 4GB GPU cannot support a proposed experiment, report the limitation and propose a smaller genuine training experiment. Never bypass Windows authorization or provider licensing.

**Testbench requirement: Claude must eventually build reproducible local automated tests for all implemented features, run long soak/crash/recovery suites, and coordinate independent candidate training with tests when machine resources allow; no false claim of constant GPU-parallel training on 4 GB VRAM. These are future milestones, not actions authorized in M0.

**Coding success criterion:** Zalius must ultimately be engineered toward real Claude/ChatGPT-class software engineering using its **own trained model and tools**. Passing a trivial coding example is NOT parity. Code G0-G5 gates in Section 8A are separate from model authenticity. This is a long-term goal, not a guaranteed outcome on a 4 GB GPU.


**Binding implementation order:** R0 real model → R1 functional local-browser app → R2 automatic browser/model/backend qualification → R3 independent Windows and macOS packages → R4 each installed-app test matrix → R5 official download website linking only tested signed packages → optional R6 commercialization. This is a staged specification; do not create fake browser controls, represent existing Windows tests as macOS proof, or publish a download site before packaged-app qualification.

**Release/security constraints:** Disclose any outsourced speech models; never disguise third-party language-model inference as Zalius Core. Owner/local default is offline and first-party. Document actual hardware limits, Mac build/test/signing prerequisites and unresolved decisions. No guarantee of absolute bug-freeness, parity with Claude, or all hardware compatibility.
