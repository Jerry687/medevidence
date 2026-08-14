# MedEvidence

MedEvidence is a research-oriented system for multi-source public drug-safety
information. It is intended for pharmaceutical, medical-research, and
pharmacovigilance research workflows. It does not provide diagnosis,
treatment, dosage, emergency guidance, or individualized medical advice.

## Repository status

**The approved `main` baseline and accepted live-run code revision are
`531f867006f3d01ebbc14633ad6e5509e4e70a47`.
Run 001 remains
`M1A_LIVE_RUN_001_ACCEPTED_AS_FAILED_INTEROPERABILITY_EVIDENCE` and never
passed. The separately authorized Run 002 is `M1A_LIVE_RUN_002_ACCEPTED` and
establishes `M1A_LIVE_ACCEPTANCE_PASS`. M1A is `M1A_COMPLETE` and
`READY_FOR_M1B_OWNER_PLANNING`; M1B has not begun.**

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
  `5102d56c73b6714d3608a93a47aa31f70ffa1097`; and
- M1A-004-integrated historical `main` identity:
  `14a38d48416e8a4b63fe72b91ceb083f1d895473`; and
- M1A-005-integrated approved `main` identity:
  `47504a4016f968ed0a0dd10e4280b1a957c15461`; and
- current approved `main` identity:
  `531f867006f3d01ebbc14633ad6e5509e4e70a47`.

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

M1A-004's PubMed application tools and deterministic draft-report behavior are
merged. M1A-005 adds the single versioned
`POST /v1/research/pubmed` FastAPI operation, a fixed embedded catalog, closed
request/error contracts, an explicit composition boundary, normalized OpenAPI
evidence, and disabled-by-default live-smoke code. Ordinary validation remains
offline. PR #7 is merged at
`47504a4016f968ed0a0dd10e4280b1a957c15461`; hosted checks and final review/
audit were green before merge. The live gate remains disabled by default.
Run 002 later passed its separately authorized bounded live acceptance at the
current baseline. M1A is complete and M1B has not begun.
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
schema-migration tooling pin `alembic==1.18.5`. M1A-005 adds only the approved
base-package pin `fastapi==0.141.1`; its `standard` and `all` extras and Uvicorn
remain absent. The resolved additions are `fastapi`, `starlette`, and
`annotated-doc`. The dependency evidence inventories the native `psycopg-binary` payload;
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
`5102d56c73b6714d3608a93a47aa31f70ffa1097`. At that historical integration
point, live NCBI/TLS behavior was intentionally unverified; live run 001 is the
later bounded execution described below. M1A-003A's historical CRLF failure and
M1A-003B's historical failed review/database evidence remain visible in their
immutable records. The integrated M1A-003B gates passed 532 offline
unit/contract tests, 236 PostgreSQL integration tests, and left zero Docker
residue.

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
returned PASS with P0 0 / P1 0 / P2 0. M1A-005 is integrated and remains an
ancestor of the current approved baseline
`531f867006f3d01ebbc14633ad6e5509e4e70a47`.

The separately authorized M1A live run 001 executed one bounded PubMed ESearch
request at the PR #8 baseline and exited `1`. Immutable evidence reconstructs
the terminal connector outcome as `failed / unavailable / indeterminate` after
invalid XML on the first search response; fetch was not executed. The persisted
manifest/envelope uses `failed / partial / indeterminate` solely to retain the
received bytes. A redaction-harness numeric substring false positive prevented
the original acceptance record from being written. A structurally validated
no-clobber recovery record preserves the reconstructable facts. Offline
reproduction now identifies `CLIENT_XML_DTD_INTEROPERABILITY_FAILURE`: the
response bytes were received, and the historical parser rejected the official
external provider DOCTYPE. The exact retained bytes parse under the bounded
candidate as `PubMedSearchPage` with provider `count=676`, 100 returned
identifiers, and zero socket or external file-open calls. This was not an NCBI
outage. Live run 001 is dispositioned as
`M1A_LIVE_RUN_001_ACCEPTED_AS_FAILED_INTEROPERABILITY_EVIDENCE`; its historical
outcomes remain immutable. No rerun occurred within Run 001, and it never
established a live PASS. See [the recovery
record](.delivery/M1A-LIVE-RUN-001-RECOVERY.md) and [the interoperability
record](.delivery/M1A-PUBMED-DTD-INTEROPERABILITY.md).

The later, separately authorized live run 002 executed the same exact frozen
query at `2026-08-09T05:13:33.284549Z` on code revision
`531f867006f3d01ebbc14633ad6e5509e4e70a47`, using schema `1.0`, connector
`m1a-002`, and retention policy `M1A-LIVE-RETENTION-v1`. One run used exactly
two requests and two contiguous acquisitions. Search returned
`succeeded / partial / matches`, 100 valid results, one page, and
`truncated=true`; fetch returned `succeeded / complete / matches`, one valid
retained publication, one page, and `truncated=false`.

The accepted redacted record is 3,223 bytes with SHA-256
`008770e8155eee608aa71fab08cdd2a223f1e9ec92824427cc7a3409c6f69f25`.
It remains outside Git under the safe external root label
`OWNER_EXTERNAL_M1A_LIVE_RUN_002_ROOT` and relative label
`acceptance/pubmed-live-b1ab911398624933ab8fc06de2e08596.json`.
Closed-contract validation passed identity, containment, schema, redaction,
and unexpected-file checks. Operator-supplied evidence reports exit `0`,
`1 passed`, acceptance written, supplied environment values cleared, and a
clean repository immediately after the live run. This documentation did not
independently rerun the live test. No rerun occurred; live authority is
consumed and `rerun_authorized=false`.

Run 002 establishes `M1A_LIVE_ACCEPTANCE_PASS`; Run 001 remains historical
failed-interoperability evidence. The partial search is bounded and
non-exhaustive, and neither outcome supports causal, incidence,
comparative-risk, or clinical conclusions. The draft remains research-only,
non-exportable, and non-clinical. See [the Run 002 acceptance
record](.delivery/M1A-LIVE-RUN-002-ACCEPTANCE.md).

The exceptional Owner-authorized cycle-4 offline correction is integrated at
PR #9 merge `e8e28ffbde7fa3994ff8aa71dd62a956250147c1` and
confines all live credentials, transport/provider objects, raw content,
headers, complete URLs, and query parameters to one traceback-hidden sensitive
executor. The live test receives only a frozen closed scalar result. Recursive
structural redaction uses punctuation/case-insensitive key normalization;
fixed-code harness failures suppress original chains; offline subprocess and
AST gates check pytest output and source structure. Reviewer-triggered
mechanical rework pass 1 made the source gate derive every local helper
reachable from the sensitive executor and reject direct or aliased
`pytest.fail` plus an omitted newly raw-bearing helper. Final authorized pass 2
rejects every `pytest` module reference or propagated alias in that closure,
including local/module aliases and `getattr`. Its node-local checks were green
before integration. The external
recovery record is unchanged at 3,032 bytes with SHA-256
`1d90d931620952c0a0ea62aaa29d9b9a8c3ed952b3cef8860accf9db1e9f37cf`.
The provider-DTD compatibility work is integrated in the accepted Run 002 code
revision. The later live acceptance does not rewrite Run 001.

The live-artifact policy `M1A-LIVE-RETENTION-v1` remains approved. Every further
live run requires exact Owner authorization. Default CI and recovery validation
remain offline. No standalone
ASGI server dependency is authorized for M1A; `M1A-005` may use an in-process
ASGI test client.

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
used by the default test or validation path. The Run 002 authority is consumed;
any further live PubMed execution remains unauthorized without a new exact
Owner approval.

## Windows Python and quality toolchain

ME-000A1 uses uv `0.11.32` as the only Python environment and dependency
manager. uv installs CPython `3.12.13` and creates the repository-local
`.venv`; a system Python installation is not used. MedEvidence supports only
the `pwsh` executable with PowerShell Core `>= 7.6.4` and `< 7.7.0`. Windows
PowerShell 5.1 and `powershell.exe` are unsupported. From PowerShell 7.6 LTS:

```powershell
pwsh -NoLogo -NoProfile -File .\scripts\bootstrap.ps1
pwsh -NoLogo -NoProfile -File .\scripts\quality.ps1
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
pwsh -NoLogo -NoProfile -File `
  .\scripts\validate-environment.ps1 -EnvFile .\.env.example -Template
pwsh -NoLogo -NoProfile -File `
  .\scripts\validate-compose.ps1 -EnvFile .\.env.example -Template
pwsh -NoLogo -NoProfile -File `
  .\scripts\test-infrastructure-contract.ps1
```

For persistent local infrastructure, copy the template, replace its password,
validate the real environment in strict mode, and then start Compose:

```powershell
Copy-Item .\.env.example .\.env
# Edit only .env and replace POSTGRES_PASSWORD.
pwsh -NoLogo -NoProfile -File `
  .\scripts\validate-environment.ps1 -EnvFile .\.env
pwsh -NoLogo -NoProfile -File `
  .\scripts\validate-compose.ps1 -EnvFile .\.env
docker compose --env-file .\.env up -d --wait
docker compose --env-file .\.env down
```

The isolated smoke test creates a random in-memory password and temporary
loopback ports, verifies exact service versions, image digests, health, and
bindings, and removes its containers, network, and volumes:

```powershell
pwsh -NoLogo -NoProfile -File `
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
