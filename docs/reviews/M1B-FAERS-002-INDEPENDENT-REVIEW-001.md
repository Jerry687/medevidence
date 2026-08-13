# M1B-FAERS-002 Independent Review 001

## Verdict

`FAIL — P0 0 / P1 2 / P2 1`

This is the final Review001 verdict for the exact candidate below. It does not
authorize terminal audit, commit, push, pull request, CI, merge, completion, or
M1B-FAERS-003 work. A provisional `final_url` checkpoint was sent after this
review for same-class remediation closure, but it was not part of the reviewed
candidate and is not counted in this verdict.

## Candidate binding

- Branch: `feat/m1b-faers-002-connector`
- Baseline, HEAD, and merge-base:
  `0a8b617a23522f30186600948176a458c48aa25f`
- Owner Freeze bytes: `680144`
- Owner Freeze SHA-256:
  `1701431e299542d3ef16f29efc45d03c7dae58259385e18ab7273bd64519d372`
- Reviewed candidate manifest rows: `35`
- Reviewed manifest preimage bytes: `3887`
- Reviewed manifest SHA-256:
  `378eda5dc9b29776484ffb440080e2a263381d7d7f97f01b67d78304f7d0e86e`
- Scope review: every reviewed path was authorized by K.5. No API, report,
  FAERS-003, dependency, or denied-path drift was found.

## Findings

### P1-01 — Untrusted JSON parsing is not closed

Files and symbols:

- `src/medevidence/connectors/faers/parsing.py::_json_object`
- `src/medevidence/connectors/faers/parsing.py::parse_count_page`
- `src/medevidence/connectors/faers/client.py::FaersConnector.aggregate`

Reproduction and evidence:

- `_json_object` uses ordinary `json.loads` without duplicate-key rejection.
- The payload
  `{"results":[{"term":"UNKNOWN","term":"NAUSEA","count":1}]}` is accepted
  as a valid `NAUSEA=1` bucket because the latter duplicate silently wins.
- A 5,000-digit count raises raw `ValueError` from Python's integer digit
  ceiling. `aggregate()` catches only `FaersParseError`, so the connector
  escapes its typed failure boundary.
- A count such as `10**100` is accepted even though persistence uses PostgreSQL
  `bigint`, deferring a predictable integrity failure beyond the parser trust
  boundary.

Acceptance criteria:

- Use a strict duplicate-key-rejecting JSON decoder.
- Translate every decode and numeric-conversion exception to `FaersParseError`.
- Enforce the approved nonnegative PostgreSQL-bigint range before bucket
  construction.
- Add duplicate root, metadata, bucket, and error-key tests plus oversized
  integer and exact overflow-boundary tests that prove connector-level typed
  failure.

### P1-02 — Snapshot capture accepts unpersistable duplicate membership

Files and symbols:

- `src/medevidence/ingestion/artifacts.py::FaersSnapshotManifest.validate_manifest`
- `src/medevidence/ingestion/artifacts.py::capture_faers_snapshot`
- frozen constraint
  `m1b_snapshot_artifacts.uq_m1b_snapshot_artifacts_membership`

Reproduction and evidence:

- The manifest checks unique `link_id` but does not require unique
  `artifact_id` or `content_hash`.
- Two retry observations containing identical exact bodies are accepted as two
  members that resolve to the same content-addressed file.
- The frozen schema requires artifact identity uniqueness within
  `(run, source, acquisition, snapshot)`; the accepted manifest therefore
  cannot be registered as the exact durable snapshot graph.

Acceptance criteria:

- Fail closed before publication when artifact or content identities repeat,
  or use the exact already-frozen representation satisfying the uniqueness
  constraint.
- Add identical retry-response, duplicate-member replay, and
  persistence-parity negative tests.
- Preserve attempt and retry evidence without inventing a new schema semantic.

### P2-01 — Authentication and authorization failures are not distinguished

Files and symbols:

- `src/medevidence/connectors/faers/policy.py::FaersFailureKind`
- `src/medevidence/connectors/faers/client.py::_send_once`

Reproduction and evidence:

- HTTP 401 and 403 are both returned as generic `CLIENT_ERROR`.
- The connector policy requires authentication or authorization failure to be
  distinguishable from invalid request and other permanent client failures.
- Existing tests explicitly assert the collapsed classification.

Acceptance criteria:

- Add the already-required typed authentication or authorization
  classification and map 401 and 403 to it without retry.
- Keep 400, 404, and 422 in their appropriate permanent invalid or unsupported
  classes.
- Add exact status-classification tests.

## Independent validation

- Focused FAERS unit and contract selection: `85 passed`.
- Focused ingestion and persistence selection: `170 passed, 2 skipped`.
- Full offline socket-disabled suite: `1371 passed`, `80%` coverage.
- Ruff: PASS.
- Format: PASS, `95` files.
- MyPy: PASS, `45` source files.
- `git diff --check`: PASS.
- PostgreSQL was not rerun independently because `MEDEV_DATABASE_URL` was
  absent; both selected tests skipped. Prior delivery PostgreSQL evidence was
  inspected but was not treated as a fresh reviewer run.
- Medical-source requests: `0`.
- Other network requests: `0`.
- Reviewer Git or filesystem writes: `0`.

## Required next gate

Remediate all three findings within the frozen scope and remaining budget, run
the complete applicable validation, and perform a fresh independent review of
the entire new candidate. Acceptance requires fresh `P0/P1/P2 = 0/0/0`; a
finding-only spot check is insufficient.

## Post-Review001 remediation evidence

Historical verdict and findings above remain unchanged. The bounded
implementation-local remediation has now been validated and awaits a fresh
complete Review002; this section is not a retroactive Review001 PASS.

Remediation closure supplied at the implementation join:

- P1-01: the FAERS JSON decoder now rejects duplicate names at every object
  depth, maps decoding and numeric-conversion failures to `FaersParseError`,
  accepts only the exact nonnegative signed PostgreSQL `bigint` range, and
  proves connector-level typed malformed-response handling. Exact retained
  response admission also validates `final_url` against the frozen request
  origin and URL before evidence is accepted.
- P1-02: FAERS manifest validation and capture preflight now reject duplicate
  artifact and content identities before publication. Replay rejects duplicate
  membership, and PostgreSQL parity coverage proves the frozen unique
  membership constraint remains enforceable.
- P2-01: HTTP 401 and 403 now map without retry to the typed
  `AUTHENTICATION_OR_AUTHORIZATION` failure; other permanent client statuses
  retain their closed classifications.

Fresh root validation after remediation:

- joined focused validation: `281 passed`;
- disposable PostgreSQL migration, metadata, immutable replay, and conflict
  validation: `3 passed`;
- full offline socket-disabled suite: `1386 passed`, two expected warnings,
  `80%` coverage;
- Ruff: PASS;
- format: PASS, `95` files;
- MyPy: PASS, `45` source files;
- `git diff --check`: PASS;
- exact authorized-path comparison: PASS.

The PostgreSQL run used only the pinned local image with pull disabled. Its
disposable container, volume, and network were removed afterward. Medical and
other external network requests remained `0`. No terminal audit or Git
lifecycle operation is claimed.

## Independent Review002

### Verdict

`FAIL — P0 0 / P1 3 / P2 1`

Review002 independently confirmed that all three Review001 findings were
closed. It then reviewed the complete remediated candidate and found the four
additional defects below. This verdict is bound to the 36-row, 4,010-byte
candidate manifest with SHA-256
`64242d12b0d74c2323109ad21f82c8c14efc23a47f66115a7a90a257332cdc0a`.

### P1-01 — Count-envelope total semantics reject a valid bounded projection

Files and symbols:

- `src/medevidence/connectors/faers/parsing.py::FaersCountPage`
- `src/medevidence/connectors/faers/parsing.py::parse_count_page`

Reproduction and evidence:

- A syntactically valid count response with provider `total=1000` and one
  returned `NAUSEA` bucket is rejected solely because total is required to be
  at most 100 and equal the retained collection length.
- `meta.results.total` is bounded nonnegative provider record-total metadata
  independent of the returned closed PT bucket cardinality; it must not
  redefine or invalidate the frozen complete three-PT projection.

Acceptance criteria:

- Accept totals `101`, `1000000`, and signed-`bigint` maximum while an otherwise
  complete exact one-bucket projection remains complete with no next page.
- Keep the returned bucket collection at most 100, exact-PT-only, unique,
  canonically ordered, and complete for the closed query.
- Reject negative, Boolean, signed-`bigint` maximum-plus-one, and huge-digit
  totals through typed malformed-response handling.

### P1-02 — ReadTimeout after a retained prefix is not retried

Files and symbols:

- `src/medevidence/connectors/faers/client.py::_read_body`
- `src/medevidence/connectors/faers/client.py::_send_once`
- `src/medevidence/connectors/faers/client.py::_send_with_retries`

Reproduction and evidence:

- A response stream that yields a retained prefix and then raises
  `httpx.ReadTimeout` produces only one request and terminates as `TRANSPORT`.
- The frozen policy classifies read timeout as retryable within the two-attempt
  and 30-second budgets, including when an incomplete prefix is retained.

Acceptance criteria:

- Classify an in-stream `ReadTimeout` as the typed retryable timeout class and
  retain each exact prefix with `body_complete=false` and
  `termination_reason=read_timeout`.
- Retry once under the two-attempt/deadline bounds, emit one `TIMEOUT` retry
  event, and after a second timeout return `RETRY_EXHAUSTED` with cause
  `TIMEOUT`, `request_count=2`, and no complete or no-match evidence.
- Preserve ordinary `ReadError` as non-retryable `TRANSPORT` with one request.

### P1-03 — Snapshot member cardinality can contradict attempt lineage

Files and symbols:

- `src/medevidence/ingestion/artifacts.py::FaersSnapshotManifest.validate_manifest`
- `src/medevidence/ingestion/artifacts.py::capture_faers_snapshot`

Reproduction and evidence:

- Manifests containing three through five response members are accepted even
  though the frozen acquisition permits at most two attempts.
- A manifest is also accepted when its member count exceeds `attempts_used`.
- The current shape can also represent a continued response after an earlier
  terminal complete 2xx member.
- Such states cannot represent truthful retained-response-to-attempt lineage.

Acceptance criteria:

- Enforce the frozen maximum of two retained response members and require
  member cardinality to be consistent with `attempts_used`.
- Reject capture and replay for three-to-five members and for
  `len(members) > attempts_used`, and reject any member after a terminal
  complete 2xx response, before publication or durable acceptance.
- Preserve valid one-member/one-attempt, one-member/two-attempt pre-response
  failure, two-member/two-attempt retry, and zero-member unavailable shapes
  without inventing new lineage fields.

### P2-01 — Invalid injected clock values escape typed connector handling

Files and symbols:

- `src/medevidence/connectors/faers/client.py::FaersConnector._require_utc`
- connector operations using the injected `utc_now` clock

Reproduction and evidence:

- A naive `datetime` or a non-`datetime` value returned by the injected clock
  raises a raw exception rather than a typed connector contract or integrity
  failure.

Acceptance criteria:

- Validate the injected clock result before transport or timestamp use and
  translate naive `datetime`, string, `None`, non-UTC, and other non-`datetime`
  results to `INTEGRITY_FAILURE` with `request_count=0`, no raw responses, and
  no exception escape.
- Do not accept or normalize invalid timestamps.
- Add exact naive and non-`datetime` clock tests proving no raw exception
  escapes.

### Review002 validation and boundaries

- Focused candidate validation: `270 passed, 3 skipped`.
- Full offline socket-disabled suite: `1386 passed`, two expected warnings,
  `80%` coverage.
- Ruff: PASS.
- Format: PASS, `95` files.
- MyPy: PASS, `45` source files.
- `git diff --check`: PASS.
- Review001 findings: independently confirmed closed.
- Medical-source requests: `0`.
- Other external network requests: `0`.
- Reviewer writes and Git operations: `0`.

All four Review002 findings require bounded remediation and fresh complete
independent review. Terminal audit and Git lifecycle remain prohibited.

## Post-Review002 remediation evidence

The historical Review002 verdict and findings remain unchanged. The bounded
remediation is implementation-validated and awaits a fresh complete Review003;
this section is not a retroactive Review002 PASS.

Remediation closure supplied at the implementation join:

- P1-01: provider record-total metadata is now parsed independently from the
  returned closed PT bucket cardinality. Large valid nonnegative totals through
  signed-`bigint` maximum preserve a complete bounded projection, while
  negative, Boolean, maximum-plus-one, and huge-digit totals fail through the
  typed malformed-response boundary.
- P1-02: an in-stream `ReadTimeout` now retains the exact incomplete prefix,
  records `body_complete=false` with the timeout termination, consumes the
  single bounded retry when deadline permits, and on repetition returns typed
  `RETRY_EXHAUSTED` caused by `TIMEOUT`. Ordinary `ReadError` remains a
  non-retryable transport failure.
- P1-03: FAERS snapshot manifests now admit at most two members, require member
  count not to exceed `attempts_used`, reject continuation after a terminal
  complete 2xx member, and apply those checks during capture preflight, replay,
  and PostgreSQL parity validation. Valid one-member/one-attempt,
  one-member/two-attempt, two-member/two-attempt, and unavailable shapes remain
  accepted.
- P2-01: injected clock values are validated before transport; naive, non-UTC,
  string, `None`, and other non-`datetime` values become typed
  `INTEGRITY_FAILURE` with zero requests and no retained responses.

Fresh root validation after remediation:

- joined focused validation: `295 passed`;
- disposable PostgreSQL migration, metadata, replay, and conflict validation:
  `3 passed`;
- full offline socket-disabled suite: `1400 passed`, two expected warnings,
  `80%` coverage;
- Ruff: PASS;
- format: PASS, `95` files;
- MyPy: PASS, `45` source files;
- `git diff --check`: PASS;
- exact authorized-path comparison: PASS.

PostgreSQL used only the pinned local image with pull disabled. Its disposable
container, volume, and network were removed afterward. Medical-source and
other external network requests remained `0`. No terminal audit or Git
lifecycle operation is claimed.

## Independent Review003

### Verdict

`FAIL — P0 0 / P1 1 / P2 1`

Review003 independently confirmed the Review001 and Review002 findings closed,
then reviewed the complete remediated candidate and found the two defects
below. This verdict is bound to the 36-row, 4,012-byte candidate manifest with
SHA-256
`ee646bb87607af4791c164a1d28ca6668f34c4187e3138d7f49d7c5a83d3ef02`.

### P1-01 — Connector retry evidence cannot be represented by the snapshot contract

Files and symbols:

- `src/medevidence/connectors/faers/client.py` retained response termination
  mapping;
- `src/medevidence/ingestion/artifacts.py::RawResponseObservation` and
  `FaersSnapshotManifest.validate_manifest` response admissibility.

Reproduction and evidence:

- The remediated connector retains an incomplete streamed-timeout response
  with `termination_reason=read_timeout`, but the ingestion snapshot contract
  does not admit `read_timeout`; exact connector evidence therefore cannot be
  captured or replayed.
- Snapshot member admissibility also omits HTTP 408 and the complete frozen 5xx
  retryable class, so valid retained retry-attempt responses cannot be
  represented consistently across connector, manifest, replay, and
  persistence.

Acceptance criteria:

- Extend the existing frozen termination/admissibility representation only as
  mechanically required to retain `read_timeout`, HTTP 408, and every frozen
  retryable 5xx attempt without changing their non-authoritative semantics.
- Require such retry members to remain incomplete or non-terminal as
  appropriate; they must never establish complete coverage, no-match, or
  authoritative buckets.
- Add connector-to-observation, capture-preflight, manifest/replay, and
  PostgreSQL-parity tests for read timeout, 408, and representative/all 5xx
  status handling.

### P2-01 — Invalid monotonic clocks escape or bypass the deadline

Files and symbols:

- `src/medevidence/connectors/faers/client.py` monotonic clock reads and
  remaining-deadline calculation.

Reproduction and evidence:

- Non-numeric, Boolean, non-finite, or exception-raising injected monotonic
  values can escape as raw exceptions.
- A clock that rewinds can increase the calculated remaining budget and bypass
  the frozen 30-second deadline.

Acceptance criteria:

- Validate every monotonic sample as finite, numeric, non-Boolean, and
  nondecreasing from the previous accepted sample.
- Translate invalid values, clock exceptions, and rewind into the existing
  typed fail-closed integrity boundary without a raw exception escape or
  additional request.
- Prove the deadline cannot increase or be bypassed, including invalid initial
  sample, invalid later sample, NaN, infinity, Boolean, exception, and rewind
  adversarial tests.

### Review003 validation and boundaries

- Focused candidate validation: `284 passed, 3 skipped`.
- Full offline socket-disabled suite: `1400 passed`, two expected warnings,
  `80%` coverage.
- Ruff: PASS.
- Format: PASS, `95` files.
- MyPy: PASS, `45` source files.
- `git diff --check`: PASS.
- Review001 and Review002 findings: independently confirmed closed.
- Medical-source requests: `0`.
- Other external network requests: `0`.
- Reviewer writes and Git operations: `0`.

Both Review003 findings require the final bounded remediation and a fresh
complete independent review. Terminal audit and Git lifecycle remain
prohibited.

## Post-Review003 final remediation evidence

The historical Review003 verdict and findings remain unchanged. The final
authorized remediation cycle is implementation-validated and awaits a fresh
complete Review004; this section is not a retroactive Review003 PASS.

Final remediation closure supplied at the implementation join:

- P1-01: `read_timeout` is now an exact admitted incomplete termination across
  connector observation mapping, snapshot capture preflight, canonical
  manifest, replay, and persistence parity. Retained retry-attempt responses
  for HTTP 408, 429, and the complete frozen 5xx class are representable with
  non-authoritative retry semantics and cannot establish complete coverage,
  no-match, or authoritative buckets.
- P2-01: every monotonic sample is now validated as finite, numeric,
  non-Boolean, and nondecreasing. Invalid initial or later samples, NaN,
  infinity, exceptions, and rewind fail through the typed integrity boundary;
  remaining deadline cannot increase or bypass the frozen 30-second ceiling.

Fresh root validation after final remediation:

- joined focused validation: `319 passed`;
- disposable PostgreSQL migration, snapshot-parity, replay, and conflict
  validation: `3 passed`;
- full offline socket-disabled suite: `1424 passed`, two expected warnings,
  `80%` coverage;
- Ruff: PASS;
- format: PASS, `95` files;
- MyPy: PASS, `45` source files;
- `git diff --check`: PASS;
- exact authorized-path comparison: PASS.

PostgreSQL used only the pinned local image with pull disabled. Its disposable
container, volume, and network were removed afterward. Medical-source and
other external network requests remained `0`. The remediation budget is now
exhausted at `3/3`; any Review004 P0/P1/P2 finding must stop for Owner action.
No terminal audit or Git lifecycle operation is claimed.

## Independent Review004

### Verdict

`PASS — P0 0 / P1 0 / P2 0`

Review004 inspected the complete final candidate after all three authorized
remediation cycles. It independently confirmed the Review001, Review002, and
Review003 findings closed and found no additional P0, P1, or P2 defects.

Candidate binding:

- branch: `feat/m1b-faers-002-connector`;
- baseline and merge-base:
  `0a8b617a23522f30186600948176a458c48aa25f`;
- manifest rows: `36`;
- manifest preimage bytes: `4012`;
- manifest SHA-256:
  `a57c4faba7553e9fc741fb127fd746eb86fad40e5b478e0c1ab055ea14f2b3d5`.

Review closure:

- Review001 strict JSON, integer range, duplicate snapshot membership, typed
  authentication/authorization, and final-URL integrity findings: closed.
- Review002 provider-total semantics, streamed timeout retry, member/attempt
  lineage, and injected UTC-clock findings: closed.
- Review003 retry-evidence snapshot/DB parity and monotonic-clock/deadline
  findings: closed.
- Frozen PT tuple, `provider_count_occurrence`, unfiltered provider roles,
  inclusive `receivedate`, 30/60-second limits, exact query identity,
  mandatory limitations, immutable replay, and M1A/DailyMed compatibility:
  preserved.

Independent Review004 validation:

- focused candidate validation: `308 passed, 3 skipped`;
- full offline socket-disabled suite: `1424 passed`, two expected warnings,
  `80%` coverage;
- Ruff: PASS;
- format: PASS, `95` files;
- MyPy: PASS, `45` source files;
- `git diff --check`: PASS;
- exact authorized-path and dependency-boundary checks: PASS.

Boundaries:

- FAERS/openFDA and other medical-source requests: `0`;
- other external network requests: `0`;
- no new dependency, API/report route, FAERS-003 behavior, real provider
  fixture, patient narrative, or persistence expansion was introduced;
- reviewer filesystem and Git writes: `0`.

Review004 authorizes progression to the separately required terminal evidence
audit. It does not itself claim terminal-audit PASS, commit, push, pull request,
CI, merge, integrated verification, completion, or FAERS-003 readiness.
