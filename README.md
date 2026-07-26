# MedEvidence

MedEvidence is a research-oriented system for multi-source public drug-safety
information. It is intended for pharmaceutical, medical-research, and
pharmacovigilance research workflows. It does not provide diagnosis,
treatment, dosage, emergency guidance, or individualized medical advice.

## Repository status

**M0 consistency remediation — design and repository controls only.**

The repository contains approved V1 design documents, architecture decisions,
configuration skeletons, and empty implementation packages. It intentionally
contains no connector, domain, retrieval, LangGraph, LLM, FastAPI business,
Streamlit page, or MCP tool implementation.

The original independent M0 review returned **FAIL**. Remediation is recorded
under `docs/reviews/`; M0 approval is not effective until an independent
re-review returns PASS.

## Formal V1 reference domain

The release acceptance scenario compares public information about
gastrointestinal adverse reactions for semaglutide and tirzepatide.

This scenario is configuration and evaluation data, not hard-coded behavior.
Drug, adverse reaction, time range, and selected source are typed scope inputs.

## Source roles

- PubMed: scientific literature evidence.
- DailyMed: official labeling evidence.
- FAERS/openFDA: descriptive spontaneous-report data queried through a bounded
  structured-data tool; it is not ordinary document retrieval and cannot
  establish incidence, causality, or product safety ranking.
- CADEC: auxiliary NLP/retrieval corpus that cannot support clinical, causal,
  incidence, regulatory, or product-risk conclusions.

## Separate processing planes

```text
OFFLINE / INCREMENTAL INGESTION

PubMed / DailyMed / approved CADEC inputs
  -> connectors and immutable raw snapshots
  -> manifest + PostgreSQL provenance
  -> normalize / deduplicate / chunk
  -> rebuildable BM25 sparse + dense Qdrant index


ONLINE RESEARCH

ResearchScope
  -> safety and scope policy
  -> bounded source plan
  -> PubMed / DailyMed / local retrieval tools
  -> FAERS structured aggregate query
  -> claims and comparability analysis
  -> two-stage citation gate
  -> draft report
  -> save pending draft
  -> human confirmation before export
  -> idempotent finalize and export
```

Online research cannot publish or mutate the offline retrieval index. Qdrant is
derived and rebuildable; snapshots and PostgreSQL metadata preserve
authoritative provenance.

## V1 technology boundary

The approved capability set is Python 3.12, Pydantic, HTTPX, Tenacity,
FastAPI, SQLAlchemy, Alembic, PostgreSQL, Qdrant, LangGraph, Streamlit, pytest,
pytest-socket, Ruff, mypy, structured logging, and foundational OpenTelemetry.

Exact dependency, container, and GitHub Action versions are not selected during
M0. Decision gate `ME-000A` must complete before dependency installation or
container execution. Model-provider, retrieval-model/configuration, and
external tracing decisions have separate gates in the PRD.

Redis, React, GraphRAG, multi-agent workflows, ClinicalTrials.gov, signal
detection metrics, PHI workflows, and public multi-tenancy are outside V1.

## Authoritative offline checks

The required command set is identical in `AGENTS.md`, `Makefile`, and the CI
quality workflow:

```bash
python -m ruff check .
python -m ruff format --check .
python -m mypy src
python -m pytest tests/unit tests/contract --disable-socket
```

Unit and contract suites use directory-based classification and always disable
network sockets. Live API tests are explicitly opt-in. The CI file is a
disabled policy template during M0; `ME-000A` must approve and pin the runner,
actions, build backend, dependencies, and tool versions before activation.

## Local infrastructure skeleton

`docker-compose.yml` contains PostgreSQL and Qdrant only. Their image values
are intentionally unset until `ME-000A`; Compose execution is expected to fail
closed until approved image versions are supplied in a local `.env`.

## Design and governance documents

- [Product requirements](docs/PRD.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Data-source semantics](docs/DATA_SOURCES.md)
- [Evaluation plan](docs/EVALUATION_PLAN.md)
- [Security and medical-safety policy](docs/SECURITY.md)
- [V1 traceability matrix](docs/TRACEABILITY_MATRIX.md)
- [Architecture decisions](docs/decisions/README.md)
- [M0 review and approval records](docs/reviews/)
- [Interview narrative](docs/INTERVIEW_NOTES.md)
