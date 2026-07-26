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

## Windows Python and quality toolchain

ME-000A1 uses uv `0.11.32` as the only Python environment and dependency
manager. uv installs CPython `3.12.13` and creates the repository-local
`.venv`; a system Python installation is not used. From Windows PowerShell:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\quality.ps1
```

Bootstrap uses the explicit development group:

```powershell
uv sync --locked --group dev
```

Networked dependency auditing remains deferred until a production dependency
exists. ME-000A2 adds the approved container, environment-validation, and CI
contracts described below.

## Authoritative offline checks

The local ME-000A1 command set remains authoritative. The optional Makefile
`quality` target and the Windows CI job delegate to the same commands:

```powershell
uv run --locked --no-sync ruff check .
uv run --locked --no-sync ruff format --check .
uv run --locked --no-sync mypy src
uv run --locked --no-sync pytest `
  tests/unit tests/contract `
  --disable-socket `
  --cov=medevidence `
  --cov-report=term-missing `
  --cov-report=xml
```

Unit and contract suites use directory-based classification and always disable
network sockets. Live API tests are explicitly opt-in.

## Local infrastructure

`docker-compose.yml` contains exactly PostgreSQL 18.4 and Qdrant 1.18.3.
Both images are digest-pinned, all published ports bind to `127.0.0.1`, and
both data stores use Docker-managed named volumes. PostgreSQL 18 data is mounted
at `/var/lib/postgresql`; Qdrant uses its unprivileged image and stores its
rebuildable index under `/qdrant/storage`.

Validate the committed template and all negative infrastructure-contract cases
without starting or pulling containers:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\validate-environment.ps1 -EnvFile .\.env.example -Template
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\validate-compose.ps1 -EnvFile .\.env.example -Template
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\test-infrastructure-contract.ps1
```

For persistent local infrastructure, copy the template, replace its password,
validate the real environment in strict mode, and then start Compose:

```powershell
Copy-Item .\.env.example .\.env
# Edit only .env and replace POSTGRES_PASSWORD.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\validate-environment.ps1 -EnvFile .\.env
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\validate-compose.ps1 -EnvFile .\.env
docker compose --env-file .\.env up -d --wait
docker compose --env-file .\.env down
```

The isolated smoke test creates a random in-memory password and temporary
loopback ports, verifies exact service versions, image digests, health, and
bindings, and removes its containers, network, and volumes:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\smoke-compose.ps1
```

Makefile targets are optional conveniences. Windows setup, validation, smoke
testing, and CI never require Make.

## Continuous integration

The required workflow contains exactly two jobs:

- `windows-quality` on `windows-2025` synchronizes the locked development
  environment and runs the four authoritative checks with `UV_OFFLINE=1`.
- `compose-config` on `ubuntu-24.04` runs the persistent infrastructure
  contract without starting containers or pulling images.

Both jobs have explicit timeouts, read-only repository permissions, concurrency
cancellation, and full-SHA action pins. Networked dependency auditing is not a
required PR job and remains deferred until a production dependency exists.

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
