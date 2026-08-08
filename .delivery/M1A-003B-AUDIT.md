# M1A-003B Local Implementation Audit

- Work item: `M1A-003B`
- Branch: `feat/m1a-003b-postgres-snapshot-metadata`
- Approved baseline: `9f326481d13c149e818f77a75de3c53184522f0a`
- Implementation commit and pre-evidence HEAD:
  `7bd41450cb13d9d118c64e8da51de0e10079bc6b`
- Status: **IMPLEMENTATION COMMIT AND HOSTED CI PASS; POST-EVIDENCE REVIEW/AUDIT PENDING**
- Candidate: exact 21-path implementation committed on the feature branch
- Failed reviewed candidate identity:
  `a10b414fc4c2f3473a2bea984215a4bd15f68eb0c7fae7d85611b35cdd4d8c24`
- Final independently reviewed technical candidate identity:
  `cceaa47edaddccc81e6a41760fc6b9efc1c2d0311ccc2ac9914e15ca13ed8b0f`
- Cycle 4 pre-remediation candidate identity:
  `a8f5b0231a1ac94a41ccf1ba2e64cc1d07bd5998e765fcf2dd0df49f9b671230`
- Cycle 4 pre-documentation candidate identity:
  `e3482d1a9d923f7bf828a04959fb36c1c0a6b260433feecbfa781c99b98792a6`
- Final-byte candidate and exact staged identity:
  `68391faf3933b8ebc56256d7183adab0f6beeec9c616c44fccd125929c5e8dde`

The initial independent review recorded **P0 0 / P1 3 / P2 1**; later review
cycles and remediation are preserved below. Final-byte review and the terminal
evidence audit passed with **P0 0 / P1 0 / P2 0** before the implementation
commit. This record does not claim final PR-head review, post-evidence-commit
terminal audit, PR readiness, merge, approved-`main` integration, or
live-source validation. The companion contract was bound before implementation to the
137,908-byte external artifact with SHA-256
`346f95b7d4aba72a9fccad597e684a6faab8f7115ca5272ca326bbece966e10e`.
The parent freeze SHA-256 was
`65d8ab5c6edc8970382eb3ccfdec769daa6dc2feddaef30e3d559dbeb35a47fe`.

## Implemented behavior

The local candidate implements the frozen synchronous PostgreSQL persistence
boundary with SQLAlchemy Core, Psycopg, and Alembic. It includes:

- schema `medevidence`, Alembic revision `m1a003b0001`, and the version table
  in `public`;
- exactly 13 application tables with the frozen column, primary-key, unique,
  foreign-key, CHECK, secondary-index, artifact-binding, outcome, capacity,
  and deferred run/report closure contracts;
- restrictive `ON UPDATE` and `ON DELETE` behavior for all foreign keys;
- immutable insert-or-verify behavior using savepoints and named-constraint
  race reconciliation, including identical and conflicting concurrent replay;
- separate acquisition and run/report transactions with rollback coverage;
- snapshot/publication identity and content-hash binding, canonical JSON byte
  validation in the owning layer, safe timestamp validation, exact catalog
  binding, registration-observation matrices, bounded table cardinalities,
  and credential/URL/path/detail redaction; and
- no PostgreSQL column for raw HTTP response bytes.

The design keeps persistence as an infrastructure adapter and does not change
domain, ingestion, connector, evidence, or medical-source semantics.

## Independent review failure and cycle 2

Independent review of candidate
`a10b414fc4c2f3473a2bea984215a4bd15f68eb0c7fae7d85611b35cdd4d8c24`
failed with three P1 findings and one P2 finding:

1. acquisition and replay did not compare complete source outcome and
   provenance;
2. the 185-case PostgreSQL statement did not execute every public repository
   operation or every exact capacity threshold;
3. persistence imported concrete sibling ingestion implementation; and
4. redacted database URLs retained the username.

Cycle 2 removes all concrete ingestion imports, adds consumer-owned replay
protocols and persistence-owned validated DTOs, enforces complete pre-SQL and
replay equality, expands the repository/capacity tests, and removes credential
identifiers from URL renderings. Fresh cycle 2 offline validation passed 479
unit/contract tests at 82% aggregate coverage, and 194 integration cases were
collected without a database connection. The first cycle 2 PostgreSQL execution
then passed 193 of 194 cases and exposed a product defect: at full
`research_run` capacity, a same-identity immutable mismatch was classified as
`PersistenceCapacityError` instead of `PersistenceConflict`. The bounded fix
and focused regression tests were implemented locally. The final same-lifecycle
PostgreSQL rerun then passed 193/193 in 2.17 seconds. Cycle 2 validation is not a
reviewer PASS and does not reuse the earlier 185-case result as proof for the
changed repository behavior.

## Fresh review failure and final remediation cycle 3

Fresh independent review of exact candidate
`517271d6687541e9774c9a221416998e682e3eca46952ffc21e8238c68cd6b7a`
returned **FAIL, P0 0 / P1 5 / P2 1**. The reviewer reproduced incomplete
acquisition outcome/artifact checks, missing full `PublicationRecord` domain
validation, incomplete run/report and shared-child lineage ownership, missing
native-library dependency evidence and ownership, non-PostgreSQL all-table
capacity proof, and invalid-port exceptions escaping the typed/redacted
configuration boundaries.

Final remediation cycle 3 implements the frozen corrections without changing
the 13-table schema, dependency set, or public persistence interface. It adds
mutually coherent counterexamples, full domain-payload validation, exact
run/report and snapshot-owned lineage checks, a real PostgreSQL 13-table
maximum/precedence matrix, fail-closed port parsing, and saved native-library
inventory support. Fresh independent re-review and terminal audit remain
**PENDING**; this implementation-owned remediation is not a reviewer PASS.

## Owner-authorized remediation cycle 4

A later independent review reproduced one P1 finalization defect: final
run/report registration trusted a prevalidated run-envelope graph and global
publication existence without proving that the complete durable acquisition
set belonged to the target run or that cited publications were members of a
snapshot acquired by that run. The Owner authorized exactly one additional
cycle and selected Option A: extend the existing `RunReportRegistration`
input with a validated source-neutral ordered tuple of acquisition ordinal and
acquisition registration-envelope identity.

Cycle 4 is implemented locally without a schema, migration, model, dependency,
lock, UPDATE, DELETE, or additional-path change. Before the first final write,
the existing run/report transaction now:

- loads at most 102 target-run attempts ordered by acquisition ordinal;
- requires one to 101 durable attempts, a search at ordinal zero, contiguous
  ordinals, exact target-run ownership, and one-to-one equality with the
  ordered input references; and
- uses one bounded set-based join through target-run attempt, exact
  manifest/acquisition-intent snapshot binding, snapshot-publication composite
  membership, and publication-version artifact binding to require every cited
  report publication to be current-run reachable.

The query permits an earlier-created publication version when the current run
has its own durable membership, permits citations from any one of several
current-run attempts, does not require every acquired publication to be cited,
and leaves search-only complete `no_match` valid. Traceability failure raises
the existing `PersistenceIntegrityError` before final artifacts or metadata are
written, so previously committed acquisition metadata is unchanged.

Seventeen focused PostgreSQL regressions cover the complete Owner list:
missing/searchless/mismatched attempts, exact accepted references, cross-run
and globally unowned publications, artifact-binding mismatch, earlier-version
current membership, several attempts, uncited publications, and transaction
atomicity. The fresh root PostgreSQL run passed all **236/236** persistence
integration cases in **6.02 seconds**, including all 17 new cases. Independent
re-review then passed; terminal evidence audit remains **PENDING**.

## Fresh independent review after cycle 4

The independent reviewer evaluated exact technical candidate
`cceaa47edaddccc81e6a41760fc6b9efc1c2d0311ccc2ac9914e15ca13ed8b0f`
and returned **PASS, P0 0 / P1 0 / P2 0**. Mandatory counterexamples reproduced
the frozen fail-closed behavior:

- no durable attempt was rejected after one bounded `SELECT`, with zero final
  writes;
- a mismatched registration-envelope reference was rejected after one bounded
  `SELECT`, with zero final writes; and
- a publication reachable only through another run was rejected after two
  bounded `SELECT` statements, with zero final writes.

The reviewer freshly passed the lock, Ruff, format, and MyPy gates; 532 offline
unit/contract tests at 80% coverage; the 116-test focused selection; integration
collection of 236 cases; and 20 database-independent integration cases, with
215 database-dependent cases skipped because no database URL was supplied. The
reviewer inspected the root 236/236 PostgreSQL evidence but did not rerun Docker
or network operations. All 15 protected pre-cycle hashes remained exact, the
candidate retained the authorized six-path cycle 4 delta and 21-path total
scope, and no medical-source access or Git mutation occurred. At that review
point, terminal evidence audit remained **PENDING**; the reviewer PASS alone was
not a terminal work-item PASS.

## Final-byte audit, implementation commit, and hosted CI

The final-byte candidate identity was
`68391faf3933b8ebc56256d7183adab0f6beeec9c616c44fccd125929c5e8dde`.
Independent final-byte review passed, and the terminal evidence auditor returned
**PASS, P0 0 / P1 0 / P2 0**. The staged identity matched that exact candidate.
The implementation was committed as
`7bd41450cb13d9d118c64e8da51de0e10079bc6b` and pushed normally, without force,
to Draft PR [#5](https://github.com/Jerry687/medevidence/pull/5), titled
`M1A-003B: persist snapshot metadata in PostgreSQL`.

Hosted CI passed:

- `compose-config`: run `31238530166`, job `93055404634`, 38 seconds;
- `windows-quality`: run `31238530166`, job `93055404647`, 1 minute 3 seconds;
  and
- `dependency-audit`: run `31238530162`, job `93055404624`, 42 seconds.

No medical-source request occurred. Because this post-CI evidence update changes
the four documentation records after the implementation commit, final review of
the resulting PR head and a final terminal audit after the evidence commit remain
**PENDING**. PR readiness, merge, approved-`main` integration, and `M1A-004`
authorization or implementation also remain **PENDING**.

## Exact 21-path scope

The implementation commit contains exactly these 21 authorized paths:

1. `alembic.ini`
2. `alembic/env.py`
3. `alembic/script.py.mako`
4. `alembic/versions/20260806_01_m1a_003b_snapshot_metadata.py`
5. `src/medevidence/persistence/__init__.py`
6. `src/medevidence/persistence/config.py`
7. `src/medevidence/persistence/models.py`
8. `src/medevidence/persistence/repositories.py`
9. `src/medevidence/persistence/session.py`
10. `tests/unit/persistence/test_config.py`
11. `tests/unit/persistence/test_metadata.py`
12. `tests/integration/persistence/test_migrations.py`
13. `tests/integration/persistence/test_snapshot_metadata.py`
14. `pyproject.toml`
15. `uv.lock`
16. `tests/unit/test_dependency_boundaries.py`
17. `scripts/dependency-audit.ps1`
18. `README.md`
19. `docs/TRACEABILITY_MATRIX.md`
20. `.delivery/M1A-003B-AUDIT.md`
21. `docs/reviews/M1A-003B-INDEPENDENT-REVIEW-001.md`

No other repository path is part of the implementation commit.

## Dependency and lock evidence

The candidate adds exactly three approved direct pins. Runtime persistence uses:

- `SQLAlchemy==2.0.51`
- `psycopg[binary]==3.3.4`

Production schema-migration tooling uses:

- `alembic==1.18.5`

`uv lock --check` passed and the lock contains 59 package records: the local
project plus 58 external packages. The dependency-audit node ran the repository
`scripts/dependency-audit.ps1` in `Audit` mode against logical branch
`feat/m1a-003b-postgres-snapshot-metadata` and expected commit
`9f326481d13c149e818f77a75de3c53184522f0a`. The exact shell quoting was not
retained; the manifest fields are the authoritative invocation provenance.

Live advisory evidence directory:

`C:\Users\BoqiNiu\AppData\Local\Temp\medevidence-m1a003b-audit-f1bcdcaab9dd4631828da24d319bb00a`

- outcome: `pass`;
- 58 external packages represented in the lock, resolved requirements/tree,
  licenses, CycloneDX SBOM, and vulnerability audit;
- 58 declared licenses, zero missing metadata, zero review exceptions;
- advisory result: zero known vulnerabilities, zero skipped packages;
- candidate file-set identity:
  `sha256:9ab883fb7b1bbd63a602b024b2de1dbb7986a4fe89feb94fae2374c05afacd4b`;
- evidence-manifest SHA-256:
  `92091a7cc55b4694e1b3ab6cb810863b2089de2d2c07f8479b14e40fec822650`.

After remediation cycle 1 changed only the integration test harness, the
dependency node refreshed the inventory offline in:

`C:\Users\BoqiNiu\AppData\Local\Temp\medevidence-m1a003b-remediation-inventory-af0d537702a64fe2832076e729e3d182`

- outcome: `pass`, advisory status `not_run_offline`;
- the same 58 external packages and canonical package-set identity were
  reconciled across every offline representation;
- candidate file-set identity:
  `sha256:57295fced69489852a06e6fea73a0fe3a6599c798479dd102c21cf80e3eb657d`;
- evidence-manifest SHA-256:
  `94d4e56f941ac796b50b3ba3496e0234e73aaa522d20902cfaab78ba75eaacb6`.

The first attempt to run the final cycle 2 inventory was blocked by host policy
before script execution and produced no inventory evidence. The established
`powershell.exe -ExecutionPolicy Bypass` invocation then ran
`scripts/dependency-audit.ps1` successfully in `Inventory` mode, offline, at:

`C:\Users\BoqiNiu\AppData\Local\Temp\medevidence-m1a003b-rem2-inventory-2c1e7ab3`

- 58 external packages reconciled;
- candidate file-set identity:
  `sha256:4fd7229067453ddf0e547661dc66b9d2ce122359e639336c2b018373b0123d62`;
- evidence-manifest SHA-256:
  `7a3a096c1deb58aaf9b6188b72ed033b52d1442f3dfa079639968529d17b715a`;
- advisory status: `not_run_offline`.

The offline inventories did not rerun advisories and do not supersede or
enlarge the earlier live advisory claim. Because the lock and dependency graph
did not change, the prior live Audit result remains the applicable
no-known-vulnerability evidence for that unchanged graph.

The cycle 3 audit-script contract additionally writes
`psycopg-binary-native-libraries.json`. The fresh offline inventory completed
at:

`C:\Users\BoqiNiu\AppData\Local\Temp\medevidence-m1a003b-rem3-inventory-da5a8618a00a4de599ae288ffbc0ca3c`

- 58 external packages reconciled;
- advisory status: `not_run_offline`;
- candidate file-set identity:
  `sha256:11bcb09c1854adc19a52f02a3a62b58501e1abe8b1a4d474edfb1d18b1f64137`;
- evidence-manifest SHA-256:
  `d7fc681a4c023cf973d8636bbb0a425e803a6932d47dba11145548366f83e114`;
- bundled native versions: `libpq` 18.3, `libssl` 3.6.2, and `libcrypto`
  3.6.2.

The native evidence records each filename, file/product version, SHA-256,
platform, and process architecture. The **MedEvidence Project Owner** owns
weekly advisory monitoring and prompt patch response for the pinned native
payload under the current evidence contract. This offline inventory did not
rerun advisories and does not establish production deployment suitability; the
prior live no-known-vulnerability evidence remains applicable to the unchanged
dependency graph.

After cycle 4 implementation, the Owner-authorized fresh live dependency audit
completed at:

`C:\Users\BoqiNiu\AppData\Local\Temp\medevidence-m1a003b-cycle4-audit-9ea27f17c0394c5ca6ecb129bf6d69c5`

- outcome: `pass`, with no known vulnerabilities;
- 58 external packages audited;
- candidate file-set identity:
  `sha256:5ea738c5ceafba252d24bdf903e76e96a0fd8b0e14453d3c0c8e581909461003`;
- evidence-manifest SHA-256:
  `6e38c26f4655e6f08469ea5259422538bdac3705a91ef7f85b4ef197bb9439c9`;
- network access was limited to authorized `pypi.org` and
  `files.pythonhosted.org` package/advisory metadata; no medical-source request
  occurred.

## Focused and full offline validation

The implementation and validation nodes executed:

```text
uv lock --check
uv run --locked --no-sync pytest tests/unit/persistence tests/unit/test_dependency_boundaries.py -q
uv run --locked --no-sync ruff check .
uv run --locked --no-sync ruff format --check .
uv run --locked --no-sync mypy src
$out=Join-Path $env:TEMP 'medevidence-m1a003b-coverage.xml'; uv run --locked --no-sync pytest tests/unit tests/contract --disable-socket --cov=medevidence --cov-report=term-missing --cov-report="xml:$out"
```

Observed results:

- lock check: PASS, 59 package records;
- focused persistence and dependency-boundary selection: 20 passed;
- Ruff check: PASS;
- Ruff format check: PASS for 43 files;
- MyPy strict check: PASS for 22 source files;
- full offline unit/contract suite: 436 passed, one expected
  `pytest-socket` warning, 82% aggregate coverage.

Remediation cycle 1 was mechanical and changed only the two authorized
integration-test harness files. It corrected disposable-database test isolation
and cleanup behavior; it did not change product code, DDL, dependencies, public
interfaces, or persistence semantics. The refreshed focused/full gates above
passed after remediation.

Cycle 2 fresh offline gates executed after the reviewer FAIL:

- focused persistence and dependency-boundary selection: 63 passed;
- Ruff check: PASS;
- Ruff format check: PASS for 43 files;
- MyPy strict check: PASS for 22 source files;
- full sockets-disabled unit/contract suite: 479 passed, one expected
  `pytest-socket` warning, 82% aggregate coverage;
- integration collection only: 194 cases collected;
- first PostgreSQL execution: **FAIL**, 193 passed and 1 failed because
  identity-conflict precedence was incorrectly classified at full
  `research_run` capacity;
- capacity-precedence remediation focused selection: 115 passed;
- capacity-precedence remediation full sockets-disabled suite: 531 passed,
  one expected `pytest-socket` warning, 82% aggregate coverage;
- post-remediation integration collection: 193 cases, after moving the 52
  deterministic capacity states into the offline unit suite;
- post-remediation lock, Ruff, format, and MyPy checks: PASS;
- final capacity-precedence PostgreSQL rerun: **PASS, 193/193 in 2.17 seconds**.

Final cycle 3 implementation-owned evidence:

- focused frozen-counterexample selection: 21 passed;
- full sockets-disabled unit/contract suite: 532 passed, one expected
  `pytest-socket` warning, 81% aggregate coverage;
- lock, Ruff, format, and MyPy checks: PASS (43 formatted files and 22 typed
  source files);
- integration collection: 219 cases, including 13 real-PostgreSQL capacity
  maximum and identity-precedence cases;
- PowerShell dependency-audit script parse: PASS;
- first same-lifecycle PostgreSQL execution: **FAIL, 218/219** solely because a
  stale rollback fixture reached the newly strengthened prevalidation and
  raised `KeyError: coverage_status` before its intended transactional failure;
- mechanical test-only repair in
  `tests/integration/persistence/test_snapshot_metadata.py`: complete valid
  run/report/lineage setup followed by the intended post-write repository
  failure, plus explicit table ordering to eliminate SQLAlchemy warnings;
- final full same-lifecycle PostgreSQL rerun: **PASS, 219/219 in 4.59 seconds,
  no warnings**;
- fresh offline dependency inventory: PASS for 58 external packages, advisory
  status `not_run_offline`, with bundled native-library evidence recorded.

Cycle 4 implementation-writer evidence, with no database connection:

- focused persistence and dependency-boundary selection: 116 passed;
- source-neutral run/report validator selection: 1 passed;
- the integration module's database-independent cases: 20 passed, while 215
  database-dependent cases skipped because `MEDEV_DATABASE_URL` was absent;
- full sockets-disabled unit/contract suite: 532 passed, one expected
  `pytest-socket` warning, 80% aggregate coverage;
- lock: PASS with 59 package records;
- Ruff check: PASS;
- Ruff format check: PASS for 43 files;
- MyPy strict check: PASS for 22 source files; and
- integration collection only: 236 cases, exactly 17 more than cycle 3.

Fresh root validation after the cycle 4 implementation passed:

- lock check with 59 package records;
- Ruff check and Ruff format check for 43 files;
- MyPy strict check for 22 source files;
- the full sockets-disabled unit/contract suite, **532 passed** with one
  expected `pytest-socket` warning and **80%** aggregate coverage; and
- the full PostgreSQL persistence integration suite, **236/236 passed in 6.02
  seconds**.

The external coverage XML is retained at
`C:\Users\BoqiNiu\AppData\Local\Temp\medevidence-m1a003b-cycle4-coverage-9153283962af47b2aa0f51aa852d9bf2.xml`.
The earlier 219/219 database result remains historical cycle 3 evidence and is
not reused as proof for cycle 4.

## Disposable PostgreSQL integration validation

The integration node used only the approved pinned image:

```text
docker.io/library/postgres:18.4-bookworm@sha256:1961f96e6029a02c3812d7cb329a3b03a3ac2bb067058dec17b0f5596aca9296
```

It created container `medevidence-m1a003b-impl-c7a41d92` with `--pull never`,
synthetic PostgreSQL credentials, `PGDATA=/var/lib/postgresql/18/docker`,
`--tmpfs /var/lib/postgresql:rw,nosuid,nodev`, and
`--publish 127.0.0.1::5432/tcp`. Inspection recorded container ID prefix
`d3135509`, no mounts or volumes, and loopback endpoint `127.0.0.1:62102`.
Kernel `findmnt` confirmed tmpfs, and `pg_isready` succeeded on attempt 2.

With `MEDEV_DATABASE_URL` injected for that disposable database (credentials
and the complete URL intentionally omitted), the integration node executed:

```text
uv run --locked --no-sync pytest tests/integration/persistence -q
```

Historical cycle 1 result: 185 passed in 1.65 seconds. It covered the direct
database matrices and a subset of repository behavior, but independent review
proved it did **not** execute all public repository operations, successful
complete acquisition/run-report registration, replay/lineage validation, or
all 13 exact capacity thresholds. It is retained as historical database
evidence and is not a PASS for the cycle 2 repository candidate.

Cleanup used `docker stop --time 10` (with only Docker's deprecation warning)
and `docker rm` for the exact container. Final inspection found zero matching
containers, zero volumes, and only default Docker networks. No unrelated Docker
resource was changed.

### Cycle 2 remediation database lifecycle

Cycle 2 used container `medevidence-m1a003b-rem2-8e5b3a4c`, container ID
prefix `e5d4015a`, from the same approved pinned PostgreSQL digest above with
`--pull never`. It published only to loopback port `58779`, used tmpfs-backed
database storage with no mounts, and became ready on attempt 2. Credentials and
the complete database URL were not recorded.

The first cycle 2 execution reported 193 passed and 1 failed. The failing
real-repository case proved that a full table capacity guard overrode a
conflicting immutable identity. The bounded correction makes identical content
replay, differing content conflict, and only a new identity raise capacity.
The final rerun in the same disposable-container lifecycle passed **193/193 in
2.17 seconds**.

The exact remediation container was removed. Final inspection found zero
matching containers, zero volumes, and only default Docker networks. No
unrelated Docker resource was changed.

### Cycle 3 remediation database lifecycle

Cycle 3 used container `medevidence-m1a003b-rem3-c3a7d91e`, full container ID
`97a1bf5e33e448fdf2352018a8062bc7a91c8c1afc32b224071fb3da7dbabb26`,
from the exact approved image:

```text
docker.io/library/postgres:18.4-bookworm@sha256:1961f96e6029a02c3812d7cb329a3b03a3ac2bb067058dec17b0f5596aca9296
```

Docker Desktop used the `desktop-linux` context with Linux engine version
29.6.2 and `--pull never`. PostgreSQL used
`PGDATA=/var/lib/postgresql/18/docker`; database storage was tmpfs with
`rw,nosuid,nodev`, and inspection found no mounts. The only published endpoint
was loopback `127.0.0.1:61075`, and readiness succeeded on attempt 1.

The first full run passed 218/219. Its sole failure was the stale rollback-test
fixture described above, not a product defect or frozen-schema failure. After
the authorized mechanical test-only correction, the final full rerun passed
**219/219 in 4.59 seconds with no warnings** in the same container lifecycle.

The exact cycle 3 container was removed. Final inspection found zero
containers, zero volumes, and only the default `bridge`, `host`, and `none`
networks.

### Cycle 4 remediation database lifecycle

Fresh root validation used container `medevidence-m1a003b-rem4-c4b91e2a`,
full container ID
`4d32838225f1eefc9067ec08819b2756ceeba58d69df9d9e6a62831bbe6bd651`,
from the exact approved image:

```text
docker.io/library/postgres:18.4-bookworm@sha256:1961f96e6029a02c3812d7cb329a3b03a3ac2bb067058dec17b0f5596aca9296
```

Docker Desktop used the `desktop-linux` context with Linux engine version
29.6.2 and `--pull never`. PostgreSQL used
`PGDATA=/var/lib/postgresql/18/docker`; database storage was tmpfs with
`rw,nosuid,nodev`, and inspection found no mounts. The only published endpoint
was loopback `127.0.0.1:60305`, and readiness succeeded on attempt 1.

The full persistence integration suite passed **236/236 in 6.02 seconds**. The
exact cycle 4 container was removed. Final inspection found zero containers,
zero volumes, and only the default `bridge`, `host`, and `none` networks.

## Network and Git scope

- No PubMed, NCBI, DailyMed, FAERS, or other medical-source request occurred.
- Package network activity was limited to the Owner-authorized PyPI package
  hosts and the dependency advisory service used by the live audit.
- The later remediation inventory was offline.
- The final cycle 2 inventory's first command was blocked before execution by
  host policy; the established PowerShell `ExecutionPolicy Bypass` invocation
  then completed `Inventory` mode offline. Neither attempt made a package or
  advisory network request.
- The cycle 3 dependency inventory was offline and reported advisory status
  `not_run_offline`; no medical-source access occurred.
- Cycle 4 root validation used only the authorized disposable PostgreSQL
  lifecycle above and the authorized PyPI dependency audit. Network access was
  limited to `pypi.org` and `files.pythonhosted.org` package/advisory metadata;
  no medical-source or Git-remote request occurred.
- Cycle 4 evidence finalization and independent review performed no new Docker,
  database, network, medical-source, or Git operation.
- Cycle 3 performed no Git mutation: no stage, commit, push, merge, rebase,
  reset, clean, branch deletion, or remote-state change.
- The exact staged candidate was committed as
  `7bd41450cb13d9d118c64e8da51de0e10079bc6b` and pushed normally to Draft PR
  `#5`; no force-push, merge, rebase, reset, clean, branch deletion, or history
  rewrite occurred.
- This post-CI evidence-finalization node performed no staging, commit, push,
  Docker, network, or other Git mutation.

## Lifecycle gates and remaining risks

| Gate | State |
|---|---|
| Approved implementation | Owner-authorized cycle 4 traceability remediation implemented locally |
| Focused validation | Cycle 4 PASS: 116 focused tests plus 20 database-independent integration cases |
| Full offline validation | Cycle 4 PASS: 532 tests, one expected warning, 80% coverage; Ruff/format/MyPy/lock PASS |
| Disposable PostgreSQL integration | Cycle 4 PASS: 236/236 in 6.02 seconds; exact container removed and cleanup verified |
| Remediation | Authorized cycle 4 of 4 implemented, locally validated, and independently reviewed |
| Independent actual-diff/executable review | **PASS for exact technical candidate `cceaa47edaddccc81e6a41760fc6b9efc1c2d0311ccc2ac9914e15ca13ed8b0f`; P0 0 / P1 0 / P2 0** |
| Final-byte review and pre-commit terminal evidence audit | **PASS for exact candidate `68391faf3933b8ebc56256d7183adab0f6beeec9c616c44fccd125929c5e8dde`; P0 0 / P1 0 / P2 0; staged identity exact** |
| Local implementation commit | **PASS: `7bd41450cb13d9d118c64e8da51de0e10079bc6b`** |
| Draft PR and hosted CI | **PASS: Draft PR `#5`; compose-config, windows-quality, and dependency-audit jobs passed** |
| Final PR-head review | **PENDING after the evidence commit** |
| Final terminal evidence audit | **PENDING after the evidence commit** |
| Merge and approved-`main` integration | **PENDING** |
| Live medical-source validation | Not authorized; not run |

Remaining risks:

- `psycopg[binary]` is an approved pinned convenience distribution, but its
  production deployment/runtime suitability still requires the later
  deployment-context review; this local slice does not establish a production
  deployment claim.
- The implementation is committed and hosted CI is green, but the Draft PR has
  not completed final PR-head review or post-evidence terminal audit.
- No live medical-source behavior was exercised, by design.
- PR readiness, merge, approved-`main` integration, and `M1A-004` remain
  pending.

## Manual verification

1. Verify the evidence commit changes only the four authorized documentation
   paths.
2. Confirm Draft PR `#5` points at the evidence commit and all three hosted jobs
   remain green.
3. Run final independent review of the resulting PR head.
4. Run the final terminal evidence audit only after the documentation bytes are
   stable.

## Owner interview questions

1. Why does insert-or-verify use a savepoint and named unique-constraint
   reconciliation instead of a SELECT-before-INSERT race claim?
2. Which provenance data belongs in PostgreSQL, and why do raw HTTP response
   bytes remain in immutable file snapshots?
3. How do the deferred run/report closure and separate transactions prevent a
   partially persisted acquisition or report from appearing complete?
