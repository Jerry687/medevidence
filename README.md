# MedEvidence

MedEvidence is a research-oriented system for multi-source public drug-safety
information. It is intended for pharmaceutical, medical-research, and
pharmacovigilance research workflows. It does not provide diagnosis,
treatment, dosage, emergency guidance, or individualized medical advice.

## Repository status

**M1A-002 is locally integrated into the approved `main` baseline. M1A-003A
immutable snapshot/manifest work is locally committed at
`c3d724b2097c8df1249b217f610a78291039edbb` on
`feat/m1a-003a-snapshot-manifests`. The cycle-4 LF remediation is committed at
`52e71f0802e31580304980f487eba3c23f57db41`, pushed to PR `#4`, and hosted
rerun `31147466248` passes. Evidence reconciliation review/audit, its later
commit/push and hosted rerun, PR readiness, merge, and approved-`main`
integration remain pending.**

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
  `4f39ed3d27438e69a4a5a30ff6be499d247541c1`.

The original independent M0 review returned **FAIL**. The frozen remediation
later received an unconditional independent **PASS**, and the Project Owner
approved M0. Those historical records remain unchanged under `docs/reviews/`.

Implemented work consists of the approved Python and uv baseline, locked
development-quality tools, Windows validation scripts, loopback-only
PostgreSQL and Qdrant Compose infrastructure contracts, the two-job CI
foundation, and strict source-neutral M1A domain contracts for research scope,
planning/outcomes, provenance, publications/status, claims, citations, and
draft reports. The approved local `main` baseline also contains a synchronous
bounded PubMed ESearch/EFetch connector with hardened XML parsing and
deterministic offline HTTP transport contracts. The locally committed
M1A-003A feature-branch implementation adds typed journal contracts, immutable
exact-byte raw snapshot storage, canonical manifest construction, and replay
integrity checks. Its terminal implementation review and pre-commit evidence
audit passed. Hosted PR run `31146015339` passed Compose, Ruff, format, and
MyPy, but Windows tests reported 422 passed and 2 failed because Git checked
the canonical manifest fixture out with CRLF. Cycle 4 added the exact LF
checkout rule in remediation commit `52e71f0`. A fresh
`core.autocrlf=true` clone verified the 1,155-byte LF-only fixture and the two
formerly failing tests passed 2/2. Hosted rerun `31147466248` passed
Compose-config (114 cases), Ruff, format (32 files), MyPy (17 source files),
and the offline unit/contract suite (424 passed, one expected warning, 86%
coverage). The earlier failed run remains part of the record. Evidence
reconciliation and the remaining PR lifecycle gates are incomplete.

No PostgreSQL persistence adapter is integrated into `main` yet. The M1A-003B
persistence implementation is committed on its feature branch, but independent
review of candidate
`a10b414fc4c2f3473a2bea984215a4bd15f68eb0c7fae7d85611b35cdd4d8c24`
failed with P0 0 / P1 3 / P2 1. Remediation cycle 2 passed its 479-test
initial offline unit/contract gate. Its first expanded PostgreSQL run passed
193/194 and exposed a capacity-versus-conflict classification defect. After the
bounded fix, the final offline suite passed 531 tests at 82% coverage and the
same-lifecycle PostgreSQL rerun passed 193/193. Fresh independent review of
candidate `517271d6687541e9774c9a221416998e682e3eca46952ffc21e8238c68cd6b7a`
then failed with P0 0 / P1 5 / P2 1. Final remediation cycle 3 is local;
its full offline gate passed 532 tests at 81% coverage. The first cycle 3
PostgreSQL run passed 218/219 and exposed one stale rollback-test fixture; the
mechanical test-only repair was followed by a warning-free 219/219 rerun in
4.59 seconds. A later independent review reproduced a P1 finalization defect:
the candidate did not bind a run envelope to the complete durable attempt set
or prove that report publications belonged to the same run. Owner-authorized
remediation cycle 4 now adds those transactional gates and 17 focused
PostgreSQL regressions locally. Fresh root validation passed all 236 PostgreSQL
integration cases, all 532 offline unit/contract tests, lock, Ruff, format, and
MyPy. A fresh authorized dependency audit found no known vulnerabilities in
the unchanged 58-package external graph. Fresh independent review of exact
technical candidate
`cceaa47edaddccc81e6a41760fc6b9efc1c2d0311ccc2ac9914e15ca13ed8b0f`
passed with P0 0 / P1 0 / P2 0. Final-byte review and terminal evidence audit
also passed exact candidate
`68391faf3933b8ebc56256d7183adab0f6beeec9c616c44fccd125929c5e8dde`
with P0 0 / P1 0 / P2 0. Implementation commit
`7bd41450cb13d9d118c64e8da51de0e10079bc6b` was pushed normally to Draft PR
[#5](https://github.com/Jerry687/medevidence/pull/5), and all three hosted CI
jobs passed. Final PR-head review and post-evidence-commit terminal audit remain
pending; the PR is not ready or merged.
No application tool, report service, or FastAPI business endpoint exists.
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
effective. The governance package and M1A-001B implementation have been
reviewed and merged. M1A-002 is locally integrated into the approved `main`
baseline and is limited to the bounded connector plus its historical offline
evidence. Live NCBI/TLS behavior remains intentionally unverified. `M1A-003A`
is integrated in baseline `9f326481d13c149e818f77a75de3c53184522f0a`.
`M1A-003B` is committed as an exact 21-path feature-branch implementation. Its first
independent implementation review failed with three P1 and one P2 findings;
the earlier 185-case PostgreSQL run did not execute every claimed repository
path. Cycle 2 removes the concrete ingestion dependency, strengthens complete
provenance equality and replay ports, expands repository tests, and removes
credential identifiers from URL diagnostics. Its first database run passed
193/194 and caught a product defect in full-capacity identity precedence. The
corrected final gates passed 531 offline unit/contract tests at 82% aggregate
coverage and 193/193 PostgreSQL integration cases in 2.17 seconds. This is
implementation validation, not a reviewer PASS. Fresh review of candidate
`517271d6687541e9774c9a221416998e682e3eca46952ffc21e8238c68cd6b7a`
failed with P0 0 / P1 5 / P2 1 on acquisition completeness, full publication
domain validation, run/report lineage ownership, native dependency evidence,
real PostgreSQL capacity evidence, and invalid-port exception translation.
Final remediation cycle 3 addresses those frozen counterexamples locally;
the final PostgreSQL suite passed 219/219 after a stale rollback fixture was
mechanically corrected, and the refreshed offline dependency inventory records
the bundled native-library versions. These are implementation-owned results,
not a reviewer PASS. Cycle 4 is now implemented locally under the Owner's
Option A decision: final registration receives an ordered source-neutral
acquisition-reference tuple, requires exact equality with the target run's
durable attempts, and accepts report-publication lineage only when the cited
artifact is reachable through a current-run attempt, snapshot membership, and
publication-version binding. The 17 new database regressions are collected,
and fresh root execution now passes all 236 PostgreSQL integration cases in 6.02
seconds. The corresponding offline gate passes 532 tests at 80% coverage, and
the authorized dependency audit reports no known vulnerabilities. Those
validation results alone are not an independent-review or terminal-audit PASS.
Fresh independent review of exact technical candidate
`cceaa47edaddccc81e6a41760fc6b9efc1c2d0311ccc2ac9914e15ca13ed8b0f`
then passed with P0 0 / P1 0 / P2 0 after reproducing the missing-attempt,
mismatched-reference, and cross-run-publication failure paths with zero final
writes. Final-byte review and the terminal evidence audit passed exact candidate
`68391faf3933b8ebc56256d7183adab0f6beeec9c616c44fccd125929c5e8dde`
with P0 0 / P1 0 / P2 0, and its staged identity was exact. Implementation
commit `7bd41450cb13d9d118c64e8da51de0e10079bc6b` was pushed normally to Draft
PR [#5](https://github.com/Jerry687/medevidence/pull/5), titled
`M1A-003B: persist snapshot metadata in PostgreSQL`. Hosted CI passed
compose-config run `31238530166` job `93055404634` in 38 seconds,
windows-quality in the same run job `93055404647` in 1 minute 3 seconds, and
dependency-audit run `31238530162` job `93055404624` in 42 seconds. Final
PR-head review, final terminal audit after the evidence
commit, PR readiness, merge, and approved-`main` integration remain pending.
`M1A-004` onward remains unimplemented.

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
