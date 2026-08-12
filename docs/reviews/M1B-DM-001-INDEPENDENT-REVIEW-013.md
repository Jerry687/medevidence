# M1B-DM-001 Independent Review 013

## Verdict

`FAIL — P0 0 / P1 1 / P2 0`

## Candidate identity

- Branch: `feat/m1b-dm-001-contract-freeze`
- HEAD/baseline: `ebcd11eb91aa02ae9a7115188ea10604e9f335d1`
- Freeze SHA-256:
  `e44778f42585134634e2311e16d61d2269f3da06f79ac74c8ed37cbaa701ea70`
- Exact 30-path ordinal/no-terminal-LF manifest:
  `c5ac09050724eab58b489b859d6a34d9e355ecca2adfd74bc843faf72396b959`
- Review 012: 3,715 bytes, SHA-256
  `3053717d5d4699b37f05c05ff90db076676351a4303fc52195770e0296264a26`
- Index empty; no network, dependency, connector/parser, API, persistence,
  schema, DM-002, or Git mutation occurred.

## P1-01 — Public fetch comparators accept a coherently forged acquisition chain

`RetainedSplResponse.validate_against` receives a SourceOutcome but no trusted
fetch acquisition reference, so it authenticates only source, query, and
terminal triple. `DailyMedLocatorV1.validate_against` likewise receives no
trusted fetch acquisition identity and permits retained response omission.

Using the existing positive fixture, the reviewer substituted fetch
acquisition ID, attempt, intent, ordinal `1` to valid later ordinal `7`,
snapshot, manifest, source-outcome ID, member/link identities, and updated the
retained response and locator consistently with a recomputed retained-response
ID. Both public comparators accepted:

```text
ACCEPTED_COHERENT_FOREIGN_FETCH_CHAIN
```

The authoritative report comparator rejected the same chain because its
trusted acquisition union differed. This isolates the defect to the two public
fetch comparators.

Required closure: require existing trusted fetch acquisition context at both
public comparators; reject omission; compare every applicable acquisition,
attempt, intent, ordinal, operation, query, snapshot, manifest, outcome,
member/link/raw-artifact/hash identity; add one-field and coherent-chain
adversarial tests. No new serialized field, model, schema, dependency, or
connector/parser behavior is needed.

## Verified closures and gates

Review 012's mandatory selection-context closure is verified. No other defect
was reproduced in prior context/outcome closure, selection/partial/pinned/
no-result semantics, ownership/cardinality, SETID/SPL identity, LOINC,
trust/XML/ZIP policy, M1A/OpenAPI compatibility, or authorized scope.

```text
Domain plus byte-exact OpenAPI: 380 passed in 0.82s
Full offline: 959 passed, 2 expected warnings in 6.68s
Coverage: 80%
Ruff check: passed
Ruff format: 67 files already formatted
MyPy --no-incremental: 34 source files passed
git diff --check: passed
```

## Lifecycle result

Review 013 is `FAIL — P0 0 / P1 1 / P2 0`. It is a mechanically equivalent
exact-comparator omission within the Owner-authorized closure. Terminal audit
and all Git/PR/CI/merge/integration steps remain prohibited pending a fresh
independent `0/0/0` review.
