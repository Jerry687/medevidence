# M1B-DM-001 Independent Review 012

## Verdict

`FAIL — P0 0 / P1 1 / P2 0`

The offline/static gates are green, but a reproducible authoritative-provenance
bypass remains. Terminal audit and all Git/PR/CI/merge/integration operations
must not proceed.

## Candidate identity

- Branch: `feat/m1b-dm-001-contract-freeze`
- HEAD/baseline: `ebcd11eb91aa02ae9a7115188ea10604e9f335d1`
- Owner freeze SHA-256:
  `e44778f42585134634e2311e16d61d2269f3da06f79ac74c8ed37cbaa701ea70`
- Exact 29-path ordinal/no-terminal-LF manifest:
  `8445fb3a9c2bed48819b03c8989f4d9ef593f3d7ede874f9010b417697f1d188`
- Review 011: 4,301 bytes, SHA-256
  `305c8625f945aaadc8559f23364910896fe895d0675eadc2cac77e4f159ea951`
- Index and unauthorized paths: empty
- Dependency, connector/parser, API, persistence, DM-002, Git mutation, and
  medical-source network activity: none

The manifest uses ordinal Python path sorting and
`path<TAB>byte_count<TAB>lowercase_sha256` rows joined by UTF-8 LF without a
terminal LF.

## P1-01 — Locator comparison permits omission of authoritative selection context

`DailyMedLocatorV1.validate_against` declares the decision, candidate tuple,
trusted source-outcome identity, discovery-manifest hash, and retained response
optional. Complete authoritative discovery validation runs only when a
decision is supplied.

Using the existing positive report fixture, a locator with substituted
`selection_decision_id`, `selected_candidate_id`, `discovery_attempt_id`,
`discovery_manifest_id`, and `discovery_source_outcome_id` was accepted when
the comparator received only discovery/fetch outcomes, stable label, and
section:

```text
ACCEPTED_WITHOUT_AUTHORITY
candidate:foreign
decision:foreign
artifact:foreign
```

The same object rejected when complete authoritative decision context was
supplied. An internally valid retained response with recomputed identity after
the same substitutions also produced `ACCEPTED_FORGED_CHAIN` when authoritative
decision context was omitted.

Required closure: make authoritative decision, exact candidates, trusted
source-outcome identity, and manifest hash mandatory at the public locator
comparator; validate through `LabelSelectionDecision.validate_against`; remove
or make unreachable incomplete authoritative paths; ensure report intrinsic
construction does not present an incomplete comparator call as authoritative;
add omission and one-field substitution tests. No field, schema, dependency,
connector/parser behavior, or evidence semantic change is needed.

## Verified closure and evidence

Review 011's other defects are closed: arbitrary public Pydantic context cannot
authorize decisions; former intrinsic-only shortcuts are absent; warning and
retained comparators require authoritative discovery context; and the
classifier/report construction boundaries reject invalid existing
SourceOutcome instances. Complete-only/partial/no-result/pinned semantics,
request/acquisition provenance, security/XML/ZIP/LOINC policy, M1A
serialization, and byte-exact OpenAPI remain intact.

```text
Domain plus byte-exact OpenAPI: 380 passed in 0.81s
Full offline: 959 passed, 2 expected warnings in 6.71s
Coverage: 80%
Ruff check: passed
Ruff format: 67 files already formatted
MyPy --no-incremental: 34 source files passed
git diff --check: passed
```

The warnings are the existing Starlette TestClient deprecation and deliberate
socket-block assertion.

## Lifecycle result

Review 012 is `FAIL — P0 0 / P1 1 / P2 0`. This is a mechanically equivalent
missing exact comparator within the Owner-authorized same-class closure.
Terminal audit and every Git/PR/CI/merge/integration step remain prohibited
until a fresh complete independent review returns `0/0/0`.
