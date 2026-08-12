# M1B-DM-001 Independent Review 011

## Verdict

`FAIL — P0 0 / P1 2 / P2 0`

Review 010 closed its originally reproduced direct mutations, but two
accepted-instance trust-boundary defects remain. Reproducible counterexamples
override the green suite and prevent terminal audit or Git lifecycle
progression.

## Candidate identity

- Branch: `feat/m1b-dm-001-contract-freeze`
- HEAD/baseline: `ebcd11eb91aa02ae9a7115188ea10604e9f335d1`
- Owner freeze SHA-256:
  `e44778f42585134634e2311e16d61d2269f3da06f79ac74c8ed37cbaa701ea70`
- Exact 28-path ordinal/no-terminal-LF manifest:
  `564e352be9ad2470c58be20156036c9f66f8aa90ad9964048f085dc6d5de254b`
- Review 010: 3,536 bytes, SHA-256
  `75c35c0360d02c062e7dc3a68e0565035230af11b19c88d46882aa1551ad56d0`
- Index: empty
- Network, Git mutation, dependency, schema, connector/parser, persistence, and
  DM-002 activity: none

Reviews 001–010 remain immutable historical evidence.

## P1-01 — Caller-controlled intrinsic context bypasses decision authority

`LabelSelectionDecision.validate_decision_shape` returns before authoritative
outcome/candidate validation when caller-supplied Pydantic context contains
`{"intrinsic_only": true}`. The public `revalidate_intrinsic` method and the
warning, retained-response, locator, and report comparators use that shortcut.

A selected decision whose SETID/version were changed to
`99999999-9999-9999-9999-999999999999` / `99`, with a recomputed decision ID,
was accepted by direct `model_validate(..., context={"intrinsic_only": true})`
while real authoritative outcome/candidate validation rejected it. A changed
`discovery_manifest_content_hash` with recomputed decision ID also passed
`revalidate_intrinsic`, warning, retained-response, and locator comparison,
but failed the authoritative `LabelSelectionDecision.validate_against` call.

Required closure: remove the caller-forgeable bypass; require complete trusted
discovery context at warning, retained-response, locator, and report decision
boundaries; reject direct context injection and all propagated selected
identity, manifest, candidate, outcome, and warning provenance drift without
adding serialized fields or changing selection semantics.

## P1-02 — Classifier and report construction accept invalid SourceOutcome instances

The exported `classify_dailymed_selection` accepted
`valid_outcome.model_copy(update={"schema_version": "evil"})` and returned
`selected`. `M1BResearchReportV1.create` and direct report `model_validate`
also accepted and preserved an existing nested `SourceOutcome` with the same
invalid schema version, including a nested model-copy report path.

Required closure: fully reconstruct every SourceOutcome before classification
and within the report's own model/factory/direct-validation boundary; add
one-field accepted-instance adversarial coverage; preserve the inherited seven
outcome triples, M1A serialization, partial/no-result semantics, and byte-exact
OpenAPI behavior.

## Verified Review 010 closure and other requirements

The targeted Review 010 mutations now reject: warning message/schema,
candidate schema/SETID/completeness/termination, invalid decision-factory
outcome, retained/locator decision schema/member and outcome schema, and
trusted report-outcome drift. No other finding was reproduced in complete-only
selection, partial/no-result semantics, pinned behavior, request-owned
provenance, acquisition cardinality/uniqueness, SETID/SPL rules, frozen
trust/XML/ZIP/LOINC policy, M1A/OpenAPI compatibility, or scope/network
boundaries.

## Validation evidence

```text
Reports/source-outcomes focused: 274 passed
Domain plus byte-exact OpenAPI: 373 passed
Security/LOINC/selection focused: 128 passed, 77 deselected
Full unit/contract suite: 952 passed, 2 expected warnings
Coverage: 80%
Full-suite duration: 6.42s
Ruff check: passed
Ruff format check: 67 files already formatted
MyPy --no-incremental: 34 source files passed
git diff --check: passed
```

The warnings are the existing Starlette TestClient deprecation and deliberate
socket-block assertion.

## Lifecycle result

Review 011 is `FAIL — P0 0 / P1 2 / P2 0`. Terminal audit and every Git/PR/CI/
merge/integration step remain prohibited until the same-class mechanical
closure is independently reviewed at `P0/P1/P2 = 0/0/0`.
