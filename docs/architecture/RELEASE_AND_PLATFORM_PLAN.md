# Release and Platform Plan (M0, design only)

## 1. Binding stage order

R0 real model → R1 local browser app → R2 automated browser/model/backend qualification → R3 Windows + macOS packages → R4 per-platform installed-app qualification → R5 website with only qualified, signed packages → (optional) R6 commercial. A stage's evidence gates the next (REL-001). No fake controls, no macOS claim from Windows tests, no download site before R4.

## 2. Six final systems — boundaries

| System | Boundary / key design | First concrete artifact | Gate |
|---|---|---|---|
| **DEP** Deployment | Device profiler → measured compatibility table (supported/experimental/unsupported per checkpoint) → local inference by default; model-serving contract shared by browser and desktop. Hosted option is future, explicit opt-in, first-party models only | capability probe in M5; table filled from real benchmarks | DEP-G1 |
| **SEC** Security | Auth/session, DPAPI/Keychain secrets, loopback+origin controls, admin broker split, tool-gate injection filtering, SBOM, signing-key custody | threat model + SBOM tooling in M1 | SEC-G1 (+ human review) |
| **UPD** Updates/recovery | Separate versions (app, bridge, API schema, tokenizer, weights, DB, train code); signed manifest (hash, size, channel, platform, min versions); stage → verify → atomic swap → health check → commit; pre-migration backup; restore drills | manifest schema + backup/restore in M5–M6 | UPD-G1 per OS |
| **BENCH** Lab | Versioned catalog, sealed hash-protected sets, pre-declared trials/margins, scorecards labelling experimental vs verified | catalog + frozen baseline at M2–M4 | BENCH-G1 |
| **XP** Cross-platform | Shared browser product; platform-neutral action contract; separate Windows (C#) and macOS (Swift) adapters; capability discovery hides unsupported controls | contract in M1 | XP-G1 |
| **REPRO** Rights/rebuild | Ownership ledger, dataset provenance, run manifests, locked deps, chain-of-custody hashes, clean-room rebuild drill | `rights/SOURCE_RIGHTS_REGISTER.md` (M0 format), manifests M2+ | REPRO-G1 |

## 3. macOS prerequisites (what must exist; none verified)

- A real, supported Mac for build, test and notarisation (Apple Silicon recommended; Intel Macs vs ARM64 matrix decided in XP-008). **No Mac is known to be available** — D2.
- Apple Developer Program membership (paid, annual) for Developer ID signing and notarisation; Xcode toolchain; notarytool workflow. Current fees/requirements must be re-checked on Apple's site at planning time (not verified in M0).
- Handling of TCC prompts (Accessibility, Screen Recording, Automation) is part of the test plan; they cannot be bypassed and tests must run in a way that grants them legitimately.
- Metal/MPS inference evaluated separately from CUDA; weights/serialization compatibility tested, not assumed (XP-005).
- Without the above, macOS stays "specified, unsupported" and cannot be listed on the site.

## 4. Windows prerequisites

Code-signing certificate and key custody plan (D16); clean VM or spare machine for install tests (Hyper-V needs Pro/Enterprise — to verify); SmartScreen reputation realities noted for first releases; installer technology (MSIX vs MSI vs others) picked with the desktop-shell ADR.

## 5. Browser qualification (R2) entry criteria

Real Core checkpoint + backend + UI; every enabled control has an implemented action; Playwright suites for TB-009/010, security TB-014, recovery TB-018, soak profiles run per the pre-declared thresholds; zero release-blockers; owner approval. REL-004: UI click tests never stand in for model competence tests.

## 6. Official site and download integrity (R5; design)

- Site serves only artifacts listed in a signed **release manifest** (REL-006): version, channel, commit, SBOM, SHA-256, signatures, compatible model/tokenizer/schema versions, OS/arch, test report IDs, owner approval.
- Download links are generated from the manifest; CI test downloads each link, verifies hash, signature (Authenticode / Apple notarisation ticket) and HTTPS config; old/unknown artifacts blocked.
- Capability labels on the site derive from the verified-feature list (Verified / Experimental / Planned / Unsupported) — no hand-written marketing claims.
- Owner go/no-go with a residual-risk register (REL-010). Domain/brand checks first (D17).
- Update channels: dev / beta / stable; stable never auto-receives experimental checkpoints (UPD-007).

## 7. Explicit non-claims

No guarantee of bug-free software, hardware compatibility, frontier-level intelligence, or Claude/ChatGPT coding parity. Soak testing reduces but cannot eliminate unknown defects.
