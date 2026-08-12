# M1B-DM-001 Independent Review 006

## Verdict

`FAIL — P0 0 / P1 1 / P2 0`

The finding is a same-class exact provenance-binding defect under the frozen
semantics. Owner-authorized mechanical remediation remains in progress under
the explicit do-not-stop clause. This failed verdict does not authorize PASS,
terminal audit, or any Git/integration lifecycle step.

## Candidate identity and boundary

- Branch: `feat/m1b-dm-001-contract-freeze`
- HEAD/baseline: `ebcd11eb91aa02ae9a7115188ea10604e9f335d1`
- Exact candidate manifest:
  `75416c4fb6a3df9bbcf40783bcc4aab9f12e3d3c8df9118fdaebfe7f756dbeef`
- Medical-source and other network requests: none
- Git mutations, dependency changes, schema changes, and DM-002 work: none

The immutable prior review files remain byte-identical:

| Review | Bytes | SHA-256 |
|---|---:|---|
| 001 | 3,706 | `77fe15b782d9787c71b3f9d9cd0b38f02e5350e56f1c03bdc3eb60bb315c33a2` |
| 002 | 3,680 | `a12ee20819c603d7e76b348aa0dcb049f82b01b0a93e0822eca0f58c66bca718` |
| 003 | 5,847 | `173c3b853cd5da1dccf435df3e1a271c06d2335c67956b0c193a4fd139777484` |
| 004 | 4,610 | `9b37d9c30cc3fe39b3a3ca8fe282379c430f24f5d34bf3f4c32cea23630f90f8` |
| 005 | 4,448 | `57fc6efee6023c0d8ea2a0cfc565a0d11ac3f4982f4615e4e38280036b3547fd` |

## Verified prior closures

Review 006 verified the post-Review 005 closure of authoritative candidate
discovery and candidate-set identity, trusted outcome/manifest context, and
complete optional locator decision/retained-response identity comparison.
Earlier Review 001–004 closures remain intact.

## P1-01 — Report permits cross-request acquisition identity reuse

A two-request report was rebuilt three times. In each case only one field of
section 2's discovery reference was replaced with section 1's value while its
query, acquisition intent, ordinal, operation, and every other field remained
constant. The trusted request/ref/outcome tuples were rebuilt from the forged
references and outcomes. `M1BResearchReportV1.validate_against` accepted all
three variants:

```text
acquisition_id ACCEPTED_CROSS_REQUEST_REUSE
snapshot_id ACCEPTED_CROSS_REQUEST_REUSE
source_outcome_id ACCEPTED_CROSS_REQUEST_REUSE
```

The report validates source/query disjointness and acquisition-ordinal
uniqueness, but it does not require acquisition IDs, snapshot IDs, and source
outcome IDs to be globally unique across the complete report. A caller can
therefore construct internally self-consistent trusted tuples that reuse one
request's acquisition identity in another request.

Acceptance criteria using existing models and frozen semantics:

1. Reject duplicate `acquisition_id`, `snapshot_id`, or `source_outcome_id`
   anywhere in the report's trusted acquisition collection.
2. Add two-request adversarial tests that mutate each of those three identity
   dimensions independently while holding every other field constant.
3. Preserve all existing positive single-request and multi-request cases.

## Validation evidence

```text
Focused gate: 319 passed in 0.74s
Combined DailyMed/OpenAPI gate: 321 passed in 1.16s
Ruff check: passed
Ruff format: 67 files already formatted
MyPy --no-incremental: 34 source files passed
Full unit/contract suite: 935 passed, 2 expected warnings, 80% coverage in 9.60s
git diff --check: passed
```

The warnings are the existing Starlette TestClient deprecation and deliberate
socket-block assertion. Green tests do not override the reproduced
cross-request counterexamples.

## Lifecycle result

Review 006 is `FAIL`. Same Owner-authorized same-class mechanical remediation
is in progress. Fresh Review 007 and terminal evidence audit remain pending.
Do not claim PASS or perform commit, push, PR, CI, ready transition, merge,
integration, network execution, or `M1B-DM-002`.
