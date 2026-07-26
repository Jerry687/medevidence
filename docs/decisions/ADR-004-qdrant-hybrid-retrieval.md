# ADR-004: Qdrant hybrid retrieval

- Status: Accepted by Project Owner; M0 effectiveness pending independent re-review PASS
- Approved by: Boqi Niu
- Approval role: Project Owner
- Approval date: 2026-07-25
- Approval reference: M0-OWNER-APPROVAL-001
- Revision: 1
- Independent review reference: M0-INDEPENDENT-AUDIT-001
- Independent review role: Validation only; not an approving authority

## Context

V1 must compare BM25, dense, and hybrid retrieval without maintaining an
additional search service or adding raw scores with incompatible scales.

## Decision

Qdrant stores named BM25 sparse and dense representations of the same
versioned textual chunks. V1 exposes:

1. BM25 sparse retrieval;
2. dense retrieval;
3. RRF fusion of sparse and dense candidate rankings;
4. an optional bounded second-stage reranker.

All modes use one source-neutral retrieval contract and consistent corpus,
filters, relevance judgments, and `k` values. Original component ranks/scores
and final rank are retained.

RRF is the frozen V1 fusion baseline. The reranker is not required for
availability and becomes a default only after measured quality/latency review.
FAERS aggregate observations are not inserted into the ordinary text index.

Executable retrieval configuration is not an M0 commitment. Decision gate
`ME-000C`, owned by Boqi Niu as Project Owner and due before M2, must approve
the Qdrant client/server versions, tokenizer, sparse encoding, BM25 `k1`/`b`,
dense embedding, reranker, and candidate/final limits.

## Alternatives considered

- SQLite FTS5 or a separate BM25 service plus Qdrant dense search.
- Direct weighted addition of raw sparse and dense scores.
- Dense-only retrieval.
- Reranking every query as a mandatory step.

## Consequences

- V1 operates PostgreSQL and Qdrant without an additional lexical-search
  service.
- Qdrant remains an adapter behind `RetrievalPort`.
- Experiments must version sparse/dense models, chunking, index, fusion, and
  reranker configuration.
- M2 cannot construct a release index or compare retrieval modes until
  `ME-000C` is approved.
- Vendor migration requires rebuilding derived indexes, not changing domain
  contracts.

## Validation

- BM25, dense, and RRF modes run independently on one frozen corpus.
- Raw result artifacts contain component and fused rankings.
- Recall@5/10, MRR@10, nDCG@10, and P50/P95 are reproducible.
- Clearing Qdrant does not remove authoritative source records.

## Supersedes / Superseded by

None.
