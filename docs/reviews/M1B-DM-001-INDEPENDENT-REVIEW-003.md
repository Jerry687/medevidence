# M1B-DM-001 Independent Review 003

## Verdict

`FAIL — P0 0 / P1 2 / P2 0`

A reproducible report-provenance defect overrides the green offline suite.
Terminal audit requires `0/0/0` and must not proceed.

## Identity and scope

- Branch: `feat/m1b-dm-001-contract-freeze`
- HEAD/baseline: `ebcd11eb91aa02ae9a7115188ea10604e9f335d1`
- Freeze SHA-256:
  `e44778f42585134634e2311e16d61d2269f3da06f79ac74c8ed37cbaa701ea70`
- Review 001 SHA-256:
  `77fe15b782d9787c71b3f9d9cd0b38f02e5350e56f1c03bdc3eb60bb315c33a2`
- Review 002 SHA-256:
  `a12ee20819c603d7e76b348aa0dcb049f82b01b0a93e0822eca0f58c66bca718`
- Exact 20-path candidate manifest:
  `06b77e138ed4f87b2ddc749ef8eb67fd214b61512714f56b95e881afbbeeb6b3`
- Staged paths: zero
- `git diff --check`: passed
- Connector, parser, API, migration, persistence, dependency, schema, DM-002,
  and outer-path changes: none

## Findings

### P1-1 — Report outcome references are not bound to authoritative acquisition outcomes

`AcquisitionOutcomeRef` carries acquisition ID, intent, ordinal, operation,
source-outcome ID, and snapshot. The inherited `SourceOutcome` has none of
those identity fields, only source/query/status/content fields.

`M1BResearchReportV1.validate_m1b_report` joins references to outcomes only by
`(source, query_id)`. Consequently, arbitrary well-typed acquisition, snapshot,
intent, and outcome identities are accepted. The request-envelope comparator
does not close this boundary.

Reproducer:

```python
import runpy
from medevidence.domain import M1BResearchReportV1

ns = runpy.run_path("tests/unit/domain/test_reports.py")
report, request = ns["dailymed_report_for_acquisition_counts"]((1,))

for field, value in (
    ("source_outcome_id", "source-outcome:foreign"),
    ("acquisition_id", "acquisition:foreign"),
    ("acquisition_intent_id", "acquisition-intent:sha256:" + "f" * 64),
    ("snapshot_id", "snapshot:foreign"),
):
    payload = report.model_dump(mode="python")
    payload["source_sections"][0]["acquisition_outcome_refs"][0][field] = value
    accepted = M1BResearchReportV1.model_validate(payload)
    accepted.validate_against(request)
    print(field, getattr(accepted.source_sections[0].acquisition_outcome_refs[0], field))
```

Observed:

```text
source_outcome_id source-outcome:foreign
acquisition_id acquisition:foreign
acquisition_intent_id acquisition-intent:sha256:ffff...ffff
snapshot_id snapshot:foreign
```

This violates the frozen exact acquisition/outcome-reference union and permits
a report to attribute a valid outcome payload to a foreign acquisition or
outcome row.

Acceptance criterion: without changing serialized schemas or adding a public
concept, extend the existing exact-comparator pattern to require trusted
canonical `AcquisitionOutcomeRef` and `SourceOutcome` tuples, compare every
reference field exactly, and compare the canonical outcome sequence exactly.
Both necessary types already exist. Comparing only current report internals is
insufficient because `SourceOutcome` has no source-outcome ID or acquisition
tuple. Mutating inherited `SourceOutcome` is unauthorized and unnecessary.

### P1-2 — Retained response and locator can disagree on selected candidate and discovery provenance

The retained-response comparison omits `candidate_set_snapshot_id` and
`selected_candidate_id`. The locator-to-retained comparison also omits
`selected_candidate_id`. Although `DailyMedLocatorV1.validate_against` can
compare those fields when passed a retained response and decision, the report
does not pass either object.

Accepted serialized counterexamples:

```text
ACCEPTED_LOCATOR_SELECTED_CANDIDATE_DRIFT
retained=dailymed-candidate:sha256:959cb84c...
locator=candidate:foreign

ACCEPTED_RETAINED_DISCOVERY_SNAPSHOT_DRIFT
discovery_ref=snapshot:dailymed-discovery
retained=snapshot:foreign
```

This contradicts ADR-011's requirement that `RetainedSplResponse` close the
selected/fetch/stable binding and that locator fetch fields bind to it.

Acceptance criteria within existing authorized models and fields:

1. Compare `retained_response.candidate_set_snapshot_id` with the discovery
   reference snapshot.
2. Compare locator and retained-response `selected_candidate_id`.
3. Pass `retained_response` to `locator.validate_against`.
4. Add serialized negative tests for each drift.

## Verified prior closures

Review 001 findings are closed:

- Original and same-class weakened policy tuples reject.
- Omission, duplication, reordering, redirect/transport drift, permanent-class
  drift, trust-path drift, and ZIP path-class drift reject.
- Discovery/fetch acquisition IDs and snapshots differ; fetch ordinal is
  strictly later; global `(run_id, source, acquisition_ordinal)` ownership is
  enforced; `(0, 2)` with the same intent remains accepted.

Review 002 findings are closed:

- Foreign-scope section drugs reject.
- `validate_against(M1BResearchRequestV1)` checks request ID, scope, source set,
  and the exact DailyMed request array.
- Actual report totals one through eight accept and a ninth acquisition rejects.

## Validation and network evidence

```text
DailyMed domain plus byte-exact OpenAPI: 285 passed
Ruff check: passed
Ruff format: 67 files already formatted
MyPy --no-incremental: 34 source files passed
Full unit/contract suite: 899 passed, 2 expected warnings, 80% coverage
```

The two warnings are the existing Starlette TestClient deprecation and the
deliberate socket-block assertion. No medical-source or other network request
was made. Post-validation identity remained the exact same 20-path manifest.

## Lifecycle result

The Owner-authorized extra remediation cycle 1/1 is consumed. Status is
`OWNER_DECISION_REQUIRED` for another bounded mechanical remediation cycle.
Do not run terminal audit, commit, push, PR, CI, merge, integration, or
`M1B-DM-002` from this candidate.
