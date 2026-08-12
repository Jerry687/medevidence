# M1B-DM-001 Independent Review 005

## Verdict

`FAIL — P0 0 / P1 2 / P2 0`

The findings are same-class exact-binding defects under frozen semantics.
Batch mechanical remediation remains in progress under the Owner-authorized
same-class clause. This failed verdict does not authorize PASS or terminal
audit.

## Candidate identity and boundary

- Branch: `feat/m1b-dm-001-contract-freeze`
- HEAD/baseline: `ebcd11eb91aa02ae9a7115188ea10604e9f335d1`
- Exact 22-path candidate manifest:
  `420cfd5a5ec52a30d53dee54d5bac2cfff2a11c0b450e03031434d4ea1881bca`
- Authorized paths: 22
- Medical-source and other network requests: none
- Git mutations, dependency changes, and outer-path changes: none

## Verified prior closures

Review 005 verified Review 004's three manifestations are closed: selected
decision identity matches its authoritative candidate, exact pinned selection
matches the pin, and request-owned trusted tuples reject cross-request bundle
swaps. Earlier Review 001–003 closures remain intact.

## P1-01 — Decision accepts foreign discovery and candidate-set identity

A direct decision using authoritative candidate context accepted each one-field
mutation after recomputing `decision_id`:

```text
run_id ACCEPT
attempt_id ACCEPT
acquisition_id ACCEPT
acquisition_ordinal ACCEPT
acquisition_intent_id ACCEPT
candidate_set_snapshot_id ACCEPT
discovery_manifest_id ACCEPT
candidate_set_id ACCEPT
discovery_manifest_content_hash ACCEPT
```

The same missing authority propagated end to end. A selected failed-fetch
report accepted each of these fields:

```text
selected_failed_fetch attempt_id ACCEPTED_END_TO_END
selected_failed_fetch discovery_manifest_id ACCEPTED_END_TO_END
selected_failed_fetch candidate_set_id ACCEPTED_END_TO_END
selected_failed_fetch discovery_manifest_content_hash ACCEPTED_END_TO_END
```

Review-required and no-candidate report paths likewise printed `<field>
ACCEPTED` for `attempt_id`, `discovery_manifest_id`, `candidate_set_id`, and
`discovery_manifest_content_hash`.

This allows a correctly rehashed decision to claim a foreign discovery or
candidate set while retaining otherwise valid report evidence.

Acceptance criteria using existing fields and models:

1. Compare every candidate discovery field: run, source, attempt, acquisition,
   ordinal, intent, query, snapshot, and manifest.
2. Recompute `candidate_set_id` for positive-candidate and zero-candidate
   decisions.
3. Require trusted primitive context for discovery-manifest hash and source
   outcome identity.
4. Add one-field negatives through selected failed-fetch, review-required, and
   no-candidate report paths.

## P1-02 — Locator optional exact comparators omit duplicated identities

The decision/locator comparator accepted different label identities:

```text
ACCEPTED_LOCATOR_DECISION_LABEL_DRIFT
decision = 11111111-1111-1111-1111-111111111111 / 3
locator  = 22222222-2222-2222-2222-222222222222 / 4
```

The retained-response/locator comparator accepted simultaneous drift in every
listed stable identity:

```text
ACCEPTED_LOCATOR_RETAINED_STABLE_DRIFT
locator  = original run/snapshot/SETID/version/label_version_id
retained = foreign run/snapshot/SETID/version/label_version_id
```

The optional exact comparator omits duplicated run, SETID, SPL version,
snapshot, and label-version identities. Passing both optional objects does not
repair comparisons absent from each branch.

Acceptance criteria:

1. Compare every duplicated decision/locator identity.
2. Compare every duplicated retained-response/locator identity.
3. Add decision-only, retained-only, and both-object drift tests.

## Validation evidence

```text
Focused four-domain gate: 308 passed in 0.46s
DailyMed plus byte-exact OpenAPI: 310 passed in 0.76s
Review 004 target gate: 13 passed in 0.21s
Ruff check: passed
Ruff format: 67 files already formatted
MyPy --no-incremental: 34 source files passed
Full unit/contract suite: 924 passed, 2 expected warnings, 80% coverage in 7.18s
git diff --check: passed
```

The warnings are the existing Starlette TestClient deprecation and deliberate
socket-block assertion. Green tests do not override the accepted
counterexamples.

## Lifecycle result

Review 005 is `FAIL`. Same Owner-authorized same-class batch remediation is in
progress. Fresh Review 006 and terminal audit remain pending. Do not claim PASS
or perform commit, push, PR, CI, merge, integration, network execution, or
`M1B-DM-002`.
