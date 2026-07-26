# Retrieval Layer Rules

These rules extend the repository-root `AGENTS.md` for indexing and retrieval.

## Responsibility

This layer owns lexical retrieval, dense retrieval, hybrid fusion, metadata
filtering, candidate generation, reranking, and citation-bearing result
assembly. It must remain usable and evaluable without an LLM, LangGraph, API,
frontend, or MCP server.

## Contracts

- Expose a source-neutral query and result contract.
- Every result must retain evidence record ID, source identity, retrievable
  passage/span, rank, retrieval method, and applicable scores.
- Keep original BM25, dense, fusion, and reranker scores distinguishable.
- Do not expose Qdrant points or another backend's native objects as the public
  retrieval contract.
- Treat an index as a derived artifact, never the authoritative evidence store.
- Version corpus snapshots, index configuration, embeddings, sparse
  representation, chunking, and reranker configuration.

## Retrieval behavior

- Apply approved metadata filters consistently across baselines.
- Make result limits, candidate-pool size, fusion method, and score
  normalization explicit.
- Preserve deterministic tie-breaking where practical.
- Do not let reranking remove provenance or citation spans.
- Duplicate suppression must be source-aware and auditable.
- Empty results, filtered results, backend failure, and partial results are
  distinct outcomes.

## Replaceability

- Define ports independently from Qdrant or any embedding provider.
- Keep BM25, dense, hybrid, and reranking implementations independently
  testable.
- A model-based reranker is an optional adapter, not a prerequisite for the
  retrieval contract.
- Do not put report-generation prompts or agent planning in this layer.

## Evaluation discipline

Any retrieval change must be evaluated on the same frozen corpus and relevance
judgments as its baseline. Record:

- Recall@5 and Recall@10;
- MRR and nDCG at the approved cutoff;
- P50/P95 latency;
- corpus, index, model, and parameter versions;
- per-question raw results and category slices.

Do not claim an improvement from aggregate metrics alone when important
question categories regress. Changes tuned on development data must be
evaluated once on the held-out set under `evaluation/AGENTS.md`.

## Tests

- Unit tests cover filtering, fusion, score handling, tie-breaking, and result
  contracts with deterministic fixtures.
- Integration tests cover approved local retrieval backends.
- Retrieval tests must not require an LLM or internet access.
- Add regression cases for exact drug names, rare adverse-event terms,
  aliases, date filters, duplicate records, and missing citation spans.

