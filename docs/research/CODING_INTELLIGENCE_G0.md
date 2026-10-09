# CODE-G0 — Coding Intelligence Research Note (M0)

Research/design only. No coding capability exists.

## 1. Two abilities, measured separately
(A) Model coding capability — can Zalius Core predict/produce correct code. (B) Agentic engineering — tools, repo map, plan/edit/test/verify loop. A tool loop cannot rescue an incapable model, and a capable model needs the loop (blueprint §8A.1).

## 2. Task families and language order
Order from CODE-003: Python → TypeScript/JavaScript/HTML/CSS → C#/.NET → SQL → PowerShell; others only after measured results. Families: spec-to-function, bug-to-patch, test writing, multi-file feature, refactor, log/stack-trace debugging, Git ops, build/fix loops.

## 3. Tokenizer requirements for code (feeds M2)
Tests for identifiers (camelCase/snake_case), significant whitespace/indent runs, brackets, Unicode in strings, long files, round-trip exactness. Whitespace-run handling is a design question: measure tokens-per-character on a code sample under candidate tokenizers before fixing vocab size.

## 4. Data
Permissively-licensed code only, licence verified per repo, deduplicated, secret/PII-scanned, with eval-set decontamination (hash + near-dup). Private repos and the owner's files are never auto-ingested (CODE roadmap step 2, REPRO-008). See `rights/SOURCE_RIGHTS_REGISTER.md`.

## 5. Realistic ceilings with current resources (reasoned estimate, unmeasured)
A ~15–40M-parameter model trained on one 4 GB GPU should be expected to learn syntax-level regularities and short idiomatic snippets at best. Multi-step repository engineering at Claude/ChatGPT level depends on scale (model size, data volume, post-training) far beyond that hardware class; the blueprint itself says parity may be unattainable on personal resources. **CODE-G1 is the only gate plausibly reachable early** (better than untrained/random and n-gram baselines on simple held-out code tasks). G4/G5 are research aspirations with no committed outcome.

## 6. Evaluation (see TESTBENCH_ARCHITECTURE §9)
Baselines for G1: untrained model, n-gram/char-level model, trained Zalius model; metrics: held-out code perplexity, syntax-validity rate (parses with real parser), small unit-test-checked function tasks (pass@1 with failures in denominator). Sealed set hashed before any training.

## 7. Agent pipeline contract (CODE-001..020 → services/coding-agent)
`goal → workspace permission → repo discovery → retrieval → plan → Core generation → scoped edits → build/test → diagnose/retry → independent verification → diff + report`, each stage with typed input/output/failure, verification against real filesystem/test state only, change journal for resume/revert.

## 8. Independence constraint
Claude Code assists *building* Zalius only. Zalius's shipped coding path calls no external LLM (OWN-012). The agent harness may initially be exercised with scripted/mock generators in tests; that is test scaffolding, labelled as such, never presented as Zalius intelligence.
