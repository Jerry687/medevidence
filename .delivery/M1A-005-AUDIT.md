# M1A-005 Implementation Audit

> **Historical pre-merge evidence — superseded for current integration state.**
> This document captures the M1A-005 implementation audit as it existed before
> PR #7 was merged. PR #7 was subsequently merged at
> `47504a4016f968ed0a0dd10e4280b1a957c15461`. Its earlier FAIL findings,
> candidate identities, and pre-merge wording remain historical evidence and
> are not rewritten here. Current integration state is recorded in
> [M1A-005-INTEGRATION-RECONCILIATION](M1A-005-INTEGRATION-RECONCILIATION.md).

- Work item: `M1A-005`
- Branch: `feat/m1a-005-fastapi-acceptance`
- Approved `main` baseline:
  `14a38d48416e8a4b63fe72b91ceb083f1d895473`
- Reviewed implementation parent commit:
  `5a75b96a034abbaf4769f9dfde93ea3bb154567e`
- Documentation evidence commits recorded in Git history:
  `d70b3121634ba2cd1ca89d7c935c6ec470a9a988` and
  `b603a2df6a1c1c16f5dd80cbd801d425aa6aed23`
- Draft PR: [#7](https://github.com/Jerry687/medevidence/pull/7),
  `M1A-005: expose and validate the PubMed vertical slice`
- Hosted checks: **PASS** — `compose-config`, `dependency-audit`, and
  `windows-quality`
- Independent implementation review: **PASS — P0 0 / P1 0 / P2 0**
- Terminal evidence audit: **PASS — P0 0 / P1 0 / P2 0**
- Lifecycle state: **COMMITTED, PUSHED, DRAFT PR; NOT MERGED OR INTEGRATED**
- Live PubMed acceptance: **NOT RUN**

## Owner authority and dependency decision

The controlling artifact is
`C:\Users\BoqiNiu\Downloads\M1A-005-API-FREEZE-v1.md`: 32,586 bytes,
SHA-256 `27da352fd395833de78d8eb6f9222d84e7410c02f4efd7785dc4398ec9c46b71`,
UTF-8/LF with terminal marker `READY_FOR_M1A005_IMPLEMENTATION\n`, status
**OWNER APPROVED — IMPLEMENTATION AUTHORIZED**. It supersedes ADR-009's older
provisional `fastapi==0.140.0` pin for this work item and explicitly authorizes
only `fastapi==0.141.1`, without FastAPI extras or Uvicorn. ADR-009 was not
changed.

The Owner amendment artifact is 12,490 bytes with SHA-256
`9f69433d1497e7631709171526472584da250c118bf12fb9b7fd9077210447f7`.
It authorizes operation-sensitive search/fetch cardinality correction in the
two added persistence paths, producing the amended exact 26-path allowlist.

## Scope and design

The implementation exposes only `POST /v1/research/pubmed` through an explicit
FastAPI application factory. It accepts the closed request contract, resolves
only the frozen catalog, delegates to the merged M1A-004 service, warning-safely
revalidates the returned `ResearchReport`, and emits fixed redacted versioned
errors. Request-ID factory failure receives a fresh local canonical UUID4
correlation at the failure boundary. Swagger UI, ReDoc, Uvicorn, FastAPI
extras, arbitrary queries, patient data, uploads, and additional routes remain
absent.

Concrete composition constructs the connector, M1A-004 ports, snapshot store,
and PostgreSQL repository per request without construction-time adapter I/O or
implicit real-transport fallback. Search persists positive PMID cardinality
without fabricated publication rows. Singular fetches persist independently,
and only successfully fetched and persisted publications enter the report.

Repository and replay validation distinguish search identifier cardinality
from fetch publication cardinality. Search owns zero publication rows,
memberships, and publication lineage. Fetch continues to require publication
count equal to manifest count equal to membership count, bounded to one.

The implementation remains bounded to the amended exact 26-path allowlist: the
original 24 freeze paths plus:

1. `src/medevidence/persistence/repositories.py`
2. `tests/integration/persistence/test_snapshot_metadata.py`

No schema, migration, domain contract, M1A-004 public contract, connector,
ingestion implementation, workflow, or medical-source authority changed.

## Historical review ledger

- Initial candidate
  `sha256:0813bc6c42d5dee434335749f018598d716cf8be38eb9fe7e0c40421be4449ed`:
  **FAIL — P0 0 / P1 2 / P2 2**.
- Cycle-2 candidate
  `sha256:ebf5d7c7994dc6ae40768f44852808bd6f8c4950c58b3d9640ff51da91e5b5c6`:
  **FAIL** because request-ID factory failures shared a hard-coded fallback
  correlation.
- Cycle-3 candidate
  `sha256:295c8401b9aa4f44038f93c16c8425c5a6266e6949016656e33f4aebd3020045`:
  independent review **PASS — P0 0 / P1 0 / P2 0**.
- Cycle-4 evidence candidate
  `sha256:cf1a65aecae71dbd8f35b56d29adb90ae43152512985ec39a2475665601053cb`
  was committed as
  `5a75b96a034abbaf4769f9dfde93ea3bb154567e` and pushed to Draft PR `#7`.
- Cycle-5 evidence candidate
  `sha256:ff2652651de9cde37ff767dd3d17201505062a1c64879889754cc22a96051177`
  was committed as documentation-only child
  `d70b3121634ba2cd1ca89d7c935c6ec470a9a988` and pushed to Draft PR `#7`.
- Cycle-6 evidence candidate
  `sha256:21c4d672fd21760c3ed10f8ae6d054411eaa631de4a1e41eef6cf90d83612d01`
  was committed as documentation-only child
  `b603a2df6a1c1c16f5dd80cbd801d425aa6aed23` and pushed to Draft PR `#7`.

The failures above are preserved as historical evidence and are not current
implementation findings.

## Validation evidence bound to the reviewed implementation

- focused M1A-005 unit/contract/e2e selection excluding live: 46 passed in
  0.55 seconds;
- full sockets-disabled unit/contract gate: 713 passed in 4.74 seconds, 79%
  coverage, with two expected warnings;
- `uv lock --check`, Ruff, 67-file format check, and MyPy over 34 source files:
  exit 0;
- combined PostgreSQL repository/API gate: 254 passed in 7.30 seconds;
  cleanup residue was 0 containers / 0 networks / 0 volumes;
- Docker used the cached approved PostgreSQL image with `--pull never`:
  `docker.io/library/postgres:18.4-bookworm@sha256:1961f96e6029a02c3812d7cb329a3b03a3ac2bb067058dec17b0f5596aca9296`;
- normalized OpenAPI fixture: 40,511 bytes, SHA-256
  `0d735acbbb1503dcc3235a37193b9d383cae08b8dc4fdb3b0e42616982ff028a`;
- dependency evidence: 61 external packages, 61 declared licenses, zero
  missing or review-required license records, zero vulnerabilities, and zero
  skipped packages;
- dependency candidate file-set identity:
  `sha256:e9dd241de6cfbf4a0cb05c863d32e4edcf21cf6440559124ba93233466ab630b`;
- dependency evidence-manifest SHA-256:
  `756c21b38536114807daee5dcb5e8716e16ab145742ba38739aeb83fc5cf9827`;
- dependency evidence directory:
  `C:\Users\BoqiNiu\AppData\Local\Temp\medevidence-m1a005-dependency-audit-cycle3-20260808`;
- implementation scope: 26 changed paths, 26 allowed, zero unexpected, and
  zero missing.

Hosted `compose-config`, `dependency-audit`, and `windows-quality` checks passed
for reviewed implementation commit
`5a75b96a034abbaf4769f9dfde93ea3bb154567e`. Independent review and terminal
evidence audit each returned **PASS — P0 0 / P1 0 / P2 0**. The pushed feature
ref contains later documentation-only evidence commits recorded in Git history.

## Network and Git boundary

No PubMed, NCBI, DailyMed, FAERS, or other medical-source request was made.
PostgreSQL validation traffic was loopback-only. Dependency advisory traffic
was limited to the approved vulnerability service and is not medical-source
evidence.

Git history records the implementation commit and the subsequent cycle-5 and
cycle-6 documentation-only evidence commits. The pushed feature ref contains
those committed ledger updates; Draft PR `#7` has not been merged.

## Remaining gates and risks

- Draft PR `#7` is not merged, and M1A-005 is not integrated into `main`.
- The pushed feature ref contains the documentation evidence commits recorded
  in Git history; their presence does not establish merge or integration.
- The disabled live PubMed test remains a separate Owner-authorized gate and
  was not collected or executed.
- FastAPI's TestClient emits an upstream Starlette deprecation warning; no
  unauthorized dependency was added to suppress it.

## Owner interview questions

1. Why may a search snapshot retain positive record count while owning no
   publication or membership rows?
2. How do explicit transport injection and request-scoped composition prevent
   import or application creation from contacting PubMed?
3. Why is valid persisted degradation HTTP 200 while forged output and
   persistence failures use fixed redacted errors?
