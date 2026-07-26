# Interview Notes

## 1. One-sentence positioning

MedEvidence is a multi-source drug-safety research agent that combines
biomedical information extraction, structured-data tools, hybrid retrieval,
auditable orchestration, and evidence-grounded evaluation.

## 2. Project narrative

The project connects prior capabilities into one engineering story:

- ADR work contributes biomedical entities and adverse-reaction extraction.
- Data-governance work contributes metadata, provenance, and access discipline.
- Analytics work contributes reproducible pipelines, evaluation, dashboards,
  and business-facing delivery.
- MedEvidence adds RAG, tool calling, workflow orchestration, MCP, deployment,
  and observability.

## 3. The important design choice

The system is layered around a source-neutral evidence domain. PubMed,
openFDA, and DailyMed are adapters; LangGraph coordinates stable tools; MCP
exposes the same tools through another protocol. This prevents the agent
framework or a vector database from becoming the business architecture.

## 4. Why this is not a PDF chatbot

- It uses both unstructured literature and structured adverse-event queries.
- It preserves evidence type and source semantics.
- It compares BM25, dense, hybrid, and reranked retrieval.
- It checks conflicts, citation integrity, and uncertainty.
- It measures tool behavior, recovery, latency, and cost.
- It can degrade when a source is unavailable rather than fabricating coverage.

## 5. Technical tradeoffs to explain

### BM25 versus dense retrieval

Lexical retrieval may be stronger for exact drug names, identifiers, rare
adverse-event terms, and label wording. Dense retrieval may recover semantic
paraphrases. Hybrid retrieval expands candidate recall; reranking may improve
ordering at added latency and cost. State measured results only after running
the benchmark.

### FAERS interpretation

FAERS can surface reporting patterns and hypotheses, but lacks a reliable
exposure denominator and contains reporting biases and duplicates. Never
describe report counts as incidence or causal risk.

### Agent versus deterministic pipeline

Use deterministic code for source access, normalization, retrieval, validation,
and metrics. Use the model for bounded planning, tool selection, synthesis, and
language generation. LangGraph makes control flow, recovery, and review
observable.

### MCP

MCP is a protocol adapter over stable research tools. The project value is the
well-defined, validated tool contract, not merely running an MCP server.

### Confidence

Confidence should expose components such as evidence quality, directness,
coverage, consistency, recency, and citation support. Avoid an unexplained
single model-generated number.

## 6. Demonstration outline

1. Ask a comparison question.
2. Show the research plan and selected sources.
3. Show source-specific structured evidence.
4. Inspect a claim and its original citation.
5. Show a conflict or limitation.
6. Demonstrate one source failure and graceful degradation.
7. Compare retrieval baselines and latency.
8. Confirm the report before export.

## 7. Claims that require evidence before use

Do not place these in a resume or interview as accomplished until measured:

- “hybrid retrieval improved recall by X%”;
- “reranking improved nDCG by X”;
- “supports 100 evaluated questions”;
- “reduced latency/cost by X%”;
- “achieved X% citation accuracy”;
- “production-ready,” “HIPAA-compliant,” or “clinically validated.”

Use future-tense or design language until a reproducible artifact exists.

## 8. Honest current description

Current status: engineering architecture and evaluation plan established;
business implementation and empirical results not yet completed.

