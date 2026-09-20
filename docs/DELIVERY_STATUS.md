# Local delivery status

Updated for the GitHub publication on 2026-09-20. Scope: **runnable local research
development delivery**, independently reviewed and audited. No held-out release
certification, clinical suitability, public deployment, or new hosted CI result is
claimed by this record.

## Implemented

The configured application joins bounded PubMed/DailyMed/FAERS acquisition,
optional approved local CADEC search, exact materials/provenance, DeepSeek Flash
Generation V2, independent Qwen V4 semantic validation, PostgreSQL/LangGraph
checkpoints, human review and idempotent JSON/Markdown export. Qwen is fixed to
`qwen3.8-max-0902`; changing its identity is not an unvalidated settings swap.

Repeated identical content retains the blob's first-persisted time while each
acquisition keeps its own occurrence identity/time. The outcome occurrence key
includes run, source, acquisition and content outcome ID. A downgrade that would
collapse different occurrences refuses before DDL rather than deleting data.

## Recorded verification

| Gate | Measured result |
|---|---:|
| Offline unit/contract suite | 5,054 passed; one expected socket-blocking warning; 75% coverage |
| Source PostgreSQL group | 15 passed |
| Public application PostgreSQL group | 3 passed |
| Migration PostgreSQL group | 8 passed |
| Ruff / formatting / mypy | Passed |
| Independent implementation review / terminal audit | Passed for this scope |
| Real local CADEC material/provenance | 20/20 references verified |
| Rendered Streamlit interface and loopback service health | Passed; no research submitted by the agent |

The application tests use real PostgreSQL and simulated external HTTP. They cover
submission, source collection, generation, Qwen checking, restart, review/export,
source failure and multi-source operation. Consecutive identical multi-source
queries were also checked without resetting the database. These are not live
PubMed/DailyMed/FAERS freshness tests.

### Qwen Development evidence

The 36-case comparison produced33/36 agreement (91.67%): supported11/12,
uncertain12/12, unsupported10/12, with zero uncertain/unsupported-to-supported
false positives. All original thresholds passed. Runtime request-byte and raw
response/result replay passed36/36. The DeepSeek LOW baseline had32/36 agreement
and unsupported recall8/12; different vendor/operational profiles and a small
Development set prevent a general model-superiority claim. Holdout-20 remains unused.

### CADEC recovery evidence

The official archive was recovered byte-for-byte. The old project-generated
manifest was unavailable; a distinct recovery manifest and independent data audit
were created. The original identities remain historical. Original exclusions,
splits, encoding exception and reference-only terminology rules remain unchanged.
See [ADR-043](decisions/ADR-043-cadec-recovered-asset-profile.md).

The real-asset run verified20 references, with only metadata persisted. Cold
verification took about32–37 seconds. After exact archive/manifest hash checks,
20 warm provenance reads totaled0.526 seconds (maximum0.028 seconds each). UI API
reads have a finite90-second limit. Corpus text stays local/transient and has no
claim permissions in generated reports.

## Evidence identities and availability

The reviewed implementation was an uncommitted source snapshot above Git ancestor
`26c67108bf5b8de8b05bddf7e7ec5bac61261425`. Its 580-file manifest SHA-256 is
`b8ef64410f4ba1550f3741e7ec603708c23637a5f4202b698b1157f0881c3771`.
The GitHub preparation changes README/setup/history/status documentation and the
infrastructure template/ignore rules; it does not claim that the earlier whole-tree
manifest already includes those publication edits.

| Artifact | SHA-256 |
|---|---|
| Final offline test log | `522cdfb41a4acd9042f5b10b7ac09db651a47fa0cefffca8b8d4de2a67b8c67f` |
| Qwen complete comparison result | `e95e33ee3bcc879ef5201f2e1d2efb390f3080a1167aba0f1cdae3fe4945585c` |
| Original CADEC ZIP | `4045b926a0a5735f00f785f7ad935e5a73731d6ab607d11d88880a334be18c4a` |
| Recovery manifest | `a450e571db19c8d2c79944363daea5421e9aad8101e3da7f14e9cc464360c75b` |
| Reviewed recovery data audit | `4a9c87b32e739926098a570ed51d82543393bcd2e54b3683992cde7470dd4dc7` |
| Real CADEC runtime result | `32b512d84ac073dd8e1f1d34233ccecd0ec34a31b5d1154841aa13e1812b0b44` |

Raw delivery logs/receipts are retained under project-local
`.local/evidence/V1-QWEN-DELIVERY-20260918/`; model comparison evidence is under
`.local/evidence/QWEN-COMPARISON-20260918-004/`. These local raw artifacts are not
included in a Git clone. Hashes identify the recorded evidence; they do not replace
access to that evidence or a fresh independent run. Raw licensed corpus, model
credentials, databases and user exports are excluded from Git.

## Known operating limits

- English, local, single-user reference catalog; no patient-data input or clinical advice.
- DailyMed current labels only; its material cap blocks rather than inventing complete coverage.
- Missing CADEC assets are visible policy skips. Both exact archive and approved manifest
  must be supplied separately; cloning GitHub alone does not provision them.
- Unknown external attempts are not automatically resent. Source/model failures remain visible.
- Runtime implementation hashes bind persisted runs. Changing implementation bytes or Git
  ancestry may prevent resuming older runs; retain their original checkout and evidence.
- Human approval is required for every exported report.

For startup, configuration and database separation, use the [runbook](LOCAL_RUNBOOK.md).
