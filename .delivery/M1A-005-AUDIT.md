# M1A-005 Implementation Audit

- Work item: `M1A-005`
- Branch: `feat/m1a-005-fastapi-acceptance`
- Approved baseline and current HEAD:
  `14a38d48416e8a4b63fe72b91ceb083f1d895473`
- Candidate state: uncommitted and unstaged
- Initial reviewed candidate:
  `sha256:0813bc6c42d5dee434335749f018598d716cf8be38eb9fe7e0c40421be4449ed`
- Initial independent review: **FAIL — P0 0 / P1 2 / P2 2**
- Cycle-2 candidate:
  `sha256:ebf5d7c7994dc6ae40768f44852808bd6f8c4950c58b3d9640ff51da91e5b5c6`
- Cycle-2 independent review: **FAIL — shared fallback correlation remained**
- Cycle-3 reviewed candidate:
  `sha256:295c8401b9aa4f44038f93c16c8425c5a6266e6949016656e33f4aebd3020045`
- Cycle-3 independent review: **PASS — P0 0 / P1 0 / P2 0**
- Terminal evidence audit: **PENDING**
- Hosted CI and integrated-main verification: **NOT RUN**
- Live PubMed acceptance: **NOT AUTHORIZED AND NOT RUN**

## Owner authority and dependency decision

The controlling artifact is
`C:\Users\BoqiNiu\Downloads\M1A-005-API-FREEZE-v1.md`: 32,586 bytes,
SHA-256 `27da352fd395833de78d8eb6f9222d84e7410c02f4efd7785dc4398ec9c46b71`,
UTF-8, LF-only, with its required terminal marker. Its status is
**OWNER APPROVED — IMPLEMENTATION AUTHORIZED**. It supersedes ADR-009's older
provisional `fastapi==0.140.0` pin for M1A-005 and explicitly authorizes only
`fastapi==0.141.1`, without FastAPI extras or Uvicorn. ADR-009 was not changed.

The Owner amendment artifact is 12,490 bytes with SHA-256
`9f69433d1497e7631709171526472584da250c118bf12fb9b7fd9077210447f7`.
It authorizes operation-sensitive search/fetch cardinality correction in the
two added persistence paths, producing the amended exact 26-path allowlist.

## Scope and design

The candidate exposes only `POST /v1/research/pubmed` through an explicit
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

## Exact scope

The candidate is bounded to the amended exact 26-path allowlist: the original
24 freeze paths plus:

1. `src/medevidence/persistence/repositories.py`
2. `tests/integration/persistence/test_snapshot_metadata.py`

No schema, migration, domain contract, M1A-004 public contract, connector,
ingestion implementation, workflow, or medical-source authority changed.

## Cycle-3 evidence bound to the reviewed candidate

- focused M1A-005 unit/contract/e2e selection excluding live: 46 passed in
  0.55 seconds;
- full sockets-disabled unit/contract gate: 713 passed in 4.74 seconds, 79%
  coverage, with two expected warnings;
- `uv lock --check`, Ruff, 67-file format check, and MyPy over 34 source files:
  exit 0;
- combined PostgreSQL repository/API gate: 254 passed in 7.30 seconds;
  cleanup residue was 0 containers / 0 networks / 0 volumes;
- Docker used the cached approved PostgreSQL 18.4-bookworm digest with
  `--pull never`;
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
- `git diff --check`: exit 0; exact scope was 26 changed paths, 26 allowed,
  zero unexpected, and zero missing.

The independent reviewer inspected exact cycle-3 candidate
`sha256:295c8401b9aa4f44038f93c16c8425c5a6266e6949016656e33f4aebd3020045`
and returned **PASS — P0 0 / P1 0 / P2 0**. This evidence-only cycle reconciles
the ledgers to that reviewed state. Terminal evidence audit remains pending.

## Network and Git boundary

No PubMed, NCBI, DailyMed, FAERS, or other medical-source request was made.
PostgreSQL traffic was loopback-only. Dependency advisory traffic was limited
to the approved PyPI vulnerability service and is not medical-source evidence.
No commit, stage, push, PR, merge, fetch, rebase, reset, clean, or remote-state
operation was performed.

## Remaining gates and risks

- Independent actual-diff review passed; terminal evidence audit is pending.
- Hosted CI, commit identity, PR state, and integrated-main verification do not
  yet exist.
- The implemented disabled live test remains a separate Owner-authorized gate
  and was not collected or executed.
- FastAPI's TestClient emits an upstream Starlette deprecation warning; no
  unauthorized dependency was added to suppress it.

## Owner interview questions

1. Why may a search snapshot retain positive record count while owning no
   publication or membership rows?
2. How do explicit transport injection and request-scoped composition prevent
   import or application creation from contacting PubMed?
3. Why is valid persisted degradation HTTP 200 while forged output and
   persistence failures use fixed redacted errors?
