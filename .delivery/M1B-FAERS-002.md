# M1B-FAERS-002 delivery evidence

## Status

`TERMINAL_AUDIT_PASS_AWAITING_FINAL_BYTE_REBIND_AND_GIT`

This record preserves the complete Review001 through Review004 evidence and
the terminal audit PASS after the exhausted `3/3` remediation budget. The
candidate awaits final-byte rebind and the authorized Git lifecycle. It does
not claim commit,
push, pull request, CI, merge, integrated verification,
`M1B-FAERS-002_COMPLETE`, or readiness to execute M1B-FAERS-003.

## Authority and baseline

- Work item: `M1B-FAERS-002`
- Branch: `feat/m1b-faers-002-connector`
- Baseline: `main@0a8b617a23522f30186600948176a458c48aa25f`
- Owner Freeze: audited `M1B Owner Freeze v8`
- Exact Owner artifact:
  `M1B-OWNER-PLANNING-FREEZE-v8-faers-pt-owner-resolution-final-r1.md`
- Owner artifact bytes: `680144`
- Owner artifact SHA-256:
  `1701431e299542d3ef16f29efc45d03c7dae58259385e18ab7273bd64519d372`
- Merged predecessor: ADR-012 / M1B-FAERS-001 at the exact baseline above.
- Remediation limit: default `3`; implementation-local mechanical cycles used:
  `2/3`.

## Implemented candidate

The candidate implements the frozen FAERS_M1B_CONSTRAINED_V1 boundary only:

- a closed serializer for the exact provider-count query grammar, exact
  identity strategy/stratum/provider-field mapping, inclusive `receivedate`
  dates, exact three-PT tuple, count grouping, canonical clause order, and
  exactly-once percent encoding;
- a bounded HTTPS connector with the frozen host/path, zero redirects,
  5/10/5/5-second phase timeouts, 30-second acquisition deadline, two-attempt
  retry policy, 5,242,880-byte response/cumulative ceilings, five-page and
  100-bucket ceilings, typed failure mapping, and no cache or stale fallback;
- synthetic, narrative-free count fixtures and offline connector/parser
  contracts only; no individual report, patient, product, or narrative fixture;
- exact immutable aggregate-response snapshots outside Git, canonical manifest
  identity, exact raw-byte replay, complete ordered bucket retention, manifest,
  query, outcome, snapshot, acquisition, and content-hash ownership checks;
- the approved additive `m1b_faers_queries` and `m1b_faers_buckets` metadata
  tables only, with a self-contained frozen migration chained
  `m1bdm002001 -> m1bfaers002001`;
- a specialized complete-column insert-or-verify repository method that binds
  the trusted typed query/result to its exact snapshot, manifest, SourceOutcome,
  acquisition, canonical PT tuple, bounds, identity stratum, role policy,
  endpoint/unit, and complete count-desc/PT-asc bucket collection; the generic
  M1B repository cannot bypass this comparator;
- a structured FAERS aggregate tool and composition/port contracts that expose
  the frozen aggregate operation without adding an API/report route;
- exact `statistical_unit=provider_count_occurrence`, exact
  `role_policy=unfiltered_provider_roles`, and the mandatory no-incidence,
  no-causality, no-risk, no-ranking, incomplete-GI-set, duplicate/follow-up,
  missing-date, no-role-filter, and provider-update limitations.

Existing M1A and DailyMed behavior is preserved. No new dependency, public API
route, report integration, connector mode, persistence table, migration, live
smoke, or FAERS-003 behavior is included.

## Mechanical remediation history

Implementation-local cycle 1/3 corrected the first disposable PostgreSQL
migration failure. SQLAlchemy textual bind parsing had converted the JSON
colons in `ck_m1b_faers_queries_closed_bounds` into invalid `NULL` tokens. The
SQLAlchemy constraint input now escapes those bind-like colons, the compiled
PostgreSQL DDL retains the exact canonical numeric JSONB literal, the frozen
compressed migration payload was regenerated and hash-bound, and migration
execution uses `exec_driver_sql` so the exact DDL cannot be rewritten as text
parameters. A static upgrade-path regression extracts and parses the JSON and
compares all eight exact numeric values.

Implementation-local cycle 2/3 closed the two same-class manifestations found
by fresh PostgreSQL execution:

- the freeze specifies exactly the two additive unique constraints
  `uq_m1b_faers_queries_binding` and `uq_m1b_faers_buckets_pt`; therefore the
  exact integrated PostgreSQL unique-constraint total is `63`, not `64`. Static
  tests now prove both per-table names instead of relying on the aggregate count;
- `role_predicate_json` is nullable JSONB and the frozen unfiltered-role CHECK
  requires SQL `NULL`. The repository now binds SQL `NULL`, normalizes replay
  comparison to Python `None`, and returns the canonical `None` value instead of
  JSON `null` or a SQLAlchemy expression.

Both corrections preserve the approved schema and frozen semantics.

## Validation evidence

Fresh implementation evidence supplied at this join:

- focused connector policy/parser contracts: `52 passed`;
- focused FAERS tool contract: `44 passed`;
- complete tools selection: `193 passed`;
- joined focused FAERS selection: `266 passed`;
- owned ingestion/persistence/migration selection after final remediation:
  `206 passed`, with `2` local PostgreSQL-only skips because
  `MEDEV_DATABASE_URL` was absent from the ordinary shell;
- fresh disposable PostgreSQL validation after both mechanical corrections:
  `2 passed`; this included upgrade/downgrade/upgrade, exact catalog metadata,
  and immutable FAERS insert/replay/conflict behavior;
- full offline unit and contract suite with sockets disabled and coverage:
  `1371 passed`, two expected warnings, `80%` total coverage;
- `uv run --locked --no-sync ruff check .`: PASS;
- `uv run --locked --no-sync ruff format --check .`: `95 files already formatted`;
- `uv run --locked --no-sync mypy src`: PASS for `45` source files;
- `git diff --check`: PASS;
- migration head: `m1bfaers002001`;
- exact authorized-path comparison: PASS.

The PostgreSQL validation used only the already-present pinned local Docker
image. Docker was invoked with pull disabled; no registry access occurred, and
the disposable runtime was fully removed afterward. Ordinary tests remained
socket-disabled.

## Exact candidate manifest

This manifest deliberately excludes `.delivery/M1B-FAERS-002.md` to avoid a
self-referential identity. It covers exactly the 35 current implementation,
test, migration, and synthetic-fixture paths.

Recipe: combine `git diff --name-only` with
`git ls-files --others --exclude-standard`; exclude this delivery path; convert
paths to POSIX separators; deduplicate; sort with
`[StringComparer]::Ordinal`; emit each row as
`path<TAB>byte_count<TAB>lowercase_file_sha256`; join UTF-8 rows with LF and no
terminal LF; SHA-256 the resulting preimage.

- Manifest rows: `35`
- Manifest preimage bytes: `3887`
- Manifest SHA-256:
  `378eda5dc9b29776484ffb440080e2a263381d7d7f97f01b67d78304f7d0e86e`

```text
alembic/versions/20260809_02_m1b_faers.py	3267	344dea58598dcf9ad792237ae1c6868b8f892293e3d54c844f3eb9a057a75a5a
src/medevidence/composition.py	44354	cdb45ba6d8f09c478d7eeeafb21daedca5d82a1d122199ccdf7834ba3fc35aa4
src/medevidence/connectors/faers/__init__.py	1244	6ca3be19a2d2290c3d818938f08a91cd31cef23a669c01a74921564facbf38c6
src/medevidence/connectors/faers/client.py	21570	e343d67f8683538d84233ea3ad185799f83b710e2eb2e1d561cb1ec5f7e11816
src/medevidence/connectors/faers/parsing.py	10079	102b100ee9ea78efa432fb935c00b866e5877545d8a83dbb1530538f59ea1e55
src/medevidence/connectors/faers/policy.py	13972	df38c4c472bda974de93e622a8706e9b60c93ef3621eda676c262a048c3b1a69
src/medevidence/ingestion/__init__.py	1455	0ca89302b933d07984b9280b2a2ba7bd696d42954d9cee346fe4b0695d276c5c
src/medevidence/ingestion/artifacts.py	45195	bddad2869383a84728ebeb647320161876f07c1d4fc87b2108b80de73a33d124
src/medevidence/ingestion/snapshots.py	23030	91c52f803a1b48320142816b4e0e8f885041200d7091164457d46a044533c167
src/medevidence/persistence/models.py	98347	60ab61b121b53a864da9d01d799c511c7d0581d1ec663dae1deae292474edd16
src/medevidence/persistence/repositories.py	98507	c93689567fd1387b60596383f3db3c718b02999ea8622859e0624b257d22375f
src/medevidence/tools/__init__.py	1612	2bf8db8b0cc51d21ab45717073d338c12d340851b68ef88dfd3f362730cff37c
src/medevidence/tools/contracts.py	23169	bae051d240a88d536d400e2e07a75445f1397efad41944049536b67d34791738
src/medevidence/tools/faers.py	1524	c65a032e863b8480dd53cb5134b1cadeb2b4b4226fe9f35ed1b75524c57f5dbf
src/medevidence/tools/ports.py	17195	a89b382160062226ae2a698001cbd3b3009ab2b78bbb7e5af1d0c8db487e9a15
tests/contract/connectors/test_faers_connector.py	11014	a62f1a51677d861d1f0c9ee7eb375f6c1e4da4f095fb0d16d0fc64a5d6bbc671
tests/contract/tools/test_faers_tools.py	1270	5a7af6cea9e19fb231601899769d5e8a5b01c7185b2eaa05e36f0c6952e93904
tests/fixtures/faers/count-empty.json	67	17539cfec383bca6d01f433db6c73e25a6f1e98768be700034fb5b2d72fa72d0
tests/fixtures/faers/count-single-bucket.json	132	5d3506c4c249047af4689319acb94d4be293ad09da1e662346da670efe5b519e
tests/fixtures/faers/error-429.json	70	9042ea2c56a029021d9ae3a905606d7aff59dd862cb4df3a4f6445e1b69166a0
tests/fixtures/faers/malformed.json	13	933d681330864bdf69b371ef00f4d8257457feb43877639537333148d0cba9ee
tests/fixtures/faers/raw-missing-harmonization.json	43	39d1867a7513805d421a925f1bfe9d24ac2ba0b2d80e91a49493a2d57aa49005
tests/fixtures/faers/raw-multi-version.json	20	055adfea3993bfdfd8171a8a015d9f4bd4424d0f791b3623f0b38d23184957f6
tests/fixtures/faers/raw-repeated-pt-multi-drug.json	36	b4bfce049f2ea360bac0f2536b281453624bc599c2b607e32823d4857add7ca4
tests/fixtures/faers/raw-single-latest.json	17	1df04634d071dc5f9314d638134eca98f91bd58810fbce2389c2c7c09080f9e8
tests/fixtures/faers/raw-truncated-page.json	94	3ae548872a46ff15f78739ac0d091f16bb20fd805788864c6ec9e35665bc9467
tests/fixtures/faers/raw-version-tie.json	70	a53187b6bbcab88fdc39b18b5e9f40b545c057bdec0f54ea2cd0a72d7b1df84f
tests/integration/persistence/test_faers_metadata.py	7793	2d92c12cc3dcf9f692169efcfb168dd01e0b3d603ddaecdab4701c08702529e9
tests/integration/persistence/test_migrations.py	5054	3e2f96e53699bec369de8f3158e90aec52b80e7e7d4055571e3af09d5ae12b9f
tests/unit/connectors/test_faers_parsing.py	3706	1d0fb8d78c462b81ed317566eb42d2daee4de31757e82f898306eb0d6308588c
tests/unit/connectors/test_faers_policy.py	6559	08eb12739b7dc4d163b2ca874ed1691bc8d0b9f5ee48c9266cd3d5757cf37fa7
tests/unit/ingestion/test_artifacts.py	47069	ddf521a7e3fe973a8b15492205e832e030d8f27ecaa07dbd9bec2a89c42f6560
tests/unit/ingestion/test_snapshots.py	10736	5208b4b2460f03020e7d39fc56f0f3eb3a77fe47b85eb86ed649e0143d9582d0
tests/unit/persistence/test_metadata.py	28222	6e37fa194fc7f6cb18ceaaf8b047f0ccc383ffb9dc53af0ce853ea16260b0c11
tests/unit/tools/test_faers.py	13830	059c9e28c52f7033e06b37f18165e0e5af1773bd24cf3cc20d3e91b1dd9935a6
```

## Independent Review001

Final verdict: `FAIL — P0 0 / P1 2 / P2 1`.

The review is bound to the exact 35-row, 3,887-byte manifest with SHA-256
`378eda5dc9b29776484ffb440080e2a263381d7d7f97f01b67d78304f7d0e86e`.
It identified three implementation-local findings:

1. P1: the untrusted JSON parser accepts duplicate keys, allows integers beyond
   PostgreSQL `bigint`, and can let raw numeric-conversion `ValueError` escape
   typed connector failure handling;
2. P1: FAERS snapshot capture accepts repeated artifact/content membership that
   the frozen unique snapshot-membership constraint cannot persist; and
3. P2: HTTP 401 and 403 collapse into generic `CLIENT_ERROR` instead of the
   required typed authentication or authorization failure distinction.

The exact reproductions and acceptance criteria are preserved in
`docs/reviews/M1B-FAERS-002-INDEPENDENT-REVIEW-001.md`. A provisional
`final_url` checkpoint was sent after Review001 for same-class remediation
closure, but it was not part of the reviewed candidate and is not counted in
the final Review001 verdict.

## Network, infrastructure, dependencies, and Git

- FAERS/openFDA requests: `0`.
- Other medical-source/provider requests: `0`.
- External network requests: `0`.
- Synthetic fixtures contain no patient narrative, individual report,
  production export, real provider result, or protected health information.
- Dependency changes: none.
- API/report route changes: none.
- Docker: existing pinned local PostgreSQL image only; `--pull never`; no
  registry access; disposable container, volume, and network fully removed.
- Git operations after branch creation: no stage, commit, push, PR, CI, ready,
  merge, fetch, pull, or local-main integration.
- M1B-FAERS-003: not started.

## Remaining gates and risk

Review001 and Review002 findings are remediated. The candidate requires a fresh
complete Review003 of the entire new candidate with `P0/P1/P2 = 0/0/0`. Only
then may terminal evidence audit and the already-authorized Git lifecycle
proceed. The two PostgreSQL defects
above remain preserved as mechanical failure-and-correction history; their
final fresh PostgreSQL rerun passed.

Manual verification: recompute the current manifest with the recipe above; run
the joined focused selection and full offline socket-disabled suite; run the
disposable PostgreSQL migration/catalog and FAERS metadata tests using the
existing pinned image with pull disabled; then compare the actual diff against
K.5 before review.

Owner technical-defense questions:

1. Why must `role_predicate_json` be SQL `NULL` rather than JSON `null` for the
   unfiltered-role contract?
2. Why does the specialized repository compare the complete ordered bucket
   collection instead of accepting individually valid bucket rows?
3. Why is `provider_count_occurrence` not a patient, case, incidence, risk, or
   deduplicated provider-report count?

## Post-Review001 remediation join

The historical Review001 verdict remains `FAIL — P0 0 / P1 2 / P2 1`. The
following implementation-local corrections have fresh validation and are
submitted to Review002:

- strict duplicate-name rejection at every JSON object depth, complete typed
  translation of JSON and numeric-conversion failures, and exact nonnegative
  PostgreSQL `bigint` admission;
- typed connector-level malformed-response behavior for duplicate and
  oversized/overflow numeric input;
- non-retryable typed `AUTHENTICATION_OR_AUTHORIZATION` mapping for HTTP 401
  and 403 while retaining the other closed permanent status classes;
- exact `final_url` validation against the frozen request URL and origin before
  retained response evidence can become authoritative;
- duplicate FAERS artifact/content membership rejection during manifest
  validation and capture preflight, before any file publication;
- duplicate-member replay rejection and PostgreSQL unique-membership parity
  coverage.

Fresh root evidence:

- focused joined validation: `281 passed`;
- disposable PostgreSQL migration and metadata validation: `3 passed`;
- full offline socket-disabled suite: `1386 passed`, two expected warnings,
  `80%` coverage;
- Ruff: PASS;
- format: PASS, `95` files;
- MyPy: PASS, `45` source files;
- `git diff --check`: PASS;
- exact authorized-path comparison: PASS.

PostgreSQL used only the pinned local image with pull disabled; the disposable
container, volume, and network were removed afterward. FAERS/openFDA,
medical-source, and other external network requests remained `0`.

### Post-remediation candidate manifest

The canonical manifest excludes this delivery record to avoid self-reference
and includes the historical Review001 record. Paths are POSIX-normalized,
deduplicated, ordinal-sorted, and encoded as
`path<TAB>byte_count<TAB>lowercase_sha256`, joined with LF and no terminal LF.

- rows: `36`;
- preimage bytes: `4010`;
- SHA-256:
  `64242d12b0d74c2323109ad21f82c8c14efc23a47f66115a7a90a257332cdc0a`.

Review002 must review the complete new candidate and independently require
`P0/P1/P2 = 0/0/0`. Terminal audit and Git lifecycle remain prohibited until
that gate passes.

## Independent Review002

Final verdict: `FAIL — P0 0 / P1 3 / P2 1`.

Review002 was bound to the post-Review001 candidate manifest of `36` rows,
`4010` bytes, and SHA-256
`64242d12b0d74c2323109ad21f82c8c14efc23a47f66115a7a90a257332cdc0a`.
It independently confirmed all Review001 findings closed, then found:

1. P1: provider total metadata such as `total=1000` causes an otherwise valid
   one-bucket `NAUSEA` closed projection to reject even though the nonnegative
   provider record total is independent of returned PT bucket cardinality;
2. P1: a retained prefix followed by `ReadTimeout` terminates after one request
   as `TRANSPORT` instead of retaining an incomplete `read_timeout` member and
   exercising the frozen two-attempt retry path;
3. P1: manifests with three-to-five response members, or more members than
   `attempts_used`, plus impossible continuation after a terminal complete 2xx,
   are accepted despite the two-attempt lineage ceiling; and
4. P2: naive or non-`datetime` injected clock values escape as raw exceptions
   after transport instead of preflight `INTEGRITY_FAILURE` with zero requests.

The combined review record preserves each exact reproduction and acceptance
criterion. Review002 independently ran `270 passed, 3 skipped` focused checks,
the full offline suite at `1386 passed` with two expected warnings and `80%`
coverage, Ruff, format across `95` files, MyPy across `45` source files, and
`git diff --check`; all tooling gates passed despite the reproduced defects.
Medical-source and other external network requests were `0`; the reviewer made
no filesystem or Git writes.

All four Review002 findings require remediation followed by a fresh complete
review of the entire candidate. Terminal audit and Git lifecycle remain
prohibited.

## Post-Review002 remediation join

The historical Review002 verdict remains `FAIL — P0 0 / P1 3 / P2 1`. Its
four findings have the following fresh implementation-local closures:

- provider record-total metadata is independent of the exact returned PT
  bucket cardinality, with signed-`bigint` boundaries and typed invalid-total
  handling;
- streamed `ReadTimeout` retains an incomplete prefix and follows the frozen
  bounded timeout retry/exhaustion semantics, while ordinary `ReadError`
  remains non-retryable transport failure;
- snapshot member cardinality now matches the two-attempt ceiling and
  `attempts_used`, with no response allowed after a terminal complete 2xx, and
  the same rules enforced during preflight, replay, and PostgreSQL parity;
- invalid injected clock values fail as typed `INTEGRITY_FAILURE` before any
  request or retained response.

Fresh root evidence:

- focused joined validation: `295 passed`;
- disposable PostgreSQL validation: `3 passed`;
- full offline socket-disabled suite: `1400 passed`, two expected warnings,
  `80%` coverage;
- Ruff: PASS;
- format: PASS, `95` files;
- MyPy: PASS, `45` source files;
- `git diff --check`: PASS;
- exact authorized-path comparison: PASS.

PostgreSQL used only the pinned local image with pull disabled; its disposable
container, volume, and network were removed afterward. Medical-source and
other external network requests remained `0`.

Review003 must inspect the complete remediated candidate and independently
require `P0/P1/P2 = 0/0/0`. Terminal audit and Git lifecycle remain prohibited
until that gate passes.

### Post-Review002 candidate manifest

The canonical manifest excludes this delivery record to avoid self-reference
and includes the complete combined Review001/Review002 record. Paths are
POSIX-normalized, deduplicated, ordinal-sorted, and encoded as
`path<TAB>byte_count<TAB>lowercase_sha256`, joined with LF and no terminal LF.

- rows: `36`;
- preimage bytes: `4012`;
- SHA-256:
  `ee646bb87607af4791c164a1d28ca6668f34c4187e3138d7f49d7c5a83d3ef02`.

## Independent Review003

Final verdict: `FAIL — P0 0 / P1 1 / P2 1`.

Review003 was bound to the 36-row, 4,012-byte candidate manifest with SHA-256
`ee646bb87607af4791c164a1d28ca6668f34c4187e3138d7f49d7c5a83d3ef02`.
It independently confirmed all Review001 and Review002 findings closed, then
found:

1. P1: connector retry evidence is not snapshot-representable because
   `read_timeout` is absent from the ingestion termination contract and member
   admissibility omits HTTP 408 and the complete frozen 5xx retry class; and
2. P2: invalid, non-finite, exception-raising, or rewinding monotonic-clock
   values can escape typed handling or increase the remaining deadline budget.

The combined review record preserves both exact reproductions and acceptance
criteria. Review003 independently ran `284 passed, 3 skipped` focused checks,
the full offline suite at `1400 passed` with two expected warnings and `80%`
coverage, Ruff, format across `95` files, MyPy across `45` source files, and
`git diff --check`; all tooling gates passed despite the reproduced defects.
Medical-source and other external network requests were `0`; the reviewer made
no filesystem or Git writes.

Both findings require the final bounded remediation followed by a fresh
complete review of the entire candidate. Terminal audit and Git lifecycle
remain prohibited.

## Post-Review003 final remediation join

The historical Review003 verdict remains `FAIL — P0 0 / P1 1 / P2 1`. Its two
findings have the following final implementation-local closures:

- exact incomplete `read_timeout` evidence and retained HTTP 408, 429, and all
  frozen retryable 5xx attempts are representable across connector mapping,
  snapshot capture, canonical manifest, replay, and PostgreSQL parity without
  becoming authoritative results;
- monotonic samples are finite, numeric, non-Boolean, and nondecreasing;
  invalid, exceptional, NaN, infinite, and rewinding samples fail through the
  typed integrity boundary without deadline extension or bypass.

Fresh root evidence:

- focused joined validation: `319 passed`;
- disposable PostgreSQL validation: `3 passed`;
- full offline socket-disabled suite: `1424 passed`, two expected warnings,
  `80%` coverage;
- Ruff: PASS;
- format: PASS, `95` files;
- MyPy: PASS, `45` source files;
- `git diff --check`: PASS;
- exact authorized-path comparison: PASS.

PostgreSQL used only the pinned local image with pull disabled; its disposable
container, volume, and network were removed afterward. Medical-source and
other external network requests remained `0`. The authorized remediation
budget is exhausted at `3/3`.

Review004 must inspect the complete final candidate and independently require
`P0/P1/P2 = 0/0/0`. Any Review004 finding requires Owner action; terminal audit
and Git lifecycle remain prohibited until a zero-finding PASS.

### Final remediation candidate manifest

The canonical manifest excludes this delivery record to avoid self-reference
and includes the complete combined review record. Paths are POSIX-normalized,
deduplicated, ordinal-sorted, and encoded as
`path<TAB>byte_count<TAB>lowercase_sha256`, joined with LF and no terminal LF.

- rows: `36`;
- preimage bytes: `4012`;
- SHA-256:
  `a57c4faba7553e9fc741fb127fd746eb86fad40e5b478e0c1ab055ea14f2b3d5`.

## Independent Review004

Final verdict: `PASS — P0 0 / P1 0 / P2 0`.

Review004 was bound to the 36-row, 4,012-byte candidate manifest with SHA-256
`a57c4faba7553e9fc741fb127fd746eb86fad40e5b478e0c1ab055ea14f2b3d5`.
It inspected the complete final candidate, confirmed every Review001,
Review002, and Review003 finding closed, and found no additional P0/P1/P2
defect.

Independent evidence:

- focused candidate validation: `308 passed, 3 skipped`;
- full offline socket-disabled suite: `1424 passed`, two expected warnings,
  `80%` coverage;
- Ruff: PASS;
- format: PASS, `95` files;
- MyPy: PASS, `45` source files;
- `git diff --check`: PASS;
- exact authorized-path and dependency-boundary checks: PASS.

FAERS/openFDA, medical-source, and other external network request counts were
`0`. No new dependency, API/report route, FAERS-003 behavior, real provider
fixture, patient narrative, or unapproved persistence scope was added. The
reviewer performed no filesystem or Git write.

The next gate is the independent terminal evidence audit. This Review004 PASS
does not claim audit PASS or authorize a completion statement before that gate;
no commit, push, PR, CI, merge, or integrated verification is yet recorded.

## Terminal evidence audit

Verdict: `PASS — P0 0 / P1 0 / P2 0`.

The independent terminal auditor inspected the complete current candidate,
including the combined review record and the pre-audit delivery record. Its
exact candidate binding was:

- full manifest rows: `37`;
- full manifest preimage bytes: `4110`;
- full manifest SHA-256:
  `df2a4537d5dce6db81e19cf136d5e8d06c56977b8c18be1a4da74064dc375f17`;
- pre-audit delivery bytes: `24182`;
- pre-audit delivery SHA-256:
  `28c81a27b622b945f1618ce32f68b1eb198908c19fbe6042cd5f9f908040f345`;
- combined review bytes: `22030`;
- combined review SHA-256:
  `dbde2ffb95781e942090d1ca80857e8c938a0314634df491975c01c802e045c8`.

Terminal-audit evidence:

- Review004 independently passed at `P0/P1/P2 = 0/0/0`;
- focused candidate validation: `308 passed, 3 skipped`;
- full offline socket-disabled suite: `1424 passed`;
- Ruff: PASS;
- format: PASS, `95` files;
- MyPy: PASS, `45` source files;
- `git diff --check`: PASS;
- exact PostgreSQL migration chain and prior fresh disposable PostgreSQL
  validation: PASS, `3 passed`;
- exact K.5 authorized-path comparison: PASS for all `37` candidate paths;
- dependency and architecture boundaries: PASS;
- FAERS/openFDA, medical-source, and other external network requests: `0`;
- no new dependency, API/report route, FAERS-003 behavior, real provider data,
  patient narrative, PHI, or unapproved path was introduced.

The auditor found no unsupported completion, review, validation, scope,
network, or Git claim. This persisted audit decision does not itself claim a
commit, push, PR, CI, merge, integrated verification, completion, or
FAERS-003 readiness. Final-byte rebind and the authorized Git lifecycle remain
required.

## Post-audit current-byte rebind

After persisting the terminal-audit decision in this authorized delivery
record, the current full candidate is rebound as follows:

- current full manifest rows: `37`;
- current full manifest preimage bytes: `4110`;
- current full manifest SHA-256:
  `95a8572ad6a1155ab037a30a8e87190a88a6f0cc1bb407a06e6d463f29bf0b3f`;
- current combined review bytes: `22030`;
- current combined review SHA-256:
  `dbde2ffb95781e942090d1ca80857e8c938a0314634df491975c01c802e045c8`;
- current delivery bytes before this current-byte paragraph: `25922`;
- current delivery SHA-256 before this current-byte paragraph:
  `93ff90851ee5dccb3ace8a96021cabceeff776e77dc5535b3ace4ac872cc19b8`.

This mechanical post-audit evidence append changes only the delivery record;
the terminal-audited implementation, tests, migration, fixtures, and review
bytes remain unchanged. A final exact delivery identity is computed externally
after this non-self-referential checkpoint. No Git operation or completion
claim is made here.
