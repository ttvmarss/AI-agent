# Source Rights Register (format proposal — M0)

**No entry below has been reviewed. Nothing here asserts ownership or permission.** Candidate sources are listed only as leads for review; their licences, terms and commercial-use status are *unverified*. Rule (REPRO-002): unverified sources are rejected, not used.

## Record format (one row per asset; machine-readable twin `rights/ledger.csv` from M1)

| Field | Meaning |
|---|---|
| `asset_id` | stable id, e.g. `DS-0001`, `LIB-0007`, `WT-0001`, `FONT-0002` |
| `kind` | dataset / library / weights / tokenizer / font / asset / speech-model |
| `name`, `version`, `source_url`, `collected_on` | provenance |
| `authored_by` | zalius / external |
| `license_id` + `license_url` | SPDX id where possible |
| `use_basis` | training / redistribution / tooling-only |
| `commercial_ok` | yes / no / unknown (unknown = blocks release) |
| `attribution_required`, `share_alike` | obligations |
| `checksum_sha256`, `transforms` | integrity and processing lineage |
| `pii_secret_scan` | result reference |
| `review` | reviewer, date, status: `unreviewed` / `approved` / `rejected` / `revoked` |
| `removal_notes` | takedown/revocation handling; limits of unlearning (REPRO-007) |

## Zalius-authored code and weights
Initial status for all: `unreviewed` / not yet existing. Weights do not exist (OWN-001: random init, trained locally).

## Candidate leads for M2 review (UNVERIFIED — do not ingest)
| Lead | Why considered | Open question |
|---|---|---|
| Public-domain book text (e.g. Project Gutenberg) | clearly out-of-copyright works exist | per-work jurisdiction, Gutenberg trademark/terms for bulk use |
| Permissively-licensed code (MIT/Apache/BSD) from repos with explicit licences | code-token modelling (CODE roadmap) | per-repo licence verification, attribution, secret scanning, dedupe vs eval sets |
| Official language/API documentation under open licences | code-adjacent text | licence per doc set |
| Owner-authored text/dialogues | clean rights | owner confirms consent; exclude personal/secret data (REPRO-008) |
| Existing public datasets | availability | each dataset's licence **and** its upstream sources; many mix licences |

Third-party language-model checkpoints, and datasets of unclear provenance, are excluded outright.

## Speech components
Any STT/TTS model is a *separate, disclosed* component (OWN-001, VOICE) with its own row; it is never described as Zalius Core.
