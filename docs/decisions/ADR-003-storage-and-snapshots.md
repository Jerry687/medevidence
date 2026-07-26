# ADR-003: Storage and snapshots

- Status: Accepted by Project Owner; M0 effectiveness pending independent re-review PASS
- Approved by: Boqi Niu
- Approval role: Project Owner
- Approval date: 2026-07-25
- Approval reference: M0-OWNER-APPROVAL-001
- Revision: 1
- Independent review reference: M0-INDEPENDENT-AUDIT-001
- Independent review role: Validation only; not an approving authority

## Context

Reports, citations, ingestion replay, and evaluation require immutable source
history. A vector index cannot serve as the authoritative record, and complete
raw datasets should not be committed to Git.

## Decision

V1 uses:

- immutable file snapshots for raw source responses and approved corpus inputs;
- a manifest for every ingestion containing source, query, UTC retrieval time,
  record count, SHA-256, connector version, schema version, bounds, coverage,
  file locations, and warnings;
- Git for small sanitized fixtures, manifests, and evaluation data only;
- PostgreSQL for source/snapshot metadata, versions, hashes, lineage,
  normalized identities, run/report/review records, bounded cache entries, and
  LangGraph checkpoints;
- Qdrant only for rebuildable sparse/dense vectors and chunk references.

Complete raw and normalized corpora, caches, database volumes, indexes, and
restricted content remain outside Git.

## Alternatives considered

- Store raw payloads only in PostgreSQL.
- Store all text and metadata only in Qdrant.
- Use SQLite for all V1 persistence.
- Add object storage and Redis in V1.

## Consequences

- Source history is replayable and indexes can be rebuilt.
- Local file lifecycle and backup policy must be documented.
- PostgreSQL remains the only durable application database in V1.
- Redis and object storage remain replaceable future adapters.
- Snapshot integrity becomes an explicit ingestion gate.

## Validation

- Replaying an unchanged snapshot produces deterministic record/chunk IDs.
- Hash, missing-file, schema, and record-count failures block index publication.
- Repository scans find no complete raw/normalized datasets or database/index
  volumes.
- Qdrant can be cleared and rebuilt from verified snapshots.

## Supersedes / Superseded by

None.
