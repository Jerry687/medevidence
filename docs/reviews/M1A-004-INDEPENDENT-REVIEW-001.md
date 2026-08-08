# M1A-004 Independent Review 001

- Work item: `M1A-004`
- Branch: `feat/m1a-004-pubmed-tools-report`
- Baseline: `5102d56c73b6714d3608a93a47aa31f70ffa1097`
- Initial candidate: `26165f0ab763416bf76df462589117d22f78921c2e6a9f0c277bbbfe1956b909`
- Initial decision: **FAIL — P0 0 / P1 5 / P2 1**
- Cycle-1 reviewed candidate:
  `144d213fd92896735c88564ef589cd95d3b99bd548b0a6de927fa546c3f0203a`
- Cycle-1 re-review decision: **FAIL — P0 0 / P1 2 / P2 0**
- Cycle-2 reviewed candidate:
  `a560ee33410c3d99221e899f5a07eb136f1556b857d8860d758360674f745c0f`
- Cycle-2 re-review decision: **FAIL — P0 0 / P1 1 / P2 0**
- Cycle-3 reviewed candidate:
  `a76c538e50c17e4a5dee7cb49d4edfd8807d8e04b9dd63c2f918b58ba72307eb`
- Cycle-3 re-review decision: **FAIL — P0 0 / P1 2 / P2 1**
- Cycle-4 authorization artifact SHA-256:
  `5a589571cfabd35f0187865381be1766204525df61c5208be2b735a3edf9d1ca`
  over 14,165 raw bytes
- Current status: **OWNER-AUTHORIZED CYCLE 4 IMPLEMENTED; FRESH RE-REVIEW PENDING**

## Review scope

Independent review must inspect the actual final 18-path diff and executable
behavior. It must specifically examine source traceability, no-I/O validation,
consumer-owned tool boundaries, all seven terminal outcome triples, complete-
only `no_match`, singular PMID ordering and fetch sequencing, acquisition-before-
next and run-last persistence, rollback surfaces, exact Unicode citations,
smallest-span tie-breaking, publication-status restrictions, report identity
bindings, deterministic replay, and absence of unauthorized paths or live
medical-source access.

## Initial findings

The independent review of the exact initial candidate returned **FAIL**:

1. P1: degraded matched-publication report construction did not preserve the
   composite outcome warnings/failure in valid provenance.
2. P1: a search could claim complete, nontruncated coverage when
   `total_available` exceeded returned PMIDs.
3. P1: standalone fetch did not bind `query_id` to the exact resolved query
   before execution-port I/O.
4. P1: consumer-owned execution DTOs accepted unbounded or incoherent adapter
   output.
5. P1: README and traceability current-state text incorrectly described merged
   M1A-003A/M1A-003B work as pending integration.
6. P2: candidate/evidence identity text was stale and did not record the exact
   reviewed candidate.

The earlier snapshot-versus-manifest equality concern was withdrawn because
the merged persistence contract freezes those identities as equal.

## Remediation cycle 1

Implementation-owned remediation adds degraded succeeded/failed partial-match
report regressions, exhaustive-search truncation checks, exact standalone-fetch
query binding, strict bounded execution/finalization DTOs, and corrected
baseline status text. These changes and their local tests are not independent
review evidence. A fresh reviewer must inspect the new exact candidate.

## Cycle-1 re-review findings

Independent re-review of exact candidate
`144d213fd92896735c88564ef589cd95d3b99bd548b0a6de927fa546c3f0203a`
returned **FAIL — P0 0 / P1 2 / P2 0**:

1. P1: retained report publications were not rebound to persisted current-run
   snapshot, artifact, and transformation-lineage evidence.
2. P1: failure `redacted_detail` accepted credential-like or multiline
   diagnostic content.

## Remediation cycle 2

Implementation-owned remediation adds strict persisted-publication bindings,
requires singular fetch binding cardinality and identity before continuation,
rebinds report publication provenance to current-run persisted evidence without
changing publication content identity, and closes credential/control leakage in
redacted diagnostics. These changes and tests are not independent review
evidence.

## Cycle-3 re-review finding

Independent review of exact candidate
`a76c538e50c17e4a5dee7cb49d4edfd8807d8e04b9dd63c2f918b58ba72307eb`
found that persisted acquisitions did not echo the exact expected acquisition
intent and that validation-bypassing model copies could reach downstream logic
without authoritative reconstruction of nested bindings and lineage edges.
The exact decision ledger was **FAIL — P0 0 / P1 2 / P2 1**.

## Owner-authorized remediation cycle 4

Implementation-owned remediation mirrors the exact merged ADR-010 acquisition
intent projection behind the consumer-owned tools contract, requires the
persisted acquisition to echo that identity, recursively reconstructs the
entire untrusted port result through closed strict models, and uses only the
reconstructed value downstream. The regression matrix covers wrong root and
nested types, unknown/missing fields, malformed or reused identities, wrong
identity kinds, cross-acquisition bindings, missing/extra/duplicate edges,
wrong lineage type/ordinal/endpoints, finalization blocking, immutable source
values, valid multi-acquisition execution, and offline no-match behavior.
These implementation-owned changes and tests are not independent review
evidence.

## Cycle-2 re-review finding

Independent re-review of exact candidate
`a560ee33410c3d99221e899f5a07eb136f1556b857d8860d758360674f745c0f`
returned **FAIL — P0 0 / P1 1 / P2 0**:

1. P1: the persisted publication binding carried artifact and lineage values,
   but did not prove exact publication-content-artifact to current-manifest
   endpoint ownership.

## Remediation cycle 3

Implementation-owned remediation introduces one strict source-neutral
`publication_to_manifest` edge, binds its parent to the content digest encoded
by the publication-version identity, binds its child to the current persisted
manifest/snapshot, and requires ordinal zero. The service validates those
endpoints before continuation; the report independently validates the same
ordered artifact chain. These changes and tests are not independent review
evidence.

## Decision

**PENDING FRESH RE-REVIEW.** All prior FAIL decisions remain recorded. This
remediation record is not approval, PASS, terminal audit, commit authorization,
PR-readiness, or integration evidence. Implementation-owned tests cannot fill
the independent gate.
