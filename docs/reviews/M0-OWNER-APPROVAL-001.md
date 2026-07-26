# M0 Project Owner Approval Record

- Approval reference: M0-OWNER-APPROVAL-001
- Approved by: Boqi Niu
- Approval role: Project Owner
- Approval date: 2026-07-25
- Revision: 1
- Independent review reference: M0-INDEPENDENT-AUDIT-001
- Current status: **CONDITIONAL — NOT YET EFFECTIVE**
- Frozen design manifest: `docs/reviews/M0-DESIGN-MANIFEST.sha256`
- Frozen design manifest SHA-256: `23e8430e29c18cd4ab0b6266d671d7b999d436b083c717e1fc2c4ef11d9c683d`

## Approval scope

The Project Owner approves the remediated V1 design direction and decisions
recorded in ADR-001 through ADR-008, including:

- configurable reference domain;
- source-semantic separation;
- file snapshots, manifests, PostgreSQL provenance, and rebuildable Qdrant;
- BM25/dense/RRF architecture with executable configuration deferred;
- controlled export-only LangGraph HITL;
- sixty unique evaluation cases with Gold-10 inside Development-40;
- typed/versioned domain contracts;
- approved V1 capability stack with Redis and other deferred capabilities
  excluded.

## Effectiveness condition

This approval becomes effective only after:

1. ME-000 remediation is complete in the repository;
2. an independent reviewer verifies every entry in the
   `29`-file design corpus;
3. the independent re-review issues an unconditional PASS against
   `M0-INDEPENDENT-AUDIT-001` and the exact manifest SHA-256
   `23e8430e29c18cd4ab0b6266d671d7b999d436b083c717e1fc2c4ef11d9c683d`;
4. any new blocking finding is resolved or explicitly returned to the Project
   Owner for decision.

Until those conditions are met, this record does not authorize ME-000A or any
MedEvidence business implementation.

## Frozen design corpus and invalidation

The exact approval scope is the lexicographically sorted file corpus recorded
in `docs/reviews/M0-DESIGN-MANIFEST.sha256`, whose raw file bytes hash to the
overall SHA-256 shown above. The manifest includes normative M0 design,
repository instructions, nested instructions, ADRs, and executable
configuration; exclusions are recorded in `M0-DESIGN-MANIFEST.md`.

Any modification to a manifested file invalidates this conditional approval.
The manifest must be regenerated, the new hash recorded here and in the audit
record, and independent re-review repeated. A PASS against any different or
earlier manifest hash cannot activate this approval.

## Authority clarification

Boqi Niu, as Project Owner, is the approving authority. The independent
reviewer is a validation authority only and does not approve ADRs, scope,
technology, medical policy, or implementation start.

## Decision gates remaining after effective M0 approval

- `ME-000A`: exact dependency/container/Action/lock versions;
- `ME-000B`: LLM provider/model and data policy;
- `ME-000C`: Qdrant/BM25/embedding/reranker configuration;
- `ME-000D`: external tracing vendor and exporter policy;
- source-specific and medical/export decisions listed in PRD Section 11.
