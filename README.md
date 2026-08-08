# MedEvidence

MedEvidence is a research-oriented system for multi-source public drug-safety
information. It is intended for pharmaceutical, medical-research, and
pharmacovigilance research workflows. It does not provide diagnosis,
treatment, dosage, emergency guidance, or individualized medical advice.

## Repository status

**The approved `main` baseline remains the merged M1A-003B identity
`5102d56c73b6714d3608a93a47aa31f70ffa1097`. PR `#4` (M1A-003A) and PR `#5`
(M1A-003B) are merged and integrated. M1A-004 is committed at
`2f6cb0a2aa65c5c9e2292fb6e3010d5d14d767a0`, pushed, and hosted in green Draft
PR [#6](https://github.com/Jerry687/medevidence/pull/6); final PR-head review
and terminal audit passed, but M1A-004 is not merged or integrated.**

M0 and `ME-000A` are complete and approved. The approved baselines are:

- M0 tag: `m0-approved-v1`;
- ME-000A audited implementation:
  `c6384c766d0e65240ba617d9b78f17dd7f500260`;
- ME-000A `main` merge commit:
  `540420d437ff7306f4c53dc784ccf8ec5ced9e1d`; and
- ME-000A tag: `me-000a-approved-v1`; and
- M1A-001B `main` merge commit:
  `0bf3d58d7411fffa1873a6f2adab8ee73c23ce88`; and
- M1A-002 approved local `main` identity:
  `4f39ed3d27438e69a4a5a30ff6be499d247541c1`; and
- merged M1A-003B `main` identity:
  `5102d56c73b6714d3608a93a47aa31f70ffa1097`.

The original independent M0 review returned **FAIL**. The frozen remediation
later received an unconditional independent **PASS**, and the Project Owner
approved M0. Those historical records remain unchanged under `docs/reviews/`.

Implemented work consists of the approved Python and uv baseline, locked
development-quality tools, Windows validation scripts, loopback-only
PostgreSQL and Qdrant Compose infrastructure contracts, the two-job CI
foundation, and strict source-neutral M1A domain contracts for research scope,
planning/outcomes, provenance, publications/status, claims, citations, and
draft reports. The approved `main` baseline also contains the synchronous
bounded PubMed ESearch/EFetch connector, immutable exact-byte snapshots and
canonical manifests, and the PostgreSQL metadata adapter. PR `#4` and PR `#5`
are merged and integrated. M1A-003B's integrated gates passed 532 offline
unit/contract tests and 236 PostgreSQL integration tests with zero Docker
residue. Historical failed review candidates and the earlier 193/194 and
218/219 PostgreSQL runs remain preserved in their review and delivery records;
they are not the current baseline state.

M1A-004 adds committed PubMed application tools and deterministic draft-report
behavior on its pushed feature branch. Draft PR `#6` has green hosted CI and
passed final PR-head review and terminal audit, but remains unmerged. No FastAPI
business endpoint exists yet.
DailyMed, FAERS/openFDA, CADEC, retrieval, LangGraph, LLM, Streamlit, MCP,
export, and HITL capabilities remain planned.

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

Exact dependency, container, and GitHub Action versions were not selected
during M0. `ME-000A` subsequently approved the repository, development-tool,
container, and GitHub Action baselines. ADR-009 Revision 2 approves the exact
M1A direct dependency pins. M1A-001B added and locked
`pydantic==2.13.4` plus the development-only `pip-audit==2.10.1`. M1A-002 adds
the approved `httpx==0.28.1` and `defusedxml==0.7.1` production pins. It uses a
small explicit retry loop, so the approved optional Tenacity pin is not added.
The M1A-003B implementation commit adds the approved runtime pins
`SQLAlchemy==2.0.51` and `psycopg[binary]==3.3.4`, plus the approved production
schema-migration tooling pin `alembic==1.18.5`, and a complete 59-package lock.
The dependency evidence inventories the native `psycopg-binary` payload;
deployment suitability is not inferred. Later pins remain absent until their
first requiring focused work item.
Model-provider, retrieval-model/configuration, and external tracing decisions
remain behind their separate gates in the PRD.

Redis, React, GraphRAG, multi-agent workflows, ClinicalTrials.gov, signal
detection metrics, PHI workflows, and public multi-tenancy are outside V1.

## Approved bounded M1A sequence

M1A is the approved first business vertical slice and is limited to:

- typed source-neutral domain contracts;
- bounded PubMed search and record retrieval;
- deterministic offline fixtures;
- immutable raw snapshots and canonical manifests;
- PostgreSQL snapshot metadata;
- stable PubMed tools;
- deterministic attributed extracts with exact abstract-span citations;
- a structured, non-exportable `draft` report;
- FastAPI transport; and
- one separately opt-in, one-page/one-record live PubMed smoke query.

The required sequence is `M1A-001A`, `M1A-001B`, `M1A-002`, `M1A-003A`,
`M1A-003B`, `M1A-004`, then `M1A-005`. Each implementation work item requires
its own branch and focused Draft PR from the latest approved `main`; a
monolithic M1A implementation PR is not authorized.

ADR-009 Revision 2 and the owner-authorization package are approved and
effective. M1A-001B, M1A-002, M1A-003A PR `#4`, and M1A-003B PR `#5` are
reviewed, merged, and integrated into approved `main` baseline
`5102d56c73b6714d3608a93a47aa31f70ffa1097`. Live NCBI/TLS behavior remains
intentionally unverified. M1A-003A's historical CRLF failure and M1A-003B's
historical failed review/database evidence remain visible in their immutable
records. The integrated M1A-003B gates passed 532 offline unit/contract tests,
236 PostgreSQL integration tests, and left zero Docker residue.

`M1A-004` is committed at `2f6cb0a2aa65c5c9e2292fb6e3010d5d14d767a0`
and pushed on `feat/m1a-004-pubmed-tools-report` to Draft PR
[#6](https://github.com/Jerry687/medevidence/pull/6), titled
`M1A-004: expose PubMed tools and draft reports`. It adds strict source-neutral PubMed tool
contracts, consumer-owned injected ports, deterministic quoted query
construction, ordered search/fetch acquisition orchestration, exact Unicode
abstract-span claims/citations, publication-status restrictions, and a
non-exportable draft report bound to the run, catalog, acquisition, manifest,
envelope, and report-artifact identities. Persisted singular-fetch bindings now
prove one exact publication-content-artifact to current-manifest edge, which is
projected as the report publication's ordered current-run artifact lineage;
each persisted acquisition must also echo the exact ADR-010 acquisition-intent
identity, and every untrusted adapter result is recursively reconstructed before
downstream use. Failure diagnostics reject credential-like or multiline
content. Its tests are offline and injectable; the implementation has not
contacted PubMed/NCBI or run Docker. Hosted `compose-config` and
`windows-quality` succeeded, and final PR-head review and terminal audit both
returned PASS with P0 0 / P1 0 / P2 0. The Draft PR is not merged and M1A-004
has not entered the approved `main` baseline. `M1A-005` remains unimplemented.

The live-artifact policy `M1A-LIVE-RETENTION-v1` is approved. Live PubMed
execution remains unauthorized until the Project Owner separately approves the
exact query, NCBI client-identification values, execution time, and final
acceptance command. Default CI remains offline. No standalone ASGI server
dependency is authorized for M1A; `M1A-005` may use an in-process ASGI test
client.

## Bounded PubMed connector

M1A-002 uses the exact HTTPS origin
`https://eutils.ncbi.nlm.nih.gov` and only the approved ESearch and EFetch
paths. The general connector constructor requires an injected HTTPX transport;
it never creates a real transport by default. Automated tests use
`httpx.MockTransport` with sockets disabled.

The connector enforces finite query, page, record, cumulative-payload,
connect/read/write/pool timeout, total-deadline, retry/backoff,
`Retry-After`, and redirect limits. It validates every request, redirect, and
final response URL against the exact origin and path, safely parses untrusted
XML through `defusedxml`, preserves verified earlier results after a later
failure, and exposes typed connector and source-neutral terminal outcomes.

The explicitly named production factory requires a client email and is not
used by the default test or validation path. Live PubMed execution remains
unauthorized under the separate Owner gate above.

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

Networked dependency auditing is implemented in the separate, path-filtered
`dependency-audit` workflow. It remains outside the authoritative offline
quality command set. ME-000A2 adds the approved container,
environment-validation, and CI contracts described below.

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
cancellation, and full-SHA action pins. A separate path-filtered
`dependency-audit` workflow audits the locked Python dependency graph when its
metadata or audit implementation changes, after relevant pushes to `main`, or
by manual dispatch.

## Design and governance documents

- [Product requirements](docs/PRD.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Data-source semantics](docs/DATA_SOURCES.md)
- [Evaluation plan](docs/EVALUATION_PLAN.md)
- [Security and medical-safety policy](docs/SECURITY.md)
- [V1 traceability matrix](docs/TRACEABILITY_MATRIX.md)
- [Architecture decisions](docs/decisions/README.md)
- [Review, approval, and authorization records](docs/reviews/)
- [Interview narrative](docs/INTERVIEW_NOTES.md)
