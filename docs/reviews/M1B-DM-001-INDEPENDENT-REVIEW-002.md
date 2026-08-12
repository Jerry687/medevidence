# M1B-DM-001 Independent Review 002

## Verdict

`FAIL — P0 0 / P1 1 / P2 1`

This verdict binds only the candidate manifest
`f8c9cb5b13a93d4c15847855785afac80d16e0332462a9b0734e9cb576769ffe`
on branch `feat/m1b-dm-001-contract-freeze` at baseline
`ebcd11eb91aa02ae9a7115188ea10604e9f335d1`.

## Identity and review boundary

- Work item: `M1B-DM-001`
- Owner freeze SHA-256:
  `e44778f42585134634e2311e16d61d2269f3da06f79ac74c8ed37cbaa701ea70`
- Immutable Review 001 SHA-256:
  `77fe15b782d9787c71b3f9d9cd0b38f02e5350e56f1c03bdc3eb60bb315c33a2`
- Candidate authorized-path scope: exact 19 paths
- Network and medical-source access: none
- Reviewer writes, Git mutations, dependency changes, and outer-path changes:
  none

## Closure verification from Review 001

- P1-01 original and same-class weakened policy constructions all reject.
- P1-02 discovery/fetch acquisition IDs, snapshot IDs, and ordinal constraints
  are correct.
- The allowed `(0, 2)` ordinal pair with the same acquisition intent accepts.

## Findings

### P1 — Report accepts a DailyMed request owned by a different drug scope

`M1BResearchReportV1.validate_m1b_report` in
`src/medevidence/domain/reports.py:793` checks embedded request uniqueness at
lines 821–823, but never verifies that
`section.request.drug_concept_id` belongs to `self.scope.drugs`. It also does
not bind the section request to the `M1BResearchRequestV1` identified by
`request_id`; `src/medevidence/domain/scope.py:259` validates the request
envelope, while the report retains only its ID.

Counterexample:

```text
report.scope.drugs[0].concept_id="drug:test"
report.source_sections[0].request.drug_concept_id="drug:foreign"
ACCEPTED_FOREIGN_SECTION_REQUEST drug:test drug:foreign request:00000000-0000-4000-8000-000000000011
```

This violates the frozen rule that a singular source section binds exactly one
existing source request-array element and permits cross-drug evidence
attribution. Missing adversarial cases are foreign-drug, foreign request
envelope, and request-ID ownership.

Acceptance criterion: reject a foreign drug at the model boundary and provide
an exact comparator to the existing request envelope without schema expansion.

### P2 — Mandatory acquisition-cardinality matrix is not tested

The freeze requires positive acquisition totals one through eight and rejection
of a ninth acquisition. Current tests cover one or two references and a
cross-request duplicate ordinal only. The implementation is structurally
bounded, but mandatory evidence for the full matrix is absent.

Acceptance criterion: add actual report tests for every total from one through
eight plus a ninth-acquisition rejection, retaining at most four search and
four fetch acquisitions and one or two acquisitions per request.

## Validation evidence

The reviewer verified:

```text
DailyMed focused plus byte-exact OpenAPI: 273 passed
Ruff check: passed
Ruff format check: passed
MyPy --no-incremental: passed, 34 source files
Full offline unit/contract suite: 887 passed, 2 existing warnings
```

The two warnings are the existing Starlette TestClient deprecation and the
deliberate socket-block assertion. Green validation does not override the P1
counterexample or supply the missing P2 evidence.

## Lifecycle decision

Review 002 is `FAIL`. The P1 is treated as same-class P1-02 mechanical
remediation within the Owner-authorized extra cycle 1/1; the P2 is its
mechanically dependent mandatory evidence. Remediation is in progress. Fresh
independent Review 003 and terminal audit remain pending. Do not claim PASS or
perform commit, push, PR, CI, merge, integration, `M1B-DM-002`, or network
execution from this candidate.
