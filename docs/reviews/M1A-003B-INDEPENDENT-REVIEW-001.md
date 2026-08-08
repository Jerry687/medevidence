# M1A-003B Independent Review 001

- Work item: `M1A-003B`
- Branch: `feat/m1a-003b-postgres-snapshot-metadata`
- Baseline: `9f326481d13c149e818f77a75de3c53184522f0a`
- Reviewed candidate identity:
  `a10b414fc4c2f3473a2bea984215a4bd15f68eb0c7fae7d85611b35cdd4d8c24`
- Status: **FAIL**
- Findings: **P0 0 / P1 3 / P2 1**

## Review decision

The independent review failed the reviewed candidate. It did not authorize a
terminal evidence audit, commit, PR, merge, or approved-`main` integration.
Remediation cycle 2 is local and requires a fresh independent review of the
resulting candidate before any later lifecycle claim.

## Findings

| Severity | Finding | Reproduction evidence | Cycle 2 disposition |
|---|---|---|---|
| P1 | Acquisition and replay accepted contradictory provenance and source outcomes | `_validate_acquisition` compared only a subset of manifest/snapshot fields, and replay omitted stored outcome, membership, lineage, and publication equality. The reviewer reproduced a manifest `succeeded/complete/no_match` accepted beside a snapshot `failed/unavailable/indeterminate`, plus HTTP-status and membership contradictions. | Remediated locally with persistence-owned validated DTOs, complete pre-SQL equality, and replay-port equality checks; fresh review pending. |
| P1 | The 185-case PostgreSQL statement overstated public repository execution | Seven public operations were never called; complete successful acquisition/run-report registration and all 13 exact capacity thresholds were not executed. | Tests now contain success/failure coverage for all 12 operations, complete registration graphs, replay/lineage/read APIs, collisions, and all 13 capacity thresholds. The first cycle 2 database run passed 193/194 and exposed a full-capacity identity-precedence defect; after the bounded correction, the final same-lifecycle run passed 193/193 in 2.17 seconds. Fresh review remains pending. |
| P1 | Persistence imported concrete sibling ingestion implementation | `repositories.py` imported `SnapshotManifest`, `ArtifactLink`, `SnapshotStore`, and replay helpers, while the boundary test explicitly allowed `medevidence.ingestion.*`. | Removed. Persistence now depends only on standard library, domain, and SQLAlchemy and owns replay/storage protocols and DTOs. |
| P2 | Diagnostic-safe database URL exposed the username | Redacted output retained the username before a masked password. | Removed username, password, and query values from all renderings; added encoded credential, query, repr/str, and error tests. |

## Verified positives retained from review

- The approved companion was bound at 137,908 bytes and SHA-256
  `346f95b7d4aba72a9fccad597e684a6faab8f7115ca5272ca326bbece966e10e`.
- Frozen metadata remained 13 tables, 62 CHECK constraints, 17 foreign keys,
  13 primary keys, 22 unique constraints, and 12 secondary indexes.
- Application and private migration metadata were equivalent; all foreign keys
  were restrictive and only `fk_research_run_report` was deferred.
- The reviewed candidate had no UPDATE, DELETE, raw-byte PostgreSQL column,
  live medical-source request, or unauthorized dependency.

## Remediation evidence state

The implementation writer's initial cycle 2 work did not connect to PostgreSQL
or run Docker or network operations. Its focused selection passed 63 tests;
the full sockets-disabled unit/contract suite passed 479 tests at 82% aggregate
coverage; Ruff, format, MyPy, and lock checks passed; and 194 integration cases
were collected. A later authorized first database execution passed 193/194 and
failed the real `research_run` case because the full-capacity guard returned
`PersistenceCapacityError` for a differing row with the same immutable
identity. The bounded correction and regression tests are implemented locally;
the post-correction focused selection passed 115 tests, the full
sockets-disabled suite passed 531 tests at 82% aggregate coverage, and 193
integration cases were collected after moving the 52 deterministic capacity
states into the unit suite. Lock, Ruff, format, and MyPy checks passed. The
final same-lifecycle disposable PostgreSQL rerun passed 193/193 in 2.17
seconds. Its container used the approved pinned digest, `--pull never`, a
loopback-only port, tmpfs storage, and no mounts; it was removed and final
inspection found no matching container or volume. The final offline dependency
inventory reconciled 58 external packages and did not rerun advisories; the
unchanged lock retains the prior live Audit evidence. The final remediated
candidate identity remains pending fresh review and is not inferred from these
implementation-owned gates.

The review remains **FAIL** until an independent reviewer evaluates the actual
cycle 2 diff and records a new decision. Terminal audit, commit, hosted CI,
merge, approved-`main` integration, and live-source validation remain pending.

## Fresh independent review after cycle 2

- Reviewed candidate identity:
  `517271d6687541e9774c9a221416998e682e3eca46952ffc21e8238c68cd6b7a`
- Status: **FAIL**
- Findings: **P0 0 / P1 5 / P2 1**

The fresh reviewer retained the schema/migration and dependency-boundary
positives but reproduced six remaining defects:

| Severity | Finding | Final cycle 3 disposition |
|---|---|---|
| P1 | Acquisition prevalidation accepted a publication beside an exhaustive `no_match`, a mutually coherent complete HTTP 500 terminal response, and raw-artifact byte/media/path metadata that differed from the validated file graph. | Frozen cardinality, exhaustive-result, effective-response, and exact artifact metadata checks plus coherent counterexamples are implemented locally; re-review pending. |
| P1 | Publication insertion enforced JSON shape and projections but not the complete frozen `PublicationRecord` domain contract; the positive fixture also used non-contract language `eng`. | Persistence now validates the payload through the source-neutral domain model using validation-only provenance, compares the canonical frozen payload and projections, uses language `en`, and includes domain-invalid negatives; re-review pending. |
| P1 | Run/report accepted empty lineage, and snapshot loading overselected unrelated lineage when content-addressed children were shared. | Exact run-envelope/report and report/publication lineage validation and graph-owned snapshot lineage selection are implemented with reproductions; re-review pending. |
| P1 | Dependency evidence omitted bundled `psycopg-binary` native-library versions and operational ownership. | The fresh offline inventory records version/hash evidence for `libpq` 18.3, `libssl` 3.6.2, and `libcrypto` 3.6.2, distinguishes Alembic as production schema-migration tooling, and assigns Project Owner weekly monitoring and prompt patch response; re-review pending. |
| P1 | The all-table capacity claim still rested on a fake connection rather than PostgreSQL execution at every exact threshold. | The real 13-table matrix executed in PostgreSQL. After a stale rollback-test fixture caused the first 218/219 run to fail, a mechanical test-only repair produced a warning-free 219/219 rerun in 4.59 seconds; re-review pending. |
| P2 | A malformed port could escape both configuration boundaries as raw SQLAlchemy/Python exceptions. | Both boundaries now translate `ArgumentError` and invalid-port `ValueError` fail-closed, with credential-safe tests; re-review pending. |

Cycle 3 is the final authorized remediation cycle. Its implementation-owned
checks cannot change this review decision. The frozen-counterexample selection
passed 21 tests; the full sockets-disabled suite passed 532 tests with one
expected warning and 81% coverage; lock, Ruff, format, and MyPy passed; and 219
integration cases were collected. The first same-lifecycle PostgreSQL run
passed 218/219 and failed only because the strengthened prevalidation exposed a
stale rollback fixture. The authorized mechanical test-only correction in
`test_snapshot_metadata.py` preserved the intended rollback assertion and
removed 13 SQLAlchemy ordering warnings; the final full rerun passed 219/219 in
4.59 seconds with no warnings. The disposable cycle 3 container used the exact
pinned digest, `--pull never`, loopback-only port 61075, tmpfs storage, and no
mounts, and was removed with zero containers or volumes remaining. The fresh
offline inventory reconciled 58 external packages with advisory status
`not_run_offline` and recorded `libpq` 18.3 plus `libssl`/`libcrypto` 3.6.2.
No medical-source access or Git mutation occurred. A new independent review
and the terminal evidence audit remain **PENDING**; no commit, PR, hosted CI,
merge, or approved-`main` integration is claimed.

## Owner-authorized remediation cycle 4 state

A later independent review reproduced one additional P1 defect in exact
candidate
`a8f5b0231a1ac94a41ccf1ba2e64cc1d07bd5998e765fcf2dd0df49f9b671230`:
`register_run_and_report` did not require any durable acquisition attempt and
accepted a report-publication edge based on globally durable artifact metadata
without proving membership through an acquisition of the target run. This
record remains **FAIL**; the finding is not closed by implementation-owned
work.

Under the Owner's cycle 4 Option A decision, the local implementation now adds
an ordered source-neutral acquisition-reference tuple to the existing
`RunReportRegistration` input. Inside the separate final transaction and
before its first write, the repository compares that tuple exactly against the
bounded, ordered durable attempt set for the target run, requires the ordinal
zero search and contiguous ordinals, and checks all report-publication edges in
one bounded set-based query through current-run attempt, exact snapshot
binding, snapshot-publication membership, and publication-version artifact
binding. It uses the existing `PersistenceIntegrityError` and adds no schema,
migration, model, dependency, exception export, lock, UPDATE, or DELETE.

Seventeen new PostgreSQL regressions cover the Owner-required durable-attempt,
publication-ownership, and atomicity cases. Fresh root validation of the
pre-documentation candidate
`e3482d1a9d923f7bf828a04959fb36c1c0a6b260433feecbfa781c99b98792a6`
passed all **236/236** persistence integration cases in **6.02 seconds**. The
disposable PostgreSQL container used the approved pinned digest with `--pull
never`, tmpfs storage, no mounts, loopback-only publication, and was removed;
cleanup found zero containers, zero volumes, and only default networks.

The fresh root offline gate passed 532 unit/contract tests with one expected
socket warning and 80% coverage; lock (59 package records), Ruff, format (43
files), and MyPy (22 source files) also passed. The Owner-authorized live
dependency audit found no known vulnerabilities across the unchanged 58
external packages; network access was limited to PyPI package/advisory
metadata, with no medical-source request. Independent actual-diff and
counterexample re-review and terminal evidence audit were still **PENDING** at
this pre-review evidence point. No reviewer conclusion is inferred from the
implementation-owned evidence.

## Fresh independent review after cycle 4

- Reviewed technical candidate identity:
  `cceaa47edaddccc81e6a41760fc6b9efc1c2d0311ccc2ac9914e15ca13ed8b0f`
- Status: **PASS**
- Findings: **P0 0 / P1 0 / P2 0**

The reviewer inspected the actual cycle 4 diff, frozen Option A behavior,
bounded query shape, transaction placement, and executable counterexamples.
The three mandatory reproductions passed:

1. no durable attempt was rejected after one `SELECT`, with zero final writes;
2. a mismatched acquisition registration-envelope reference was rejected after
   one `SELECT`, with zero final writes; and
3. a publication reachable only through another run was rejected after two
   `SELECT` statements, with zero final writes.

Fresh reviewer gates passed the lock check, Ruff check, Ruff format check, and
MyPy; 532 sockets-disabled unit/contract tests with 80% coverage; the 116-test
focused selection; collection of all 236 persistence integration cases; and 20
database-independent integration cases. The 215 database-dependent cases
skipped because no database URL was present. The reviewer inspected the fresh
root 236/236 PostgreSQL evidence and did not rerun Docker or network operations.

All 15 protected pre-cycle hashes remained exact, with no scope drift from the
authorized six cycle 4 paths or 21-path candidate. No medical-source access or
Git mutation occurred. The terminal evidence audit remains **PENDING**. This
reviewer PASS does not claim terminal-audit PASS, commit, hosted CI, merge,
approved-`main` integration, or live-source validation.

## Final-byte review, terminal audit, and hosted evidence

- Final-byte candidate identity:
  `68391faf3933b8ebc56256d7183adab0f6beeec9c616c44fccd125929c5e8dde`
- Final-byte independent review: **PASS**
- Terminal evidence audit: **PASS, P0 0 / P1 0 / P2 0**
- Staged identity: exact match
- Implementation commit:
  `7bd41450cb13d9d118c64e8da51de0e10079bc6b`

The implementation commit was pushed normally to Draft PR
[#5](https://github.com/Jerry687/medevidence/pull/5), titled
`M1A-003B: persist snapshot metadata in PostgreSQL`. Hosted CI passed:

- `compose-config`: run `31238530166`, job `93055404634`, 38 seconds;
- `windows-quality`: run `31238530166`, job `93055404647`, 1 minute 3 seconds;
  and
- `dependency-audit`: run `31238530162`, job `93055404624`, 42 seconds.

The historical review failures and remediation trail above remain part of the
record. No medical-source request occurred. This four-document post-CI evidence
update follows the implementation commit, so final PR-head review and the
post-evidence-commit terminal audit remain **PENDING**. PR readiness, merge,
approved-`main` integration, and `M1A-004` remain **PENDING**.
