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

These decisions are accepted by the Project Owner. Overall M0 approval remains
conditional and does not become effective until remediation receives an
independent re-review PASS. The independent reviewer validates consistency and
is not the approving authority.

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
