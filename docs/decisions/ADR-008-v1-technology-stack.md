# ADR-008: V1 technology stack

- Status: Accepted by Project Owner; M0 effectiveness pending independent re-review PASS
- Approved by: Boqi Niu
- Approval role: Project Owner
- Approval date: 2026-07-25
- Approval reference: M0-OWNER-APPROVAL-001
- Revision: 1
- Independent review reference: M0-INDEPENDENT-AUDIT-001
- Independent review role: Validation only; not an approving authority

## Context

V1 needs enough infrastructure to demonstrate production-oriented RAG and
agent engineering while remaining deliverable as a local portfolio project.

## Decision

The approved V1 stack is:

- Python 3.12;
- Pydantic v2;
- HTTPX and Tenacity;
- FastAPI;
- SQLAlchemy 2 and Alembic;
- PostgreSQL;
- Qdrant;
- LangGraph;
- Streamlit;
- pytest, pytest-socket, Ruff, and mypy;
- structured logging and foundational OpenTelemetry;
- a model-provider gateway with one approved implementation.

Docker Compose is the local runtime boundary. Redis, React, GraphRAG,
multi-agent workflows, ClinicalTrials.gov, signal-detection metrics, PHI, and
public multi-tenancy are postponed.

No Redis runtime, environment variable, volume, or service dependency is
permitted in V1.

Decision gate `ME-000A`, owned by Boqi Niu as Project Owner, must approve exact
production dependency, container-image, GitHub Action, and lock-file versions
before dependency installation or container execution. Production dependencies
may then be added within this approved capability list using the approved
pinned versions. Adding a new production capability or replacing a major
component requires a new or superseding decision.

## Alternatives considered

- SQLite-only persistence and local FTS.
- PostgreSQL, Qdrant, and Redis from the first slice.
- React for the V1 frontend.
- A framework-generated autonomous agent and multiple specialized agents.

## Consequences

- V1 operates two durable infrastructure services: PostgreSQL and Qdrant.
- Streamlit minimizes frontend effort while FastAPI preserves a stable boundary.
- Redis and enterprise/public deployment complexity do not block the vertical
  slice.
- Exact model, embedding, and reranker choices remain configurable experiment
  decisions within the approved gateway/retrieval contracts.

## Validation

- Dependency lock/inventory contains only approved production capabilities.
- Docker Compose starts PostgreSQL, Qdrant, API, and UI by M4.
- CI runs offline static analysis and tests.
- Application contracts remain free of provider-native objects.

## Supersedes / Superseded by

None.
