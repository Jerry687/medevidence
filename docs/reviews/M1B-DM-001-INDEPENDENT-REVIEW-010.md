# M1B-DM-001 Independent Review 010

## Verdict

`FAIL - P0 0 / P1 1 / P2 0`

Review 009 closed direct model-validation bypasses, but complete accepted-instance
revalidation was still missing at public projection/comparator methods and for
trusted model arguments. Reproducible counterexamples override the green suite.

## Candidate identity and boundary

- Branch: `feat/m1b-dm-001-contract-freeze`
- HEAD/baseline: `ebcd11eb91aa02ae9a7115188ea10604e9f335d1`
- Owner freeze SHA-256:
  `e44778f42585134634e2311e16d61d2269f3da06f79ac74c8ed37cbaa701ea70`
- Exact 27-path ordinal manifest:
  `6955add1ad6e5f0d58517a749fb8b9f7b41fc1c384784ca8e11da8194b97e8e0`
- Review 009: 4,528 bytes, SHA-256
  `245d63c614681c4c025a609a82ba58aad01a1fd5630a5a0813652d4c0cff6f24`
- Medical-source and other network requests: none
- Git mutations, dependencies, schema, connector/parser, and DM-002 changes: none

Reviews 001-009 remain immutable historical evidence.

## P1-01 - Public methods accepted invalid existing instances

The following executable manifestations were accepted:

- `LabelSelectionWarning.validate_against` accepted warning instances with
  `message="forged warning"` or `schema_version="evil"`.
- `DailyMedCandidateLabel.as_binding` accepted drifted schema, SETID, discovery,
  and other identity fields without complete self-revalidation.
- `LabelSelectionDecision.selected_from_discovery` accepted a trusted
  `SourceOutcome` instance with `schema_version="evil"`.
- `M1BResearchReportV1.validate_against` accepted trusted report outcomes with
  invalid schema versions.
- `RetainedSplResponse.validate_against` accepted decision schema/member drift
  and fetch-outcome schema drift.
- `DailyMedLocatorV1.validate_against` accepted decision schema/member drift and
  discovery/fetch outcome schema drift.

Configuration-level `revalidate_instances="always"` is not sufficient when a
method reads an already-constructed instance directly. Every public DM-001
factory, projection, and comparator must reconstruct and fully validate its
self object and every accepted model argument before use.

## Acceptance criteria

Using existing models and without schema expansion:

1. Reconstruct or fully revalidate warning self/decision and candidate self
   before projection.
2. Revalidate decision factory/validator outcomes and candidates.
3. Revalidate retained-response self, decision, outcome, label version, and
   stable sections.
4. Revalidate locator self, outcomes, decision, retained response, label
   version, and section.
5. Revalidate report self/request and every trusted request, reference,
   outcome, decision, candidate, and nested report object.
6. Add direct one-field `model_copy` adversarial tests while preserving all
   canonical serialization and positive paths.

## Validation evidence

```text
Reports/source-outcomes focused gate: 273 passed
Complete domain plus byte-exact OpenAPI: 372 passed
Full offline suite: 951 passed, 2 expected warnings
Coverage: 80%
Ruff check: passed
Ruff format check: 67 files already formatted
MyPy --no-incremental: 34 source files passed
git diff --check: passed
```

The warnings are the existing Starlette TestClient deprecation and deliberate
socket-block assertion.

## Lifecycle result

Review 010 is `FAIL - P0 0 / P1 1 / P2 0`. Terminal audit and every Git/GitHub
integration step remain gated pending same-class remediation, fresh complete
independent review, and terminal evidence audit. No network request or DM-002
work is authorized or performed by this review.
