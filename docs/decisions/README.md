# Architecture Decision Records

Architecture Decision Records (ADRs) capture consequential decisions that
affect multiple layers, evidence semantics, safety policy, public contracts, or
production dependencies.

## Naming

```text
ADR-NNN-short-kebab-case-title.md
```

Start with `ADR-001`. Do not renumber accepted records.

## Status values

- Proposed
- Accepted
- Superseded
- Rejected
- Deprecated

## Required sections

```markdown
# ADR-NNN: Decision title

- Status:
- Approved by:
- Approval role:
- Approval date:
- Approval reference:
- Revision:
- Independent review reference:
- Independent review role: Validation only; not an approving authority

## Context
## Decision
## Alternatives considered
## Consequences
## Validation
## Supersedes / Superseded by
```

## Owner-accepted V1 records

These decisions were accepted by the Project Owner for M0. The original M0
audit FAIL and conditional approval remain preserved in their historical
records; the frozen remediation later received an unconditional independent
PASS and M0 became effective. The independent reviewer validates consistency
and is not the approving authority.

- [ADR-001: V1 reference domain](ADR-001-v1-reference-domain.md)
- [ADR-002: Source semantics](ADR-002-source-semantics.md)
- [ADR-003: Storage and snapshots](ADR-003-storage-and-snapshots.md)
- [ADR-004: Qdrant hybrid retrieval](ADR-004-qdrant-hybrid-retrieval.md)
- [ADR-005: Controlled LangGraph HITL](ADR-005-controlled-langgraph-hitl.md)
- [ADR-006: Evaluation split and reproducibility](ADR-006-evaluation-split-and-reproducibility.md)
- [ADR-007: Domain contracts and schema versioning](ADR-007-domain-contracts-and-schema-versioning.md)
- [ADR-008: V1 technology stack](ADR-008-v1-technology-stack.md)

Any change to an accepted decision requires a new ADR that supersedes it. Do
not edit history to make a prior decision appear different.

## Owner-accepted M1A governance record

- [ADR-009: M1A PubMed vertical-slice contracts and dependency gate](ADR-009-m1a-pubmed-vertical-slice-contracts.md)
  - Status: Accepted by Project Owner; effective for the post-merge M1A
    sequence
  - Authorization package:
    [M1A-001A-OWNER-AUTHORIZATION-001](../reviews/M1A-001A-OWNER-AUTHORIZATION-001.md)
  - Independent governance review:
    [M1A-001A-INDEPENDENT-REVIEW-001](../reviews/M1A-001A-INDEPENDENT-REVIEW-001.md)
  - Effect: After this exact governance candidate is merged into `main`, only
    `M1A-001B` may begin from the resulting approved baseline

ADR-009 approves the bounded M1A sequence, source-neutral PubMed contracts,
exact citation and snapshot semantics, synchronous PostgreSQL persistence,
draft-only FastAPI transport, `M1A-LIVE-RETENTION-v1`, and exact direct
dependency pins. The live query itself remains separately unauthorized, no
standalone ASGI server is approved, and no implementation, installation, or
lock-file change may occur on the unmerged governance branch.

## Owner-accepted M1A remainder amendment

- [ADR-010: M1A remainder freeze amendment](ADR-010-m1a-remainder-freeze-amendment.md)
  - Freeze: `M1A-REMAINDER-FREEZE-v3`
  - Present state: cycle-4 remediation committed and pushed; first hosted
    rerun PASS; evidence reconciliation and integration pending

ADR-010 appends exact journal identity, ordinal-reference, immutable snapshot,
canonical manifest, and constrained-capacity rules while preserving ADR-009
history. The implementation commit is
`c3d724b2097c8df1249b217f610a78291039edbb`. Hosted run `31146015339`
identified a Windows LF-checkout portability defect and remains recorded as a
failed run. Exact seven-path remediation commit
`52e71f0802e31580304980f487eba3c23f57db41` was pushed to PR `#4`; a fresh
`core.autocrlf=true` clone verified the LF checkout and the two formerly
failing tests passed 2/2. Hosted rerun `31147466248` passed compose-config
(114 cases), Ruff, format (32 files), MyPy (17 source files), and the offline
unit/contract suite (424 passed, one expected warning, 86% coverage).
Independent evidence-only review/audit of the reconciliation candidate, its
later commit/push and hosted rerun, PR readiness, merge, and approved-`main`
integration remain pending. No live-source validation occurred. It provides
no database, tool, report, or API implementation.
